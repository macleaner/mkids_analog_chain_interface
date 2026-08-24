"""
Signal chain class for managing ordered components and calculating
gain and noise propagation through the chain.

Also owns serialization: a chain knows how to write itself to, and rebuild
itself from, a JSON file. Keeping that here rather than in the GUI means a
saved chain can be loaded from a script or notebook alongside the measurement
data it describes, and can be tested without Qt.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

import registry
from utils import to_dbm, to_W

#: Bumped when the on-disk layout changes in a way that needs migration.
FORMAT_VERSION = 2


def _evaluate_noise(component, spectral_frequency):
    """
    Evaluate a component's noise PSD in W/Hz, or return None if it has none.

    Components vary in whether ``noise()`` takes a frequency, so both calling
    conventions are tried. Anything other than a signature mismatch propagates:
    a model that raises is a bug to surface, not a component to silently treat
    as noiseless, which would quietly under-report the noise budget.
    """
    noise_attr = getattr(component, "noise", None)
    if noise_attr is None:
        return None
    try:
        return noise_attr(spectral_frequency)
    except TypeError:
        # Signature mismatch: the model takes no frequency argument.
        return noise_attr()


def _has_any_noise(noise_power):
    """True if this contribution is non-zero anywhere. Array-safe."""
    if noise_power is None:
        return False
    arr = np.asarray(noise_power, dtype=float)
    return bool(np.any(arr > 0))


class SignalChain:
    """
    Manages an ordered sequence of RF components and calculates
    signal gain and noise propagation through the chain.
    """

    def __init__(self, name="Signal Chain", description="", metadata=None):
        """
        Initialize an empty signal chain.

        Parameters
        ----------
        name : str
            Name/description of this signal chain
        description : str, optional
            Free-text notes. Persisted, so use it to record what this chain
            corresponds to - a cooldown, a deployment, a measurement run.
        metadata : dict, optional
            Arbitrary JSON-serializable bookkeeping fields (cooldown id, sample
            name, dataset path, operator...). Persisted verbatim.
        """
        self.name = name
        self.description = description
        self.metadata = dict(metadata) if metadata else {}
        self.components = []
        self.labels = {}  # Map label -> index
        self.dac = None  # DAC at start of chain
        self.adc = None  # ADC at end of chain
        #: Non-fatal issues from the most recent load(), for the caller to show.
        self.load_warnings: List[str] = []

    def set_digitizer(self, dac, adc):
        """
        Set the DAC and ADC components for the chain.
        
        Parameters
        ----------
        dac : DACComponent
            The DAC component (placed at start of chain)
        adc : ADCComponent
            The ADC component (placed at end of chain)
        """
        self.dac = dac
        self.adc = adc
    
    def get_digitizer(self):
        """
        Get the DAC and ADC components.
        
        Returns
        -------
        tuple
            (dac, adc) components
        """
        return (self.dac, self.adc)
    
    def get_full_component_list(self):
        """
        Get the complete component list including DAC and ADC.
        
        Returns
        -------
        list
            [DAC, component1, component2, ..., ADC]
        """
        full_list = []
        if self.dac is not None:
            full_list.append(self.dac)
        full_list.extend(self.components)
        if self.adc is not None:
            full_list.append(self.adc)
        return full_list
    
    def add_component(self, component, label=None):
        """
        Add a component to the end of the chain.
        
        Parameters
        ----------
        component : Component or object with gain() and noise() methods
            The component to add
        label : str, optional
            Label to identify this component for later reference
            
        Returns
        -------
        int
            Index of the added component
        """
        idx = len(self.components)
        self.components.append(component)
        
        # Auto-generate label if not provided
        if label is None:
            label = f"{component.__class__.__name__}_{idx}"
        
        # Store label mapping
        self.labels[label] = idx
        
        # Also store label on the component if it doesn't have a name
        if hasattr(component, 'name'):
            if component.name == component.__class__.__name__:
                component.name = label
        
        return idx
    
    def get_index(self, reference):
        """
        Get the index of a component from either an index or label.
        
        Parameters
        ----------
        reference : int or str
            Either an integer index or a string label
            
        Returns
        -------
        int
            The component index
        """
        if isinstance(reference, int):
            if 0 <= reference < len(self.components):
                return reference
            else:
                raise IndexError(f"Component index {reference} out of range")
        elif isinstance(reference, str):
            if reference in self.labels:
                return self.labels[reference]
            else:
                raise KeyError(f"Label '{reference}' not found in chain")
        else:
            raise TypeError("Reference must be int (index) or str (label)")
    
    def gain_between(self, start, end, frequency):
        """
        Calculate cumulative gain from start component to end component.
        
        Parameters
        ----------
        start : int or str
            Starting component (index or label)
        end : int or str
            Ending component (index or label)
        frequency : float or np.ndarray
            Frequency in Hz
            
        Returns
        -------
        float or np.ndarray
            Total gain in dB (negative indicates net loss)
        """
        start_idx = self.get_index(start)
        end_idx = self.get_index(end)
        
        # Ensure proper order
        if start_idx > end_idx:
            start_idx, end_idx = end_idx, start_idx
        
        # Sum gains from start to end (inclusive of start, exclusive of end+1)
        total_gain_db = 0.0
        for idx in range(start_idx, end_idx + 1):
            component = self.components[idx]
            if hasattr(component, 'gain'):
                total_gain_db += component.gain(frequency)
        
        return total_gain_db
    
    def noise_at_point(self, reference_point, carrier_frequency, spectral_frequency, contributions=False):
        """
        Calculate total noise at a reference point from all upstream sources.
        
        Each component's noise contribution is propagated through all
        downstream components to the reference point.
        
        Parameters
        ----------
        reference_point : int or str
            The point in the chain to calculate noise at
        carrier_frequency : float or np.ndarray
            Carrier frequency in Hz (used for gain calculations and frequency-dependent noise)
        spectral_frequency : float or np.ndarray
            Spectral/offset frequency in Hz (used for noise spectral shape, e.g., 1/f noise)
        contributions : bool, optional
            If True, return a dict with individual component contributions
            
        Returns
        -------
        float or np.ndarray
            Total noise power spectral density in W/Hz
        dict (if contributions=True)
            Dictionary mapping component labels to their noise contributions
        """
        ref_idx = self.get_index(reference_point)

        total_noise_W = 0.0
        noise_dict = {}

        # Every component up to and including the reference point.
        for idx in range(ref_idx + 1):
            noise_power = _evaluate_noise(self.components[idx], spectral_frequency)
            if not _has_any_noise(noise_power):
                continue

            # Gain from this component to the reference point, at the carrier.
            gain_db = self.gain_between(idx, ref_idx, carrier_frequency)

            # N_out_dBm = N_in_dBm + G_dB
            noise_at_ref_W = to_W(to_dbm(noise_power) + gain_db)
            total_noise_W = total_noise_W + noise_at_ref_W

            if contributions:
                noise_dict[self._get_label_for_index(idx)] = noise_at_ref_W

        if contributions:
            return total_noise_W, noise_dict
        return total_noise_W


    def _get_label_for_index(self, idx):
        """Find the label for a given index."""
        for label, label_idx in self.labels.items():
            if label_idx == idx:
                return label
        return f"Component_{idx}"

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize the chain to a JSON-ready dict.

        Each component records its stable registry type id and the exact
        parameters it was constructed with, plus its chain label - so an
        analysis result can refer to a point in the chain by name and still
        resolve after the chain is reordered.
        """
        return {
            "format_version": FORMAT_VERSION,
            "name": self.name,
            "description": self.description,
            "metadata": dict(self.metadata),
            "saved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "digitizer": {
                "dac": self.dac.to_dict() if self.dac is not None else None,
                "adc": self.adc.to_dict() if self.adc is not None else None,
            },
            "components": [
                dict(component.to_dict(), label=self._get_label_for_index(idx))
                for idx, component in enumerate(self.components)
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SignalChain":
        """
        Rebuild a chain from ``to_dict`` output.

        Accepts both the current format and the two earlier GUI formats (a bare
        list of components, and a dict with a flat ``digitizer`` config), so
        previously-saved files keep working.
        """
        warnings: List[str] = []

        if isinstance(data, list):
            # Oldest format: a bare list of component dicts, no digitizer.
            data = {"components": data}

        version = data.get("format_version", 1)
        if version > FORMAT_VERSION:
            warnings.append(
                f"file declares format_version {version} but this build "
                f"understands up to {FORMAT_VERSION}; loading anyway"
            )

        chain = cls(
            name=data.get("name", "Signal Chain"),
            description=data.get("description", ""),
            metadata=data.get("metadata"),
        )

        for entry in data.get("components", []):
            type_id = entry.get("type") or entry.get("class")
            if type_id is None:
                warnings.append(f"skipped a component with no type: {entry!r}")
                continue
            params = entry.get("params", entry.get("parameters", {}))
            try:
                component = registry.create(
                    type_id, params, name=entry.get("name"), warnings=warnings)
            except (KeyError, ValueError, TypeError) as exc:
                warnings.append(f"could not load component {type_id!r}: {exc}")
                continue
            # Prefer the saved label; fall back to the auto-generated one.
            chain.add_component(component, label=entry.get("label"))

        chain._load_digitizer(data.get("digitizer"), warnings)
        chain.load_warnings = warnings
        return chain

    def _load_digitizer(self, digitizer: Optional[Dict[str, Any]],
                        warnings: List[str]) -> None:
        """Restore DAC/ADC, accepting both the current and legacy layouts."""
        if not digitizer:
            return

        if "dac" in digitizer or "adc" in digitizer:
            # Current format: each converter is a full component dict.
            dac_data, adc_data = digitizer.get("dac"), digitizer.get("adc")
            dac = adc = None
            if dac_data:
                try:
                    dac = registry.create(dac_data["type"], dac_data.get("params"),
                                          warnings=warnings)
                except (KeyError, ValueError, TypeError) as exc:
                    warnings.append(f"could not load DAC: {exc}")
            if adc_data:
                try:
                    adc = registry.create(adc_data["type"], adc_data.get("params"),
                                          warnings=warnings)
                except (KeyError, ValueError, TypeError) as exc:
                    warnings.append(f"could not load ADC: {exc}")
            if dac is not None or adc is not None:
                self.set_digitizer(dac, adc)
            return

        # Legacy GUI format: a flat config dict from the digitizer panel.
        if digitizer.get("model") == "AD9082":
            try:
                self.set_digitizer(
                    registry.create("converter.ad9082_dac", {
                        "carrier_power_dbm": digitizer.get("carrier_power_dbm", 0.0),
                        "gain_db": digitizer.get("dac_gain_db", 0.0),
                    }, warnings=warnings),
                    registry.create("converter.ad9082_adc", {
                        "gain_db": digitizer.get("adc_gain_db", 0.0),
                    }, warnings=warnings),
                )
            except (KeyError, ValueError, TypeError) as exc:
                warnings.append(f"could not load legacy digitizer config: {exc}")
        else:
            warnings.append(
                f"unrecognized legacy digitizer model "
                f"{digitizer.get('model')!r}; digitizer not restored")

    def save(self, path: str) -> None:
        """Write the chain to ``path`` as JSON."""
        with open(path, "w") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    @classmethod
    def load(cls, path: str) -> "SignalChain":
        """
        Read a chain from ``path``.

        Check ``chain.load_warnings`` afterwards - a non-empty list means the
        file did not fully describe the chain that was rebuilt.
        """
        with open(path) as fh:
            data = json.load(fh)
        chain = cls.from_dict(data)
        if not chain.name or chain.name == "Signal Chain":
            chain.name = os.path.splitext(os.path.basename(path))[0]
        return chain
    
    def total_gain(self, frequency):
        """
        Calculate total gain through entire chain including DAC and ADC.
        
        Parameters
        ----------
        frequency : float or np.ndarray
            Frequency in Hz
            
        Returns
        -------
        float or np.ndarray
            Total gain in dB
        """
        total_gain_db = 0.0
        
        # Add DAC gain
        if self.dac is not None:
            total_gain_db += self.dac.gain(frequency)
        
        # Add regular component gains
        if len(self.components) > 0:
            total_gain_db += self.gain_between(0, len(self.components) - 1, frequency)
        
        # Add ADC gain
        if self.adc is not None:
            total_gain_db += self.adc.gain(frequency)
        
        return total_gain_db
    
    def output_noise(self, carrier_frequency, spectral_frequency, contributions=False):
        """
        Calculate total noise at the output of the chain including DAC and ADC.
        
        Parameters
        ----------
        carrier_frequency : float or np.ndarray
            Carrier frequency in Hz (used for gain calculations)
        spectral_frequency : float or np.ndarray
            Spectral/offset frequency in Hz (used for noise spectral shape)
        contributions : bool, optional
            If True, return a dict with individual component contributions
            
        Returns
        -------
        float or np.ndarray
            Total output noise power spectral density in W/Hz
        dict (if contributions=True)
            Dictionary mapping component labels to their noise contributions
        """
        total_noise_W = 0.0
        noise_dict = {}
        n_components = len(self.components)

        # Gain seen by noise originating downstream of the component chain.
        adc_gain = (self.adc.gain(carrier_frequency)
                    if self.adc is not None else 0.0)

        # DAC noise: propagates through every component, then the ADC.
        if self.dac is not None:
            dac_noise = _evaluate_noise(self.dac, spectral_frequency)
            if _has_any_noise(dac_noise):
                gain_to_output = adc_gain
                if n_components > 0:
                    gain_to_output = gain_to_output + self.gain_between(
                        0, n_components - 1, carrier_frequency)
                contribution = to_W(to_dbm(dac_noise) + gain_to_output)
                total_noise_W = total_noise_W + contribution
                if contributions:
                    noise_dict[self.dac.name] = contribution

        # Chain components.
        for idx in range(n_components):
            noise_power = _evaluate_noise(self.components[idx], spectral_frequency)
            if not _has_any_noise(noise_power):
                continue

            # NOTE: for the final component this deliberately excludes that
            # component's own gain, whereas noise_at_point() includes it via
            # gain_between(idx, ref_idx). The two methods therefore disagree on
            # the last component by its own gain. Preserved as-is; settling on
            # one convention is a physics decision, not a refactor.
            gain_to_output = adc_gain
            if idx < n_components - 1:
                gain_to_output = gain_to_output + self.gain_between(
                    idx, n_components - 1, carrier_frequency)

            contribution = to_W(to_dbm(noise_power) + gain_to_output)
            total_noise_W = total_noise_W + contribution
            if contributions:
                noise_dict[self._get_label_for_index(idx)] = contribution

        # ADC noise is already at the output, so it sees no further gain.
        if self.adc is not None:
            adc_noise = _evaluate_noise(self.adc, spectral_frequency)
            if _has_any_noise(adc_noise):
                total_noise_W = total_noise_W + adc_noise
                if contributions:
                    noise_dict[self.adc.name] = adc_noise

        if contributions:
            return total_noise_W, noise_dict
        return total_noise_W


    def summary(self):
        """
        Print a summary of the signal chain.
        """
        print(f"Signal Chain: {self.name}")
        print(f"Total components: {len(self.components)}")
        print("\nComponent List:")
        print("-" * 60)
        for idx, component in enumerate(self.components):
            label = self._get_label_for_index(idx)
            comp_type = getattr(component, 'component_type', 'unknown')
            print(f"  [{idx:2d}] {label:30s} ({component.__class__.__name__})")
        print("-" * 60)
    
    def __repr__(self):
        return f"SignalChain(name='{self.name}', components={len(self.components)})"
    
    def __len__(self):
        return len(self.components)
