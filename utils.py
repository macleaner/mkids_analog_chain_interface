"""
Utility functions for RF signal chain analysis.

Provides conversion functions between linear power and logarithmic (dBm) scales,
plus other helper functions.
"""

import numpy as np

# Physical constants
kb = 1.38e-23  # Boltzmann constant: m^2 kg s^-2 K-1


def to_dbm(power_watts):
    """
    Convert power in Watts to dBm.
    
    Parameters
    ----------
    power_watts : float or np.ndarray
        Power in Watts
        
    Returns
    -------
    float or np.ndarray
        Power in dBm
    """
    return 10 * np.log10(power_watts * 1000)


def to_W(power_dbm):
    """
    Convert power in dBm to Watts.
    
    Parameters
    ----------
    power_dbm : float or np.ndarray
        Power in dBm
        
    Returns
    -------
    float or np.ndarray
        Power in Watts
    """
    return 10**(power_dbm / 10) * 1e-3


def db_to_linear(gain_db):
    """
    Convert gain/loss in dB to linear ratio.
    
    Parameters
    ----------
    gain_db : float or np.ndarray
        Gain in dB (negative for loss)
        
    Returns
    -------
    float or np.ndarray
        Linear gain ratio
    """
    return 10**(gain_db / 10)


def linear_to_db(gain_linear):
    """
    Convert linear gain ratio to dB.
    
    Parameters
    ----------
    gain_linear : float or np.ndarray
        Linear gain ratio
        
    Returns
    -------
    float or np.ndarray
        Gain in dB
    """
    return 10 * np.log10(gain_linear)


def thermal_noise_power(temperature, bandwidth=1.0):
    """
    Calculate thermal noise power.
    
    Parameters
    ----------
    temperature : float
        Physical temperature in Kelvin
    bandwidth : float, optional
        Bandwidth in Hz (default: 1 Hz for power spectral density)
        
    Returns
    -------
    float
        Thermal noise power in Watts (or W/Hz if bandwidth=1)
    """
    return kb * temperature * bandwidth
