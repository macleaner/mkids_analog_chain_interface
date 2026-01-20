"""
Simple classes representing elements in the analog chain.
Each class contains functions for the gain and noise contribution of
the component.
"""

import numpy as np
import os
import scipy.interpolate as interpolate
from scipy.optimize import curve_fit

from component import ActiveComponent, PassiveComponent
from utils import kb


def exponential(f, A, n, b):
    return A*f**-n +b

class AD9082:
    # note: currently, the dac phase noise slope is simply taken as -10dbm/hz per decade
    # this is not quite what is in the datasheet, but it is much easier to fit with an exponential
    # The largest differences vs the datasheet occur >100 Hz, where the DAC noise should be 
    # subdominant to LNA noise and so this *should* not matter much.
    def __init__(self, ):
        self.adc_noise_density_dbm = -140
        
        f_datasheet = np.asarray([0.0001, 0.001, 0.01, 0.1, 1, 10, 100, 1000, 10000])
        #self.pnoise_dbc_datasheet_900 = np.asarray([-45, -55, -65, -75, -85, -95, -110, -130, -140])
        #self.pnoise_dbc_datasheet_1800 = np.asarray([-40, -50, -60, -70, -80, -90, -105, -125, -135])
        #self.pnoise_dbc_datasheet_3600 = np.asarray([-35, -45, -55, -65, -75, -85, -100, -120, -130])
        pnoise_dbc_simple = np.asarray([-45, -55, -65, -75, -85, -95, -105, -115, -125]) # makes fitting an exponential easier
        #pnoise_dbc_simple -= 5
        pnoise_W = 10**(pnoise_dbc_simple / 10) * 1e-3

        f_datasheet_adc_noise = np.asarray([0.001, 1, 1.5, 2, 2.5, 3])*1e9
        adc_SNR_datasheet = np.asarray([56, 55.5, 55, 54.5, 52, 51.5]) # dB_FS
        adc_nyquist_bw = 3e9
        adc_fs = 1 # dbm
        adc_noise_datasheet_WperHz = 10**((adc_fs - adc_SNR_datasheet)/10) * 1e-3 / adc_nyquist_bw
        self.adc_noise_func = interpolate.interp1d(f_datasheet_adc_noise, adc_noise_datasheet_WperHz, fill_value='extrapolate', bounds_error=False)

        self.popt, self.pcov = curve_fit(exponential, f_datasheet, pnoise_W)
        
    def dac_noise(self, f, carrier_power_dbm):
        noise_dbc =  10*np.log10(1e3 * exponential(f, self.popt[0], self.popt[1], self.popt[2]))
        noise_dbm = noise_dbc + carrier_power_dbm
        noise_W = 10**( noise_dbm / 10 ) * 1e-3
        return noise_W
    
    def adc_noise(self, f=None):
        if f is None:
            return 10**(self.adc_noise_density_dbm/10.)*1e-3
        else:
            return self.adc_noise_func(f)
        
        

class CryoElec_LNA:
    def __init__(self):
        self.f_datasheet = 1e6*np.asarray([0, 500, 1000, 1500, 2000, 2250, 2500, 2750, 3000])
        self.noise_temp_datasheet = np.asarray([5, 4, 4, 4, 5, 7, 14, 28, 56]) # highest two frequencies are estimates
        self.noise_power_datasheet = kb * self.noise_temp_datasheet
        self.noise = interpolate.CubicSpline(self.f_datasheet, self.noise_power_datasheet, bounds_error=False)
        
        self.gain_datasheet = np.asarray([32, 33, 32, 31, 30, 27, 25, 23, 22])
        self.gain_f = interpolate.interp1d(self.f_datasheet, self.gain_datasheet, bounds_error=False)
#         self.gain_f = interpolate.CubicSpline(self.f_datasheet, self.gain_datasheet)
        
    def gain(self, f):
        return self.gain_f(f)

    
        
        
class ZX60_3018Gplus:
    def __init__(self):
        
        self.f_datasheet = 1e6*np.asarray([0, 20, 50, 100, 351, 500, 663, 866, 1000, 1168, 1378, 1500, 1671, 1863, 2000, 2174, 2376, 2500, 2668, 2879, 3000])
        self.noise_figure_datasheet = np.asarray([2.92, 2.92, 2.66, 2.61, 2.69, 2.72, 2.66, 2.69, 2.64, 2.60, 2.59, 2.59, 2.60, 2.62, 2.63, 2.62, 2.61, 2.58, 2.60, 2.61, 2.64])
        self.noise_power_datasheet = kb * 290 * (10**(self.noise_figure_datasheet / 10) - 1)
        self.noise_f = interpolate.UnivariateSpline(self.f_datasheet, self.noise_power_datasheet, ext=0)  # ext=0 allows extrapolation
        
        self.gain_datasheet = np.asarray([22, 22.58, 22.75, 22.76, 22.61, 22.42, 22.28, 21.83, 21.83, 21.52, 21.16, 20.97, 20.60, 20.39, 20.22, 20.04, 19.76, 19.56, 19.26, 18.97, 18.78])
        self.gain_f = interpolate.UnivariateSpline(self.f_datasheet, self.gain_datasheet, ext=0)  # ext=0 allows extrapolation
        
        meas_gainf = np.asarray([0, 58, 470, 961.8, 1302, 1806, 2356, 2939, 3000])*1e6
        meas_gain = [23, 23.,   22.45, 21.6,  20.7, 20.1,  19.,   17.85, 17.8]
        self.meas_gain_func = interpolate.interp1d(meas_gainf, meas_gain, bounds_error=False)

    def gain(self, f):
#         return self.gain_f(f)
        return self.meas_gain_func(f)                                           
    
    def noise(self, f):
        return self.noise_f(f)

        
        
class Attenuator:
    
    def __init__(self, attenuation, temperature):
        atten_drift = [0, -1]
        atten_drift_f = [1e6, 3e9]
        self.atten_func = interpolate.interp1d(atten_drift_f, atten_drift, bounds_error=False)
        self.attenuation = attenuation
        self.temperature = temperature
        
    def noise(self, frequency=None):
        """Thermal noise is frequency-independent, but accept frequency for API compatibility"""
        return kb*self.temperature
    
    def gain(self, carrier_freq=None):
        if isinstance(carrier_freq, (float, int)):
            return self.attenuation
        elif carrier_freq is None:
            return self.attenuation
        else:
            return self.attenuation * np.ones(len(carrier_freq))
    
    def gain_meas(self, carrier_freq):
        return self.atten_func(carrier_freq) + self.attenuation
    
                             

        
class SMA_cables:
    '''
    typical room temperature SMA coax from L-com.com. Eg LCCA30166
    '''
    
    def __init__(self, length_m):
        self.length = length_m
        
        # gain at 1Mhz is an extrapolation - we are unlikely to need accuracy this low & it makes fitting easier
        #fdatasheet = np.asarray([0.001, 0.25, 0.5, 1, 2.5, 5.8])*1e9
        #db_per_m = self.length * np.asarray([-0.1, -0.5, -0.63, -0.82, -1.21, -1.78]) * 3.2/6. # datasheet for 6ft cable; convert to per m loss
        
        ## checking again with the VNA:
        fdatasheet = np.asarray([0.001, 0.25, 0.5, 1, 2.5, 3.0])*1e9
        db_per_m = self.length * np.asarray([-0.2, -0.6, -0.8, -1.2, -1.8, -2.2]) * 3.2/10. # measured for 10ft cable; convert to per m loss
        
        self.gain_per_m = interpolate.interp1d(fdatasheet, db_per_m, bounds_error=False)

        
    def gain(self, f):
        return self.gain_per_m(f) * self.length
        
        
class SMA_CuNi_cryo:
    '''
    1.16mm outer diameter coax cryo cables as used in McGill DR (see cryocoax.com)
    '''
    
    def __init__(self, length_m, temperature=4):
        self.length = length_m
        if not int(temperature) in [300, 4]:
            raise ValueError('Not recognized cable temperature value. Please choose either 300 or 4 (values are in Kelvin).')
        self.temperature = temperature
        
        # gain at 1Mhz is an extrapolation - we are unlikely to need accuracy this low & it makes fitting easier
        fdatasheet = np.asarray([0.001, 0.5, 1, 5]) * 1e9
        warmgain = np.asarray([-1, -2.1, -3, -6.7]) * self.length
        coldgain = np.asarray([-0.5, -1, -1.5, -3.2]) * self.length

        self.warm_gain = interpolate.interp1d(fdatasheet, warmgain, bounds_error=False)
        self.cold_gain = interpolate.interp1d(fdatasheet, coldgain, bounds_error=False)
        
    def gain(self, f):
        if self.temperature == 300:
            return self.warm_gain(f)
        elif self.temperature == 4:
            return self.cold_gain(f)


#################################################
# HARDWARE AS USED IN SLIM DEPLOYMENT 2024/2025 #
#################################################

class SMA_CuNi086_cryo:
    '''
    0.86mm outer diameter coax
    '''
    
    def __init__(self, length_m, temperature=4):
        self.length = length_m
#         if not int(temperature) in [300, 4]:
#             raise ValueError('Not recognized cable temperature value. Please choose either 300 or 4 (values are in Kelvin).')
        self.temperature = temperature
        
        # gain at 1Mhz is an extrapolation - we are unlikely to need accuracy this low & it makes fitting easier
        fdatasheet = np.asarray([0.0, 0.5, 1.0, 5.0, 10.0]) * 1e9
        warmgain = np.asarray([0.0, -5.4, -7.7, -17.1, -24.3]) * self.length
        coldgain = np.asarray([0.0, -4.1, -5.7, -12.8, -18.1]) * self.length

        self.warm_gain = interpolate.interp1d(fdatasheet, warmgain, bounds_error=False)
        self.cold_gain = interpolate.interp1d(fdatasheet, coldgain, bounds_error=False)
        
    def gain(self, f):
        if self.temperature > 100:
            return self.warm_gain(f)
        elif self.temperature < 100:
            return self.cold_gain(f)

class SMA_SS086_cryo:
    '''
    0.86mm outer diameter stainless steel coax
    '''

    def __init__(self, length_m, temperature=4):
        self.length = length_m

        self.temperature = temperature

        fdatasheet = np.asarray([0.0, 0.5, 1.0, 5.0, 10.0]) * 1e9
        warmgain = np.asarray([0.0, -7.3, -10.3, -23.0, -32.7]) * self.length
        coldgain = np.asarray([0.0, -4.7, -6.6, -14.8, -20.9]) * self.length

        self.warm_gain = interpolate.interp1d(fdatasheet, warmgain, bounds_error=False)
        self.cold_gain = interpolate.interp1d(fdatasheet, coldgain, bounds_error=False)

    def gain(self, f):
        if self.temperature > 100:
            return self.warm_gain(f)
        elif self.temperature < 100:
            return self.cold_gain(f)
        
class SMA_SS219_cryo:
    '''
    2.19mm outer diameter stainless steel coax
    '''

    def __init__(self, length_m, temperature=4):
        self.length = length_m

        self.temperature = temperature

        fdatasheet = np.asarray([0.0, 0.5, 1.0, 5.0, 10.0]) * 1e9
        warmgain = np.asarray([0.0, -3.0, -4.2, -9.4, -13.5]) * self.length
        coldgain = np.asarray([0.0, -1.9, -2.6, -5.9, -8.3]) * self.length

        self.warm_gain = interpolate.interp1d(fdatasheet, warmgain, bounds_error=False)
        self.cold_gain = interpolate.interp1d(fdatasheet, coldgain, bounds_error=False)

    def gain(self, f):
        if self.temperature > 100:
            return self.warm_gain(f)
        elif self.temperature < 100:
            return self.cold_gain(f)


class SMA_NbTi086_cryo:
    '''
    0.86mm outer diameter NbTi coax
    '''

    def __init__(self, length_m, temperature=4):
        self.length = length_m

        self.temperature = temperature

        fdatasheet = np.asarray([0.0, 0.5, 1.0, 5.0, 10.0]) * 1e9
        warmgain = np.asarray([0.0, -6.8, -9.6, -21.6, -30.5]) * self.length
        coldgain = np.asarray([0.0, -0.5, -0.5, -0.5, -0.5]) * self.length

        self.warm_gain = interpolate.interp1d(fdatasheet, warmgain, bounds_error=False)
        self.cold_gain = interpolate.interp1d(fdatasheet, coldgain, bounds_error=False)

    def gain(self, f):
        if self.temperature > 9:
            return self.warm_gain(f)
        elif self.temperature < 9:
            return self.cold_gain(f)


class SMA_FM_F141_cables:
    '''
    room temperature SMA coax from Fairview Microwave (eg FMCA2155)
    https://www.fairviewmicrowave.com/content/dam/infinite-electronics/product-assets/fairview-microwave/product-datasheets/FMCA2155.pdf
    '''
    
    def __init__(self, length_m):
        self.length = length_m
        
        
        fdatasheet = np.asarray([0.0, 1, 2.0, 5, 10, 18])*1e9
        db_per_m = self.length * np.asarray([0.0, -0.37, -0.54, -0.89, -1.35, -1.9])
        
        self.gain_per_m = interpolate.interp1d(fdatasheet, db_per_m, bounds_error=False)
        
    def gain(self, f):
        return self.gain_per_m(f) * self.length

                             

class ASU_3GHz_LNA:
    def __init__(self):
        self.f_datasheet = 1e9*np.asarray([0, 0.2, 0.4, 0.6, 3])
        self.noise_temp_datasheet = np.asarray([30, 15, 7, 6, 6])
        self.noise_power_datasheet = kb * self.noise_temp_datasheet
        self.noise = interpolate.interp1d(self.f_datasheet, self.noise_power_datasheet, bounds_error=False)
        
        self.f_datasheet = 1e9*np.asarray([0, 0.1, 0.5, 1, 1.5, 2, 2.5, 3])
#         self.gain_datasheet = np.asarray([-25, 0, 27, 32, 32, 32, 33, 33])
        self.gain_datasheet = np.asarray([-25, 0, 27, 32, 30, 30, 32, 33])
#         self.gain_datasheet = np.asarray([0, 5.0, 28.0, 30.0, 31.0, 30.0, 32.0, 30.0, 26.0, 10.0])
        self.gain_f = interpolate.interp1d(self.f_datasheet, self.gain_datasheet, bounds_error=False)
        
    def gain(self, f):
        return self.gain_f(f)
    
    def noise(self, f):
        return self.noise(f)


class FilterHP_VHF1320p:
    '''
    Minicircuits high-pass filter VHF-1320+
    '''

    def __init__(self):

        f_datasheet = np.asarray([1, 100, 880, 1060, 1180, 1260, 1320, 1400, 1700, 3700]) * 1e6
        gain_datasheet = np.asarray([-94, -69, -51, -27, -14, -6.3, -2.9, -1.6, -0.8, -0.5]) # dB

        self.gain_f = interpolate.interp1d(f_datasheet, gain_datasheet, bounds_error=False)

    def gain(self, carrier_freq):
        return self.gain_f(carrier_freq)


class FilterHP_VHF1760p:
    '''
    Minicircuits high-pass filter VHF-1760+
    '''

    def __init__(self):

        f_datasheet = np.asarray([1, 100, 950, 1230, 1400, 1550, 1700, 1760, 1900, 2100, 2200, 4500]) * 1e6
        gain_datasheet = np.asarray([-94, -65, -47, -24, -13, -6, -2.6, -1.9, -1.2, -0.8, -0.7, -0.5]) # dB

        self.gain_f = interpolate.interp1d(f_datasheet, gain_datasheet, bounds_error=False)

    def gain(self, carrier_freq):
        return self.gain_f(carrier_freq)


class FilterHP_VHF1910p:
    '''
    Minicircuits high-pass filter VHF-1910+
    '''

    def __init__(self):

        f_datasheet = np.asarray([1, 100, 1075, 1400, 1630, 1750, 1850, 1910, 2000, 2100, 2200, 4400]) * 1e6
        gain_datasheet = np.asarray([-91, -76, -42, -26, -13, -7, -3.4, -2.2, -1.4, -1.1, -1, -0.8]) # dB

        self.gain_f = interpolate.interp1d(f_datasheet, gain_datasheet, bounds_error=False)

    def gain(self, carrier_freq):
        return self.gain_f(carrier_freq)


####################################
# new in 2025/2026 SLIM DEPLOYMENT #
####################################

class BCB029_SS034_cryo:
    '''
    0.034" diameter stainless steel coax (CryoCoax BCB029)
    Attenuation per metre at 300 K and 4 K from datasheet (page 2)
    https://cryocoax.com/wp-content/uploads/2020/07/034-SS_SS-BCB029-CRYO.pdf.
    '''
    def __init__(self, length_m, temperature=4):
        self.length = length_m
        self.temperature = temperature

        # Frequencies in Hz
        fdatasheet = np.asarray([0.0, 0.5, 1.0, 5.0, 10.0, 20.0]) * 1e9

        # Attenuation (dB/m) × length → total dB loss
        warmgain = np.asarray([0.0, -7.3, -10.3, -23.0, -32.7, -46.4]) * self.length
        coldgain = np.asarray([0.0, -4.7,  -6.6,  -14.8, -20.9, -29.5]) * self.length

        self.warm_gain = interpolate.interp1d(fdatasheet, warmgain, fill_value='extrapolate', bounds_error=False)
        self.cold_gain = interpolate.interp1d(fdatasheet, coldgain, fill_value='extrapolate', bounds_error=False)

    def gain(self, f):
        """
        Return insertion loss (dB) at frequency f (Hz):
        • at temperatures >100 K, uses 300 K data
        • at temperatures <100 K, uses 4 K data
        """
        if self.temperature > 100:
            return self.warm_gain(f)
        else:
            return self.cold_gain(f)


class BCB014_SS085_cryo:
    '''
    0.085" diameter stainless steel coax (CryoCoax BCB014)
    Attenuation per metre at 300 K and 4 K from datasheet (page 2)
    https://cryocoax.com/wp-content/uploads/2020/07/085-SS_SS-BCB014-CRYO.pdf
    '''
    def __init__(self, length_m, temperature=4):
        self.length = length_m
        self.temperature = temperature

        # Frequencies (GHz → Hz)
        fdatasheet = np.asarray([0.0, 0.5, 1.0, 5.0, 10.0, 20.0]) * 1e9

        # Attenuation (dB/m) × length → total dB loss
        warmgain = np.asarray([0.0, -3.0,  -4.2,  -9.4,  -13.5, -19.2]) * self.length
        coldgain = np.asarray([0.0, -1.9,  -2.6,  -5.9,  -8.3,  -11.7]) * self.length

        self.warm_gain = interpolate.interp1d(fdatasheet, warmgain, fill_value='extrapolate', bounds_error=False)
        self.cold_gain = interpolate.interp1d(fdatasheet, coldgain, fill_value='extrapolate', bounds_error=False)

    def gain(self, f):
        """
        Return insertion loss (dB) at frequency f (Hz):
        • at temperatures >100 K, uses 300 K data
        • at temperatures <100 K, uses 4 K data
        """
        if self.temperature > 100:
            return self.warm_gain(f)
        else:
            return self.cold_gain(f)


class BCB024_SP034_cryo:
    '''
    0.034" diameter SP CuNi–CuNi coax (CryoCoax BCB024)
    Attenuation per metre at 300 K and 4 K from datasheet (page 2)
    https://cryocoax.com/wp-content/uploads/2020/07/034-SP-CuNiCuNi-BCB024-CRYO.pdf
    '''
    def __init__(self, length_m, temperature=4):
        self.length = length_m
        self.temperature = temperature

        fdatasheet = np.asarray([0.0, 0.5, 1.0, 5.0, 10.0, 20.0]) * 1e9

        warmgain = np.asarray([0.0, -2.1,  -3.0,  -6.7,  -9.5,  -13.4]) * self.length
        coldgain = np.asarray([0.0, -1.0,  -1.5,  -3.2,  -4.6,  -6.5 ]) * self.length

        self.warm_gain = interpolate.interp1d(fdatasheet, warmgain, fill_value='extrapolate', bounds_error=False)
        self.cold_gain = interpolate.interp1d(fdatasheet, coldgain, fill_value='extrapolate', bounds_error=False)

    def gain(self, f):
        if self.temperature > 100:
            return self.warm_gain(f)
        else:
            return self.cold_gain(f)


class BCB012_NbTi034_cryo:
    '''
    0.034" diameter NbTi–NbTi coax (CryoCoax BCB012)
    Attenuation per metre at 300 K and <0.5 dB/m at 4 K (page 2)
    https://cryocoax.com/wp-content/uploads/2020/07/034-NbTiNbTi-BCB012-CRYO.pdf
    '''
    def __init__(self, length_m, temperature=4):
        self.length = length_m
        self.temperature = temperature

        fdatasheet = np.asarray([0.0, 0.5, 1.0, 5.0, 10.0, 20.0]) * 1e9

        # 4 K attenuation is listed as "<0.5 dB/m" → treat as 0.5 dB/m for interpolation
        warmgain = np.asarray([0.0, -6.8,  -9.6,  -21.6, -30.5, -43.1]) * self.length
        coldgain = np.asarray([0.0, -0.5,  -0.5,  -0.5,  -0.5,  -0.5 ]) * self.length

        self.warm_gain = interpolate.interp1d(fdatasheet, warmgain, fill_value='extrapolate', bounds_error=False)
        self.cold_gain = interpolate.interp1d(fdatasheet, coldgain, fill_value='extrapolate', bounds_error=False)

    def gain(self, f):
        if self.temperature > 100:
            return self.warm_gain(f)
        else:
            return self.cold_gain(f)

class SMA_RG58C_cables:
    '''
    Flexible RG58 Coax Cable, single‐shielded, black PVC jacket.
    Attenuation per 100 m (dB/100 m) taken from datasheet 
    https://www.pasternack.com/images/ProductPDF/RG58C-U.pdf
    '''
    def __init__(self, length_m):
        self.length = length_m

        # Frequencies (GHz → Hz), with 0 for a zero‐loss anchor
        fd = np.asarray([0.0, 0.01, 0.1, 1.0, 5.0]) * 1e9

        # Attenuation from datasheet (dB per 100 m): [0, 4.59, 16.08, 65.62, 196.85]
        # → convert to dB/m
        db_per_100m = np.asarray([0.0, 4.59, 16.08, 65.62, 196.85])
        db_per_m = db_per_100m / 100.0

        # build per‐metre loss function and multiply by length in .gain()
        self.atten_per_m = interpolate.interp1d(fd, db_per_m, fill_value='extrapolate', bounds_error=False)

    def gain(self, f):
        """
        Total insertion loss (dB) at frequency f (Hz) over self.length metres.
        """
        return self.atten_per_m(f) * self.length


class SMA_RG174A_cables:
    '''
    Flexible RG174 Coax Cable, single‐shielded, black PVC jacket.
    Attenuation per 100 m (dB/100 m) taken from datasheet 
    https://www.pasternack.com/images/ProductPDF/RG174A-U-BULK.pdf
    '''
    def __init__(self, length_m):
        self.length = length_m

        # Frequencies (MHz → Hz), with 0 for a zero‐loss anchor
        fd = np.asarray([0.0, 0.1, 0.4, 1.0]) * 1e9

        # Attenuation from datasheet (dB per 100 m): [0, 27.56, 62.34, 104.99]
        # → convert to dB/m
        db_per_100m = np.asarray([0.0, 27.56, 62.34, 104.99])
        db_per_m = db_per_100m / 100.0

        self.atten_per_m = interpolate.interp1d(fd, db_per_m, fill_value='extrapolate', bounds_error=False)

    def gain(self, f):
        """
        Total insertion loss (dB) at frequency f (Hz) over self.length metres.
        """
        return self.atten_per_m(f) * self.length
