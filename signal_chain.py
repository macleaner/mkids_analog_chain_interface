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
from noise_budget import NoiseBudget, NoiseContribution, _magnitude
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
    
    # ------------------------------------------------------------------
    # Stage / plane model
    # ------------------------------------------------------------------

    def stages(self):
        """
        The full signal path as ``(label, component, kind)`` triples.

        Ordered DAC, chain components, ADC. Planes are numbered 0..len(stages):
        plane *k* is immediately before stage *k*, and the final plane is the
        chain output. Component integer indices and labels keep addressing
        ``self.components`` as they always have; the DAC offset is applied
        internally so existing callers and saved labels are unaffected.
        """
        result = []
        if self.dac is not None:
            result.append((self.dac.name, self.dac, "dac"))
        for idx, component in enumerate(self.components):
            result.append((self._get_label_for_index(idx), component,
                           getattr(component, "component_type", "generic")))
        if self.adc is not None:
            result.append((self.adc.name, self.adc, "adc"))
        return result

    def _stage_offset(self):
        """Stage index of ``components[0]``: 1 if a DAC is present, else 0."""
        return 1 if self.dac is not None else 0

    def _cumulative_gain(self, plane, carrier_frequency, stages=None):
        """
        Total gain from the chain input up to ``plane``.

        Plane 0 is the chain input, so its cumulative gain is zero.
        """
        stages = stages if stages is not None else self.stages()
        total = 0.0
        for _, component, _ in stages[:plane]:
            total = total + component.gain(carrier_frequency)
        return total

    def _source_plane(self, stage_index, component):
        """
        The plane at which a stage's own noise is defined.

        Input-referred noise sits at the stage's input plane, output-referred
        noise at its output plane. See ``Component.noise_reference``.
        """
        if getattr(component, "noise_reference", "input") == "output":
            return stage_index + 1
        return stage_index

    def resolve_plane(self, reference_point, at):
        """
        Resolve a reference point to a plane index and a readable description.

        Parameters
        ----------
        reference_point : int or str
            A component index, a component label, or the name of the DAC/ADC.
            Component labels take precedence over converter names.
        at : {'input', 'output'}
            Which side of the named component the plane sits on. Required -
            input and output differ by that component's gain, which for an
            amplifier is tens of dB, so it must not be implicit.
        """
        if at not in ("input", "output"):
            raise ValueError(
                f"at must be 'input' or 'output', got {at!r}")

        stages = self.stages()
        stage_index = None

        # Components first, so a user label always wins over a converter name.
        try:
            stage_index = self.get_index(reference_point) + self._stage_offset()
        except (IndexError, KeyError, TypeError):
            if isinstance(reference_point, str):
                for idx, (label, _, kind) in enumerate(stages):
                    if kind in ("dac", "adc") and label == reference_point:
                        stage_index = idx
                        break
        if stage_index is None:
            raise KeyError(
                f"cannot resolve reference point {reference_point!r}. "
                f"Known labels: {sorted(self.labels)}"
            )

        label = stages[stage_index][0]
        plane = stage_index if at == "input" else stage_index + 1
        return plane, f"{label} ({at})"

    def noise_budget(self, reference_point, carrier_frequency,
                     spectral_frequency, *, at):
        """
        Every noise source in the system referred to one reference plane.

        Sources upstream of the plane are referred forward and sources
        downstream referred backward, both via

            contribution_dBm = intrinsic_dBm + C(plane) - C(source_plane)

        so a downstream source is divided by the gain between the plane and
        itself. That is why the referred total is not a measurable power at the
        plane: an ADC behind an attenuator can dominate the budget at the input
        of an LNA.

        Parameters
        ----------
        reference_point : int or str
            Component index, component label, or DAC/ADC name.
        carrier_frequency : float or np.ndarray
            Carrier frequency in Hz, used for all gain evaluation.
        spectral_frequency : float or np.ndarray
            Offset frequency in Hz, used for each source's noise spectrum.
        at : {'input', 'output'}
            Which plane of the named component to refer to.

        Returns
        -------
        NoiseBudget
            Contributions ordered largest first, each with its intrinsic noise,
            the referral gain applied, and the result in W/Hz and K.
        """
        plane, description = self.resolve_plane(reference_point, at)
        return self._build_budget(plane, description, carrier_frequency,
                                  spectral_frequency)

    def output_budget(self, carrier_frequency, spectral_frequency):
        """Noise budget referred to the chain output, after the ADC."""
        stages = self.stages()
        return self._build_budget(len(stages), "chain output",
                                  carrier_frequency, spectral_frequency,
                                  stages=stages)

    def _build_budget(self, plane, description, carrier_frequency,
                      spectral_frequency, stages=None):
        """Refer every stage's noise to ``plane``."""
        stages = stages if stages is not None else self.stages()
        reference_gain = self._cumulative_gain(plane, carrier_frequency, stages)

        contributions = []
        for stage_index, (label, component, kind) in enumerate(stages):
            intrinsic = _evaluate_noise(component, spectral_frequency)
            if not _has_any_noise(intrinsic):
                continue

            source_plane = self._source_plane(stage_index, component)
            source_gain = self._cumulative_gain(
                source_plane, carrier_frequency, stages)
            referral_gain = reference_gain - source_gain

            contributions.append(NoiseContribution(
                label=label,
                kind=kind,
                noise_reference=getattr(component, "noise_reference", "input"),
                intrinsic_w=intrinsic,
                referral_gain_db=referral_gain,
                power_w=to_W(to_dbm(intrinsic) + referral_gain),
            ))

        contributions.sort(key=lambda c: _magnitude(c.power_w), reverse=True)
        return NoiseBudget(
            reference=description,
            carrier_hz=carrier_frequency,
            spectral_hz=spectral_frequency,
            contributions=contributions,
        )

    def noise_at_point(self, reference_point, carrier_frequency,
                       spectral_frequency, contributions=False, *, at):
        """
        Total noise referred to a plane, in W/Hz.

        A thin accessor over :meth:`noise_budget`; use that directly for the
        per-source breakdown with temperatures and referral gains.

        Parameters
        ----------
        reference_point : int or str
            Component index, component label, or DAC/ADC name.
        carrier_frequency, spectral_frequency : float or np.ndarray
        contributions : bool, optional
            If True, also return a ``{label: W/Hz}`` dict.
        at : {'input', 'output'}
            Required; see :meth:`resolve_plane`.
        """
        budget = self.noise_budget(reference_point, carrier_frequency,
                                   spectral_frequency, at=at)
        if contributions:
            return budget.total_w, budget.as_dict()
        return budget.total_w


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
            Spectral frequency in Hz - the offset from the carrier at which
            the noise is evaluated
        contributions : bool, optional
            If True, return a dict with individual component contributions
            
        Returns
        -------
        float or np.ndarray
            Total output noise power spectral density in W/Hz
        dict (if contributions=True)
            Dictionary mapping component labels to their noise contributions
        """
        budget = self.output_budget(carrier_frequency, spectral_frequency)
        if contributions:
            return budget.total_w, budget.as_dict()
        return budget.total_w


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
