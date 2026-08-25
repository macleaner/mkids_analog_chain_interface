"""
Hardware component library.

Each class models one real RF component, with gain (dB) and where applicable
noise (W/Hz) interpolated from datasheet or measured values.

Every component is registered under a stable type id (see ``registry.py``) and
declares its constructor parameters, so it can be serialized into a chain file
and rebuilt from one without relying on class names or attribute reflection.

The datasheet arrays below are unchanged from the original implementation; the
refactor to registered classes is deliberately numerics-preserving. Known
physical bugs in a few models are documented in ``tests/test_characterization.py``
under KNOWN_BAD rather than being quietly fixed here.
"""

import numpy as np
import scipy.interpolate as interpolate
from scipy.optimize import curve_fit

from component import ActiveComponent, ADCComponent, DACComponent, PassiveComponent
from registry import ParamSpec, register
from utils import kb


def exponential(f, A, n, b):
    return A * f**-n + b


# Parameter specs reused across the cable models.
LENGTH_PARAM = ParamSpec("length_m", default=1.0, label="Length", unit="m",
                         minimum=0.0, maximum=100.0, step=0.1,
                         help="Physical cable length in metres.")
TEMPERATURE_PARAM = ParamSpec("temperature", default=4.0, label="Temperature",
                              unit="K", minimum=0.0, maximum=400.0, step=1.0,
                              help="Physical temperature of the component.")


class AD9082:
    """
    Legacy AD9082 helper, kept for backward compatibility with the scripts in
    analog_chains/. It is not a chain component - it has no gain()/noise() -
    so it is intentionally not registered. Use AD9082_DAC / AD9082_ADC.
    """

    # note: currently, the dac phase noise slope is simply taken as -10dbm/hz per decade
    # this is not quite what is in the datasheet, but it is much easier to fit with an exponential
    # The largest differences vs the datasheet occur >100 Hz, where the DAC noise should be
    # subdominant to LNA noise and so this *should* not matter much.
    def __init__(self):
        self.adc_noise_density_dbm = -140

        f_datasheet = np.asarray([0.0001, 0.001, 0.01, 0.1, 1, 10, 100, 1000, 10000])
        pnoise_dbc_simple = np.asarray([-45, -55, -65, -75, -85, -95, -105, -115, -125])
        pnoise_W = 10**(pnoise_dbc_simple / 10) * 1e-3

        f_datasheet_adc_noise = np.asarray([0.001, 1, 1.5, 2, 2.5, 3]) * 1e9
        adc_SNR_datasheet = np.asarray([56, 55.5, 55, 54.5, 52, 51.5])  # dB_FS
        adc_nyquist_bw = 3e9
        adc_fs = 1  # dbm
        adc_noise_datasheet_WperHz = 10**((adc_fs - adc_SNR_datasheet) / 10) * 1e-3 / adc_nyquist_bw
        self.adc_noise_func = interpolate.interp1d(
            f_datasheet_adc_noise, adc_noise_datasheet_WperHz,
            fill_value='extrapolate', bounds_error=False)

        self.popt, self.pcov = curve_fit(exponential, f_datasheet, pnoise_W)

    def dac_noise(self, f, carrier_power_dbm):
        noise_dbc = 10 * np.log10(1e3 * exponential(f, self.popt[0], self.popt[1], self.popt[2]))
        noise_dbm = noise_dbc + carrier_power_dbm
        noise_W = 10**(noise_dbm / 10) * 1e-3
        return noise_W

    def adc_noise(self, f=None):
        if f is None:
            return 10**(self.adc_noise_density_dbm / 10.) * 1e-3
        else:
            return self.adc_noise_func(f)


@register("converter.ad9082_dac", category="Converters", label="AD9082 DAC",
          params=(
              ParamSpec("carrier_power_dbm", default=0.0, label="Carrier Power",
                        unit="dBm", minimum=-80.0, maximum=30.0, step=1.0,
                        help="Carrier power at the DAC output. Phase noise "
                             "scales with this."),
              ParamSpec("gain_db", default=0.0, label="Gain", unit="dB",
                        minimum=-50.0, maximum=50.0, step=0.5),
          ))
class AD9082_DAC(DACComponent):
    """
    AD9082 Digital-to-Analog Converter.

    Produces frequency-dependent phase noise that scales with carrier power.
    """

    def __init__(self, carrier_power_dbm=0.0, gain_db=0.0, name=None):
        super().__init__(name=name, params={
            "carrier_power_dbm": carrier_power_dbm,
            "gain_db": gain_db,
        })
        self.carrier_power_dbm = carrier_power_dbm
        self.gain_db = gain_db

        # Phase noise model (identical to the legacy AD9082).
        f_datasheet = np.asarray([0.0001, 0.001, 0.01, 0.1, 1, 10, 100, 1000, 10000])
        pnoise_dbc_simple = np.asarray([-45, -55, -65, -75, -85, -95, -105, -115, -125])
        pnoise_W = 10**(pnoise_dbc_simple / 10) * 1e-3
        self.popt, self.pcov = curve_fit(exponential, f_datasheet, pnoise_W)

    def gain(self, carrier_frequency):
        """Return DAC gain in dB."""
        if isinstance(carrier_frequency, np.ndarray):
            return np.full_like(carrier_frequency, self.gain_db)
        return self.gain_db

    def noise(self, frequency):
        """
        Return DAC phase noise PSD in W/Hz at the given spectral frequency.
        """
        noise_dbc = 10 * np.log10(
            1e3 * exponential(frequency, self.popt[0], self.popt[1], self.popt[2]))
        noise_dbm = noise_dbc + self.carrier_power_dbm
        return 10**(noise_dbm / 10) * 1e-3


@register("converter.ad9082_adc", category="Converters", label="AD9082 ADC",
          params=(
              ParamSpec("gain_db", default=0.0, label="Gain", unit="dB",
                        minimum=-50.0, maximum=50.0, step=0.5),
          ))
class AD9082_ADC(ADCComponent):
    """
    AD9082 Analog-to-Digital Converter. Fixed white noise floor.
    """

    def __init__(self, gain_db=0.0, name=None):
        super().__init__(name=name, params={"gain_db": gain_db})
        self.gain_db = gain_db
        self.adc_noise_density_dbm = -140  # Fixed white noise floor

    def gain(self, carrier_frequency):
        """Return ADC gain in dB."""
        if isinstance(carrier_frequency, np.ndarray):
            return np.full_like(carrier_frequency, self.gain_db)
        return self.gain_db

    def noise(self, frequency=None):
        """Return ADC noise PSD in W/Hz. White, so frequency is ignored."""
        return 10**(self.adc_noise_density_dbm / 10.0) * 1e-3


@register("amplifier.cryoelec_lna", category="Amplifiers",
          label="CryoElec LNA (~4 K)")
class CryoElec_LNA(ActiveComponent):
    """Cryogenic LNA, roughly 4 K noise temperature."""

    def __init__(self, name=None):
        super().__init__(name=name, params={})

        self.f_datasheet = 1e6 * np.asarray(
            [0, 500, 1000, 1500, 2000, 2250, 2500, 2750, 3000])
        self.noise_temp_datasheet = np.asarray(
            [5, 4, 4, 4, 5, 7, 14, 28, 56])  # highest two frequencies are estimates
        self.noise_power_datasheet = kb * self.noise_temp_datasheet
        # CubicSpline takes no bounds_error argument; passing one used to make
        # this class impossible to construct at all.
        self.noise_f = interpolate.CubicSpline(
            self.f_datasheet, self.noise_power_datasheet)

        self.gain_datasheet = np.asarray([32, 33, 32, 31, 30, 27, 25, 23, 22])
        self.gain_f = interpolate.interp1d(
            self.f_datasheet, self.gain_datasheet, bounds_error=False)

    def gain(self, carrier_frequency):
        return self.gain_f(carrier_frequency)

    def noise(self, f):
        return self.noise_f(f)


@register("amplifier.zx60_3018g_plus", category="Amplifiers",
          label="Mini-Circuits ZX60-3018G+")
class ZX60_3018Gplus(ActiveComponent):
    """Room temperature amplifier, roughly 20 dB gain."""

    def __init__(self, name=None):
        super().__init__(name=name, params={})

        self.f_datasheet = 1e6 * np.asarray(
            [0, 20, 50, 100, 351, 500, 663, 866, 1000, 1168, 1378, 1500, 1671,
             1863, 2000, 2174, 2376, 2500, 2668, 2879, 3000])
        self.noise_figure_datasheet = np.asarray(
            [2.92, 2.92, 2.66, 2.61, 2.69, 2.72, 2.66, 2.69, 2.64, 2.60, 2.59,
             2.59, 2.60, 2.62, 2.63, 2.62, 2.61, 2.58, 2.60, 2.61, 2.64])
        self.noise_power_datasheet = kb * 290 * (10**(self.noise_figure_datasheet / 10) - 1)
        # ext=0 allows extrapolation
        self.noise_f = interpolate.UnivariateSpline(
            self.f_datasheet, self.noise_power_datasheet, ext=0)

        self.gain_datasheet = np.asarray(
            [22, 22.58, 22.75, 22.76, 22.61, 22.42, 22.28, 21.83, 21.83, 21.52,
             21.16, 20.97, 20.60, 20.39, 20.22, 20.04, 19.76, 19.56, 19.26,
             18.97, 18.78])
        self.gain_f = interpolate.UnivariateSpline(
            self.f_datasheet, self.gain_datasheet, ext=0)

        meas_gainf = np.asarray([0, 58, 470, 961.8, 1302, 1806, 2356, 2939, 3000]) * 1e6
        meas_gain = [23, 23., 22.45, 21.6, 20.7, 20.1, 19., 17.85, 17.8]
        self.meas_gain_func = interpolate.interp1d(
            meas_gainf, meas_gain, bounds_error=False)

    def gain(self, carrier_frequency):
        # Measured response is preferred over the datasheet fit.
        return self.meas_gain_func(carrier_frequency)

    def noise(self, f):
        return self.noise_f(f)


@register("attenuator", category="Attenuators", label="Attenuator",
          params=(
              ParamSpec("attenuation", default=-10.0, label="Attenuation",
                        unit="dB", minimum=-100.0, maximum=0.0, step=1.0,
                        help="Insertion loss, negative for attenuation."),
              ParamSpec("temperature", default=300.0, label="Temperature",
                        unit="K", minimum=0.0, maximum=400.0, step=1.0,
                        help="Physical temperature; sets the thermal noise "
                             "this attenuator adds."),
          ))
class Attenuator(PassiveComponent):
    """Temperature-aware attenuator; contributes k_B*T thermal noise."""

    def __init__(self, attenuation, temperature, name=None):
        super().__init__(name=name, params={
            "attenuation": attenuation,
            "temperature": temperature,
        })
        atten_drift = [0, -1]
        atten_drift_f = [1e6, 3e9]
        self.atten_func = interpolate.interp1d(
            atten_drift_f, atten_drift, bounds_error=False)
        self.attenuation = attenuation
        self.temperature = temperature

    def noise(self, frequency=None):
        """Thermal noise is frequency-independent; frequency accepted for API parity."""
        return kb * self.temperature

    def gain(self, carrier_frequency=None):
        if isinstance(carrier_frequency, (float, int)):
            return self.attenuation
        elif carrier_frequency is None:
            return self.attenuation
        else:
            return self.attenuation * np.ones(len(carrier_frequency))

    def gain_meas(self, carrier_frequency):
        return self.atten_func(carrier_frequency) + self.attenuation


@register("amplifier.asu_3ghz_lna", category="Amplifiers",
          label="ASU 3 GHz LNA (~6 K)")
class ASU_3GHz_LNA(ActiveComponent):
    """Cryogenic LNA, roughly 6 K noise temperature."""

    def __init__(self, name=None):
        super().__init__(name=name, params={})

        noise_f_datasheet = 1e9 * np.asarray([0, 0.2, 0.4, 0.6, 3])
        self.noise_temp_datasheet = np.asarray([30, 15, 7, 6, 6])
        self.noise_power_datasheet = kb * self.noise_temp_datasheet
        # Previously this interpolator was assigned to self.noise, shadowing the
        # noise() method. Naming it noise_f keeps the method callable.
        self.noise_f = interpolate.interp1d(
            noise_f_datasheet, self.noise_power_datasheet, bounds_error=False)

        self.f_datasheet = 1e9 * np.asarray([0, 0.1, 0.5, 1, 1.5, 2, 2.5, 3])
        self.gain_datasheet = np.asarray([-25, 0, 27, 32, 30, 30, 32, 33])
        self.gain_f = interpolate.interp1d(
            self.f_datasheet, self.gain_datasheet, bounds_error=False)

    def gain(self, carrier_frequency):
        return self.gain_f(carrier_frequency)

    def noise(self, f):
        return self.noise_f(f)


class _InterpolatedFilter(PassiveComponent):
    """Shared implementation for the fixed high-pass filter models."""

    #: (frequencies_Hz, gain_dB) datasheet response, set by each subclass.
    response = None

    def __init__(self, name=None):
        super().__init__(name=name, params={})
        f_datasheet, gain_datasheet = self.response
        self.gain_f = interpolate.interp1d(
            np.asarray(f_datasheet), np.asarray(gain_datasheet),
            bounds_error=False)

    def gain(self, carrier_frequency):
        return self.gain_f(carrier_frequency)


@register("filter.vhf1320p", category="Filters", label="Mini-Circuits VHF-1320+")
class FilterHP_VHF1320p(_InterpolatedFilter):
    """Mini-Circuits high-pass filter VHF-1320+"""

    response = (
        np.asarray([1, 100, 880, 1060, 1180, 1260, 1320, 1400, 1700, 3700]) * 1e6,
        np.asarray([-94, -69, -51, -27, -14, -6.3, -2.9, -1.6, -0.8, -0.5]),
    )


@register("filter.vhf1760p", category="Filters", label="Mini-Circuits VHF-1760+")
class FilterHP_VHF1760p(_InterpolatedFilter):
    """Mini-Circuits high-pass filter VHF-1760+"""

    response = (
        np.asarray([1, 100, 950, 1230, 1400, 1550, 1700, 1760, 1900, 2100,
                    2200, 4500]) * 1e6,
        np.asarray([-94, -65, -47, -24, -13, -6, -2.6, -1.9, -1.2, -0.8,
                    -0.7, -0.5]),
    )


@register("filter.vhf1910p", category="Filters", label="Mini-Circuits VHF-1910+")
class FilterHP_VHF1910p(_InterpolatedFilter):
    """Mini-Circuits high-pass filter VHF-1910+"""

    response = (
        np.asarray([1, 100, 1075, 1400, 1630, 1750, 1850, 1910, 2000, 2100,
                    2200, 4400]) * 1e6,
        np.asarray([-91, -76, -42, -26, -13, -7, -3.4, -2.2, -1.4, -1.1,
                    -1, -0.8]),
    )


class _TemperatureSwitchedCable(PassiveComponent):
    """
    Shared implementation for cryogenic cables that carry separate warm and cold
    datasheet curves and pick between them by physical temperature.

    Subclasses set ``frequencies_hz``, ``warm_db_per_m``, ``cold_db_per_m``,
    ``transition_k`` and ``extrapolate``. The total loss is the per-metre curve
    scaled by length, matching the original per-class implementations.
    """

    frequencies_hz = None
    warm_db_per_m = None
    cold_db_per_m = None
    transition_k = 100
    extrapolate = False

    def __init__(self, length_m, temperature=4, name=None):
        super().__init__(name=name, params={
            "length_m": length_m,
            "temperature": temperature,
        })
        self.length = length_m
        self.temperature = temperature

        fill = 'extrapolate' if self.extrapolate else np.nan
        freqs = np.asarray(self.frequencies_hz)
        warmgain = np.asarray(self.warm_db_per_m) * self.length
        coldgain = np.asarray(self.cold_db_per_m) * self.length

        self.warm_gain = interpolate.interp1d(
            freqs, warmgain, fill_value=fill, bounds_error=False)
        self.cold_gain = interpolate.interp1d(
            freqs, coldgain, fill_value=fill, bounds_error=False)

    def gain(self, carrier_frequency):
        """Insertion loss in dB, using the warm curve above ``transition_k``."""
        if self.temperature > self.transition_k:
            return self.warm_gain(carrier_frequency)
        return self.cold_gain(carrier_frequency)


CABLE_PARAMS = (LENGTH_PARAM, TEMPERATURE_PARAM)


@register("cable.sma_cuni_cryo", category="Cables",
          label="SMA CuNi 1.16mm (cryo)",
          params=(LENGTH_PARAM,
                  ParamSpec("temperature", default=4.0, label="Temperature",
                            unit="K", choices=(4.0, 300.0),
                            help="This model only carries 4 K and 300 K "
                                 "datasheet curves.")))
class SMA_CuNi_cryo(_TemperatureSwitchedCable):
    """1.16mm outer diameter CuNi coax as used in the McGill DR (cryocoax.com)."""

    frequencies_hz = np.asarray([0.001, 0.5, 1, 5]) * 1e9
    warm_db_per_m = np.asarray([-1, -2.1, -3, -6.7])
    cold_db_per_m = np.asarray([-0.5, -1, -1.5, -3.2])

    def __init__(self, length_m, temperature=4, name=None):
        if not int(temperature) in [300, 4]:
            raise ValueError(
                'Not recognized cable temperature value. Please choose either '
                '300 or 4 (values are in Kelvin).')
        super().__init__(length_m=length_m, temperature=temperature, name=name)

    def gain(self, carrier_frequency):
        # Preserves the original exact-match behaviour rather than a threshold.
        if self.temperature == 300:
            return self.warm_gain(carrier_frequency)
        elif self.temperature == 4:
            return self.cold_gain(carrier_frequency)


#################################################
# HARDWARE AS USED IN SLIM DEPLOYMENT 2024/2025 #
#################################################

@register("cable.sma_cuni086_cryo", category="Cables",
          label="SMA CuNi 0.86mm (cryo)", params=CABLE_PARAMS)
class SMA_CuNi086_cryo(_TemperatureSwitchedCable):
    """0.86mm outer diameter CuNi coax."""

    frequencies_hz = np.asarray([0.0, 0.5, 1.0, 5.0, 10.0]) * 1e9
    warm_db_per_m = np.asarray([0.0, -5.4, -7.7, -17.1, -24.3])
    cold_db_per_m = np.asarray([0.0, -4.1, -5.7, -12.8, -18.1])


@register("cable.sma_ss086_cryo", category="Cables",
          label="SMA Stainless 0.86mm (cryo)", params=CABLE_PARAMS)
class SMA_SS086_cryo(_TemperatureSwitchedCable):
    """0.86mm outer diameter stainless steel coax."""

    frequencies_hz = np.asarray([0.0, 0.5, 1.0, 5.0, 10.0]) * 1e9
    warm_db_per_m = np.asarray([0.0, -7.3, -10.3, -23.0, -32.7])
    cold_db_per_m = np.asarray([0.0, -4.7, -6.6, -14.8, -20.9])


@register("cable.sma_ss219_cryo", category="Cables",
          label="SMA Stainless 2.19mm (cryo)", params=CABLE_PARAMS)
class SMA_SS219_cryo(_TemperatureSwitchedCable):
    """2.19mm outer diameter stainless steel coax."""

    frequencies_hz = np.asarray([0.0, 0.5, 1.0, 5.0, 10.0]) * 1e9
    warm_db_per_m = np.asarray([0.0, -3.0, -4.2, -9.4, -13.5])
    cold_db_per_m = np.asarray([0.0, -1.9, -2.6, -5.9, -8.3])


@register("cable.sma_nbti086_cryo", category="Cables",
          label="SMA NbTi 0.86mm (cryo)", params=CABLE_PARAMS)
class SMA_NbTi086_cryo(_TemperatureSwitchedCable):
    """0.86mm outer diameter NbTi superconducting coax."""

    frequencies_hz = np.asarray([0.0, 0.5, 1.0, 5.0, 10.0]) * 1e9
    warm_db_per_m = np.asarray([0.0, -6.8, -9.6, -21.6, -30.5])
    cold_db_per_m = np.asarray([0.0, -0.5, -0.5, -0.5, -0.5])
    # NbTi goes superconducting near 9 K, not 100 K.
    transition_k = 9


@register("cable.bcb029_ss034", category="Cables",
          label="CryoCoax BCB029 SS 0.034\"", params=CABLE_PARAMS)
class BCB029_SS034_cryo(_TemperatureSwitchedCable):
    """
    0.034" diameter stainless steel coax (CryoCoax BCB029).
    Attenuation per metre at 300 K and 4 K from datasheet (page 2)
    https://cryocoax.com/wp-content/uploads/2020/07/034-SS_SS-BCB029-CRYO.pdf
    """

    frequencies_hz = np.asarray([0.0, 0.5, 1.0, 5.0, 10.0, 20.0]) * 1e9
    warm_db_per_m = np.asarray([0.0, -7.3, -10.3, -23.0, -32.7, -46.4])
    cold_db_per_m = np.asarray([0.0, -4.7, -6.6, -14.8, -20.9, -29.5])
    extrapolate = True


@register("cable.bcb014_ss085", category="Cables",
          label="CryoCoax BCB014 SS 0.085\"", params=CABLE_PARAMS)
class BCB014_SS085_cryo(_TemperatureSwitchedCable):
    """
    0.085" diameter stainless steel coax (CryoCoax BCB014).
    https://cryocoax.com/wp-content/uploads/2020/07/085-SS_SS-BCB014-CRYO.pdf
    """

    frequencies_hz = np.asarray([0.0, 0.5, 1.0, 5.0, 10.0, 20.0]) * 1e9
    warm_db_per_m = np.asarray([0.0, -3.0, -4.2, -9.4, -13.5, -19.2])
    cold_db_per_m = np.asarray([0.0, -1.9, -2.6, -5.9, -8.3, -11.7])
    extrapolate = True


@register("cable.bcb024_sp034", category="Cables",
          label="CryoCoax BCB024 CuNi 0.034\"", params=CABLE_PARAMS)
class BCB024_SP034_cryo(_TemperatureSwitchedCable):
    """
    0.034" diameter SP CuNi-CuNi coax (CryoCoax BCB024).
    https://cryocoax.com/wp-content/uploads/2020/07/034-SP-CuNiCuNi-BCB024-CRYO.pdf
    """

    frequencies_hz = np.asarray([0.0, 0.5, 1.0, 5.0, 10.0, 20.0]) * 1e9
    warm_db_per_m = np.asarray([0.0, -2.1, -3.0, -6.7, -9.5, -13.4])
    cold_db_per_m = np.asarray([0.0, -1.0, -1.5, -3.2, -4.6, -6.5])
    extrapolate = True


@register("cable.bcb012_nbti034", category="Cables",
          label="CryoCoax BCB012 NbTi 0.034\"", params=CABLE_PARAMS)
class BCB012_NbTi034_cryo(_TemperatureSwitchedCable):
    """
    0.034" diameter NbTi-NbTi coax (CryoCoax BCB012).
    4 K attenuation is listed as "<0.5 dB/m" and treated as 0.5 dB/m here.
    https://cryocoax.com/wp-content/uploads/2020/07/034-NbTiNbTi-BCB012-CRYO.pdf
    """

    frequencies_hz = np.asarray([0.0, 0.5, 1.0, 5.0, 10.0, 20.0]) * 1e9
    warm_db_per_m = np.asarray([0.0, -6.8, -9.6, -21.6, -30.5, -43.1])
    cold_db_per_m = np.asarray([0.0, -0.5, -0.5, -0.5, -0.5, -0.5])
    extrapolate = True


class _RoomTemperatureCable(PassiveComponent):
    """
    Shared implementation for room-temperature cables with a single loss curve.

    ``db_per_m`` is per-metre loss in dB and must be negative; the total is
    scaled by length exactly once, in gain().
    """

    frequencies_hz = None
    db_per_m = None
    extrapolate = False

    def __init__(self, length_m, name=None):
        super().__init__(name=name, params={"length_m": length_m})
        self.length = length_m

        fill = 'extrapolate' if self.extrapolate else np.nan
        self.atten_per_m = interpolate.interp1d(
            np.asarray(self.frequencies_hz),
            np.asarray(self.db_per_m, dtype=float),
            fill_value=fill, bounds_error=False)

    def gain(self, carrier_frequency):
        """Total insertion loss in dB over ``self.length`` metres."""
        return self.atten_per_m(carrier_frequency) * self.length


@register("cable.sma_generic", category="Cables",
          label="SMA generic (room temp)", params=(LENGTH_PARAM,))
class SMA_cables(_RoomTemperatureCable):
    """
    Typical room temperature SMA coax from L-com.com, e.g. LCCA30166.
    Loss measured with a VNA on a 10 ft cable, converted to per-metre.
    """

    frequencies_hz = np.asarray([0.001, 0.25, 0.5, 1, 2.5, 3.0]) * 1e9
    # Measured on a 10 ft cable; 3.2/10 converts the total to dB per metre.
    db_per_m = np.asarray([-0.2, -0.6, -0.8, -1.2, -1.8, -2.2]) * 3.2 / 10.


@register("cable.fm_f141", category="Cables",
          label="Fairview Microwave F141 (room temp)", params=(LENGTH_PARAM,))
class SMA_FM_F141_cables(_RoomTemperatureCable):
    """
    Room temperature SMA coax from Fairview Microwave, e.g. FMCA2155.
    https://www.fairviewmicrowave.com/content/dam/infinite-electronics/product-assets/fairview-microwave/product-datasheets/FMCA2155.pdf
    """

    frequencies_hz = np.asarray([0.0, 1, 2.0, 5, 10, 18]) * 1e9
    db_per_m = np.asarray([0.0, -0.37, -0.54, -0.89, -1.35, -1.9])


@register("cable.rg58c", category="Cables", label="RG58C/U (room temp)",
          params=(LENGTH_PARAM,))
class SMA_RG58C_cables(_RoomTemperatureCable):
    """
    Flexible RG58 coax, single-shielded, black PVC jacket.
    Attenuation per 100 m from https://www.pasternack.com/images/ProductPDF/RG58C-U.pdf
    """

    frequencies_hz = np.asarray([0.0, 0.01, 0.1, 1.0, 5.0]) * 1e9
    # Datasheet lists attenuation as positive dB/100 m; negated here because
    # gain() must return loss as a negative gain.
    db_per_m = -np.asarray([0.0, 4.59, 16.08, 65.62, 196.85]) / 100.0
    extrapolate = True


@register("cable.rg174a", category="Cables", label="RG174A/U (room temp)",
          params=(LENGTH_PARAM,))
class SMA_RG174A_cables(_RoomTemperatureCable):
    """
    Flexible RG174 coax, single-shielded, black PVC jacket.
    Attenuation per 100 m from https://www.pasternack.com/images/ProductPDF/RG174A-U-BULK.pdf
    """

    frequencies_hz = np.asarray([0.0, 0.1, 0.4, 1.0]) * 1e9
    # Datasheet lists attenuation as positive dB/100 m; negated here because
    # gain() must return loss as a negative gain.
    db_per_m = -np.asarray([0.0, 27.56, 62.34, 104.99]) / 100.0
    extrapolate = True
