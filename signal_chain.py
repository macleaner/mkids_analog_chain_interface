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
        Calculate total gain through entire chain.
        
        Parameters
        ----------
        frequency : float or np.ndarray
            Frequency in Hz
            
        Returns
        -------
        float or np.ndarray
            Total gain in dB
        """
        if len(self.components) == 0:
            return 0.0
        return self.gain_between(0, len(self.components) - 1, frequency)
    
    def output_noise(self, carrier_frequency, spectral_frequency):
        """
        Calculate total noise at the output of the chain.
        
        Parameters
        ----------
        carrier_frequency : float or np.ndarray
            Carrier frequency in Hz (used for gain calculations)
        spectral_frequency : float or np.ndarray
            Spectral/offset frequency in Hz (used for noise spectral shape)
            
        Returns
        -------
        float or np.ndarray
            Total output noise power spectral density in W/Hz
        """
        if len(self.components) == 0:
            return 0.0
        return self.noise_at_point(len(self.components) - 1, carrier_frequency, spectral_frequency)
    
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
