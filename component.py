"""
Base component class for RF signal chain elements.

All hardware components (amplifiers, cables, attenuators, etc.) should inherit
from this base class and implement the required methods.
"""

from abc import ABC, abstractmethod


class Component(ABC):
    """
    Abstract base class for signal chain components.
    
    Each component must implement methods for gain and noise characteristics
    as functions of frequency.
    """
    
    def __init__(self, name=None, component_type=None):
        """
        Initialize a component.
        
        Parameters
        ----------
        name : str, optional
            Human-readable name/label for this component
        component_type : str, optional
            Type of component (e.g., 'amplifier', 'cable', 'attenuator')
        """
        self.name = name if name is not None else self.__class__.__name__
        self.component_type = component_type if component_type is not None else 'generic'
    
    @abstractmethod
    def gain(self, frequency):
        """
        Return the gain/loss of this component in dB.
        
        Parameters
        ----------
        frequency : float or np.ndarray
            Frequency in Hz
            
        Returns
        -------
        float or np.ndarray
            Gain in dB (negative values indicate loss)
        """
        pass
    
    def noise(self, frequency):
        """
        Return the noise power spectral density of this component.
        
        Parameters
        ----------
        frequency : float or np.ndarray
            Frequency in Hz
            
        Returns
        -------
        float or np.ndarray
            Noise power spectral density in W/Hz
            
        Notes
        -----
        Not all components contribute noise. Default implementation returns 0.
        Override this method for components that do contribute noise
        (attenuators, amplifiers, etc.).
        """
        return 0.0
    
    def __repr__(self):
        return f"{self.__class__.__name__}(name='{self.name}')"
    
    def __str__(self):
        return self.name


class PassiveComponent(Component):
    """Base class for passive components (cables, attenuators, filters)."""
    
    def __init__(self, name=None):
        super().__init__(name=name, component_type='passive')


class ActiveComponent(Component):
    """Base class for active components (amplifiers, converters)."""
    
    def __init__(self, name=None):
        super().__init__(name=name, component_type='active')
