"""
Signal chain class for managing ordered components and calculating
gain and noise propagation through the chain.
"""

import numpy as np
from typing import List, Union, Tuple
from utils import to_dbm, to_W, db_to_linear


class SignalChain:
    """
    Manages an ordered sequence of RF components and calculates
    signal gain and noise propagation through the chain.
    """
    
    def __init__(self, name="Signal Chain"):
        """
        Initialize an empty signal chain.
        
        Parameters
        ----------
        name : str
            Name/description of this signal chain
        """
        self.name = name
        self.components = []
        self.labels = {}  # Map label -> index
        self.dac = None  # DAC at start of chain
        self.adc = None  # ADC at end of chain
        
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
        
        # Iterate through all components up to and including reference point
        for idx in range(ref_idx + 1):
            component = self.components[idx]
            
            # Check if component has noise method
            if hasattr(component, 'noise'):
                # Get intrinsic noise power from component at the spectral frequency
                # Try to determine if noise() accepts multiple parameters
                try:
                    # Most components have simple noise that only depends on frequency (or is constant)
                    # Pass spectral_frequency for components with frequency-dependent noise
                    noise_power = component.noise(spectral_frequency)
                except TypeError:
                    # If that fails, component noise might not need frequency parameter
                    try:
                        noise_power = component.noise()
                    except:
                        # Skip this component if noise() call fails
                        continue
                
                if noise_power > 0:
                    # Calculate gain from component to reference point at carrier frequency
                    gain_db = self.gain_between(idx, ref_idx, carrier_frequency)
                    
                    # Propagate noise to reference point
                    # N_out = N_in * G (linear) or N_out_dBm = N_in_dBm + G_dB
                    noise_at_ref_dbm = to_dbm(noise_power) + gain_db
                    noise_at_ref_W = to_W(noise_at_ref_dbm)
                    
                    total_noise_W += noise_at_ref_W
                    
                    # Store individual contribution if requested
                    if contributions:
                        label = self._get_label_for_index(idx)
                        noise_dict[label] = noise_at_ref_W
        
        if contributions:
            return total_noise_W, noise_dict
        else:
            return total_noise_W
    
    def _get_label_for_index(self, idx):
        """Find the label for a given index."""
        for label, label_idx in self.labels.items():
            if label_idx == idx:
                return label
        return f"Component_{idx}"
    
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
        
        # Calculate gain from each component to output
        # Gain from DAC to output: gain of all components + ADC
        # Gain from regular components: gain from that component to end + ADC
        # ADC noise: no further gain (already at output)
        
        # DAC noise contribution
        if self.dac is not None and hasattr(self.dac, 'noise'):
            try:
                dac_noise = self.dac.noise(spectral_frequency)
                if dac_noise > 0:
                    # Gain from DAC output through all components to ADC output
                    gain_to_output = 0.0
                    if len(self.components) > 0:
                        gain_to_output += self.gain_between(0, len(self.components) - 1, carrier_frequency)
                    if self.adc is not None:
                        gain_to_output += self.adc.gain(carrier_frequency)
                    
                    dac_noise_at_output_dbm = to_dbm(dac_noise) + gain_to_output
                    dac_noise_at_output_W = to_W(dac_noise_at_output_dbm)
                    total_noise_W += dac_noise_at_output_W
                    
                    if contributions:
                        noise_dict['AD9082_DAC'] = dac_noise_at_output_W
            except:
                pass
        
        # Regular component noise contributions
        if len(self.components) > 0:
            for idx in range(len(self.components)):
                component = self.components[idx]
                
                if hasattr(component, 'noise'):
                    try:
                        noise_power = component.noise(spectral_frequency)
                    except TypeError:
                        try:
                            noise_power = component.noise()
                        except:
                            continue
                    
                    if noise_power > 0:
                        # Gain from this component to output (through remaining components + ADC)
                        gain_to_output = 0.0
                        if idx < len(self.components) - 1:
                            gain_to_output += self.gain_between(idx, len(self.components) - 1, carrier_frequency)
                        if self.adc is not None:
                            gain_to_output += self.adc.gain(carrier_frequency)
                        
                        noise_at_output_dbm = to_dbm(noise_power) + gain_to_output
                        noise_at_output_W = to_W(noise_at_output_dbm)
                        total_noise_W += noise_at_output_W
                        
                        if contributions:
                            label = self._get_label_for_index(idx)
                            noise_dict[label] = noise_at_output_W
        
        # ADC noise contribution (already at output, no further gain)
        if self.adc is not None and hasattr(self.adc, 'noise'):
            try:
                adc_noise = self.adc.noise(spectral_frequency)
                if adc_noise > 0:
                    total_noise_W += adc_noise
                    
                    if contributions:
                        noise_dict['AD9082_ADC'] = adc_noise
            except:
                pass
        
        if contributions:
            return total_noise_W, noise_dict
        else:
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
