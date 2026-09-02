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

from component import (ActiveComponent, ADCComponent, DACComponent,
                       PassiveComponent, flat_in_spectral)
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

    def carrier_level_db(self, carrier_frequency):
        """
        Level shift in dB applied to the phase-noise skirt at this carrier.

        The datasheet gives phase noise at a few discrete carriers, but the
        fitted model here is carrier-independent, so this is 0 dB. It is the
        hook for a measured carrier dependence: the 1/f-ish spectral shape
        would be preserved and simply shifted by whatever this returns.
        """
        return 0.0

    def noise(self, carrier_frequency, spectral_frequency):
        """
        Return DAC phase noise PSD in W/Hz.

        The shape comes from the spectral frequency - this is a 1/f skirt around
        the carrier - and the level from the carrier power, plus any carrier
        frequency dependence from :meth:`carrier_level_db`.
        """
        noise_dbc = 10 * np.log10(
            1e3 * exponential(spectral_frequency,
                              self.popt[0], self.popt[1], self.popt[2]))
        noise_dbm = (noise_dbc + self.carrier_power_dbm
                     + self.carrier_level_db(carrier_frequency))
        return 10**(noise_dbm / 10) * 1e-3


@register("converter.ad9082_adc", category="Converters", label="AD9082 ADC",
          params=(
              ParamSpec("gain_db", default=0.0, label="Gain", unit="dB",
                        minimum=-50.0, maximum=50.0, step=0.5),
          ))
class AD9082_ADC(ADCComponent):
    """
    AD9082 Analog-to-Digital Converter.

    The noise floor is derived from the datasheet SNR versus input frequency, so
    it varies with the carrier frequency and is white in spectral frequency.
    """

    #: Datasheet SNR versus input frequency, in dB relative to full scale.
    snr_frequencies_hz = np.asarray([0.001, 1, 1.5, 2, 2.5, 3]) * 1e9
    snr_dbfs = np.asarray([56, 55.5, 55, 54.5, 52, 51.5])

    #: Conditions the SNR figures were quoted under. An SNR spec only converts
    #: to a power spectral density given the full-scale level and the bandwidth
    #: the noise was integrated over, so these belong to the datasheet rather
    #: than being free knobs. Override on a subclass for a different part or a
    #: different operating configuration.
    full_scale_dbm = 1.0
    nyquist_bandwidth_hz = 3e9

    def __init__(self, gain_db=0.0, name=None):
        super().__init__(name=name, params={"gain_db": gain_db})
        self.gain_db = gain_db

        # SNR (dB below full scale) -> noise power (dBm) -> W -> W/Hz.
        noise_w_per_hz = (
            10**((self.full_scale_dbm - self.snr_dbfs) / 10) * 1e-3
            / self.nyquist_bandwidth_hz)
        self.noise_f = interpolate.interp1d(
            self.snr_frequencies_hz, noise_w_per_hz,
            fill_value='extrapolate', bounds_error=False)

    def gain(self, carrier_frequency):
        """Return ADC gain in dB."""
        if isinstance(carrier_frequency, np.ndarray):
            return np.full_like(carrier_frequency, self.gain_db)
        return self.gain_db

    def noise(self, carrier_frequency, spectral_frequency):
        """
        Return ADC noise PSD in W/Hz at the ADC input.

        Interpolated from the datasheet SNR curve at the carrier frequency, and
        white across the spectral axis.
        """
        return flat_in_spectral(self.noise_f(carrier_frequency),
                                spectral_frequency)


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

    def noise(self, carrier_frequency, spectral_frequency):
        """Noise temperature varies with carrier; white in spectral frequency."""
        return flat_in_spectral(self.noise_f(carrier_frequency),
                                spectral_frequency)


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

    def noise(self, carrier_frequency, spectral_frequency):
        """Noise figure varies with carrier; white in spectral frequency."""
        return flat_in_spectral(self.noise_f(carrier_frequency),
                                spectral_frequency)


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

    def noise(self, carrier_frequency, spectral_frequency):
        """Johnson noise: k_B*T, flat in both carrier and spectral frequency."""
        return flat_in_spectral(kb * self.temperature, spectral_frequency)

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

    def noise(self, carrier_frequency, spectral_frequency):
        """Noise temperature varies with carrier; white in spectral frequency."""
        return flat_in_spectral(self.noise_f(carrier_frequency),
                                spectral_frequency)


class _InterpolatedLNA(ActiveComponent):
    """
    Shared implementation for the fixed cryogenic LNA models.

    Subclasses set ``gain_response`` and ``noise_response``, each a
    ``(frequencies_Hz, values)`` pair - gain in dB, noise as a temperature in K,
    which is how these parts are specified and measured.

    Both curves keep the sibling LNAs' out-of-band behaviour: NaN rather than an
    extrapolated number, since an amplifier outside its band is not a gentler
    version of itself the way a filter's stopband is, and the measured rolloff
    at the edge says nothing about what happens past it. That NaN is also what
    ``chain_api`` bisects for to find the band a spec panel plots over, so the
    band shown is the measurement's own.

    ``noise_response`` must cover at least the span of ``gain_response``, or a
    chain would take gain from a component that reports no noise there.
    """

    #: (frequencies_Hz, gain_dB), set by each subclass.
    gain_response = None
    #: (frequencies_Hz, noise_temperature_K), set by each subclass.
    noise_response = None

    def __init__(self, name=None):
        super().__init__(name=name, params={})

        gain_f, gain_db = self.gain_response
        self.f_datasheet = np.asarray(gain_f, dtype=float)
        self.gain_datasheet = np.asarray(gain_db, dtype=float)
        self.gain_f = interpolate.interp1d(
            self.f_datasheet, self.gain_datasheet, bounds_error=False)

        noise_f, noise_temp_k = self.noise_response
        noise_freqs = np.asarray(noise_f, dtype=float)
        self.noise_temp_datasheet = np.asarray(noise_temp_k, dtype=float)
        self.noise_power_datasheet = kb * self.noise_temp_datasheet
        self.noise_f = interpolate.interp1d(
            noise_freqs, self.noise_power_datasheet, bounds_error=False)

        # Checked rather than trusted to the docstring: a noise curve narrower
        # than the gain curve gives a band where the component amplifies and
        # reports no noise for doing it, which reads as a free improvement to
        # the budget instead of as missing data. Datasheets really do tabulate
        # the two over different spans, so this is a live mistake to make.
        if (noise_freqs.min() > self.f_datasheet.min()
                or noise_freqs.max() < self.f_datasheet.max()):
            raise ValueError(
                f"{type(self).__name__}: noise_response covers "
                f"{noise_freqs.min() / 1e9:g}-{noise_freqs.max() / 1e9:g} GHz "
                f"but gain_response covers "
                f"{self.f_datasheet.min() / 1e9:g}-"
                f"{self.f_datasheet.max() / 1e9:g} GHz; the noise curve has to "
                f"span at least the gain curve"
            )

    def gain(self, carrier_frequency):
        return self.gain_f(carrier_frequency)

    def noise(self, carrier_frequency, spectral_frequency):
        """Noise temperature varies with carrier; white in spectral frequency."""
        return flat_in_spectral(self.noise_f(carrier_frequency),
                                spectral_frequency)


@register("amplifier.cmt_citcryo1_12d", category="Amplifiers",
          label="CMT CITCRYO1-12D (~5 K)")
class CMT_CITCRYO1_12D(_InterpolatedLNA):
    """
    Cryogenic LNA, 1-12 GHz, roughly 5 K noise temperature.

    Gain is measured rather than quoted: the SN216D s2p at 13 K, Vd = 1.2 V,
    which runs to 14 GHz and so past the 1-12 GHz the part is specified over.

    Noise is the datasheet's single 5 K figure at 12 K physical, held flat,
    because no digitised noise-versus-frequency curve was supplied for this
    part. Flat is what one number can honestly say; it is not a measurement of
    flatness, and a real HEMT's noise rises at both band edges.
    """

    gain_response = (
        1e9 * np.asarray(
            [1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 5.5,
             6, 6.5, 7, 7.5, 8, 8.5, 9, 9.5, 10, 10.5,
             11, 11.5, 12, 12.5, 13, 13.5, 14]),
        np.asarray(
            [34.8, 36.1, 37, 37.1, 37.2, 37, 36.8, 36.6, 36.6, 36.6,
             36.7, 36.8, 37.1, 37.3, 37.4, 37.2, 37.5, 37.5, 37.6, 37.4,
             37.1, 37.2, 37.2, 37.1, 37, 36.5, 36.3]),
    )
    # Spans the gain curve, so the two are defined over the same band.
    noise_response = (1e9 * np.asarray([1, 14]), np.asarray([5.0, 5.0]))


@register("amplifier.lnf_lnc1_5_6b", category="Amplifiers",
          label="LNF-LNC1.5_6B (~1.8 K)")
class LNF_LNC1_5_6B(_InterpolatedLNA):
    """
    Cryogenic LNA, 1.5-6 GHz, roughly 1.8 K noise temperature.

    Low Noise Factory LNC1.5_6B at 5 K, on its one published bias point,
    Vds = 1.9 V and Ids = 29 mA. The noise curve is the reason to reach for this
    part and the reason to read it before trusting the headline: 1.6 K over the
    middle of the band, but 6 K at 1.5 GHz, so the bottom decile of the band
    costs more than three times the quoted figure.
    """

    gain_response = (
        1e9 * np.asarray([1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0]),
        np.asarray([30.6, 28.3, 28.0, 27.8, 27.4, 27.3, 27.5, 27.6, 27.9,
                    28.0]),
    )
    noise_response = (
        1e9 * np.asarray([1.5, 1.6, 1.8, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0,
                          5.5, 6.0]),
        np.asarray([6.0, 4.0, 2.0, 1.65, 1.6, 1.65, 1.65, 1.7, 1.7, 1.95,
                    2.0, 2.3]),
    )


@register("amplifier.lnf_lnc0_3_14b", category="Amplifiers",
          label="LNF-LNC0.3_14B (~3.6 K)")
class LNF_LNC0_3_14B(_InterpolatedLNA):
    """
    Cryogenic LNA, 0.3-14 GHz, roughly 3.6 K noise temperature.

    Low Noise Factory LNC0.3_14B at 5 K, on its 19.2 mW bias point,
    Vd = 1.2 V and Id = 16 mA. Two decades of band at 38 dB, with noise best in
    the middle - 2.4 K around 7 GHz - and worst at both ends, 6.5 K at 500 MHz
    and 8 K at 14 GHz. The headline 3.6 K is met over roughly 2-10 GHz and
    nowhere near the edges, which is the whole reason the curve is carried.

    The 0.3 GHz noise point is extended from the measured 0.5-1.0 GHz slope, not
    measured: gain is published from 0.3 GHz but noise only from 0.5 GHz, and
    dropping the 0.3 GHz gain point instead would silently narrow a part whose
    name is its band. It is the one estimated number here.

    The datasheet also sweeps bias from 800 uW to this 19.2 mW point, over which
    gain falls to about 20 dB and the noise roughly doubles. Only the 19.2 mW
    curve is modelled, since there is no bias parameter to select the other end
    with, so this is the part at full power and not at its quietest setting.
    """

    gain_response = (
        1e9 * np.asarray([0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0,
                          7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0]),
        np.asarray([30.0, 37.0, 40.2, 40.4, 40.0, 39.5, 39.0, 38.6, 38.3,
                    38.2, 38.1, 38.0, 37.9, 37.9, 37.9, 38.0, 38.2, 36.5]),
    )
    noise_response = (
        1e9 * np.asarray([0.3, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0,
                          8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0]),
        #  7.1 K at 0.3 GHz continues the 0.5-1.0 GHz slope; see the docstring.
        np.asarray([7.1, 6.5, 5.0, 4.0, 3.5, 3.0, 2.75, 2.6, 2.5, 2.4,
                    2.6, 3.0, 3.5, 4.25, 4.75, 5.5, 8.0]),
    )


class _InterpolatedFilter(PassiveComponent):
    """
    Shared implementation for the fixed filter models, high- and low-pass alike.

    ``response`` is the datasheet's tabulated insertion loss, negated into gain.
    Beyond the tabulated span the endpoint slope is extended, so a chain
    evaluated where the datasheet is silent gets a usable estimate rather than a
    NaN that poisons the whole budget. The extension is clamped to keep it
    physical: never above 0 dB, since a passive filter cannot amplify, and never
    below the deepest loss the datasheet actually measured, since a linear
    extension run far enough would otherwise claim absurd rejection. Both bounds
    are inert inside the tabulated span, where the datasheet still governs.

    Treat extrapolated values as an indication, not a specification - the far
    stopband of a real filter is re-entrant, and no straight line predicts that.
    """

    #: (frequencies_Hz, gain_dB) datasheet response, set by each subclass.
    response = None

    def __init__(self, name=None):
        super().__init__(name=name, params={})
        f_datasheet, gain_datasheet = self.response
        freqs = np.asarray(f_datasheet, dtype=float)
        gains = np.asarray(gain_datasheet, dtype=float)
        self.gain_f = interpolate.interp1d(
            freqs, gains, fill_value='extrapolate', bounds_error=False)
        self.gain_floor_db = float(gains.min())
        self._span_hz = (float(freqs.min()), float(freqs.max()))

    def gain(self, carrier_frequency):
        return np.clip(self.gain_f(carrier_frequency), self.gain_floor_db, 0.0)

    def defined_span_hz(self):
        """
        The carrier band the datasheet tabulates, low and high in Hz.

        ``gain`` answers outside this band too, by extending the endpoint slope,
        so the returned value is the model stating where it is quoting measured
        data rather than estimating. A caller that needs the distinction has to
        ask, because the gain itself no longer shows it.
        """
        return self._span_hz


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


@register("filter.vhf5050p", category="Filters", label="Mini-Circuits VHF-5050+")
class FilterHP_VHF5050p(_InterpolatedFilter):
    """
    Mini-Circuits high-pass filter VHF-5050+

    Passband 5500-10000 MHz, 3 dB cutoff 5050 MHz nominal, 5 sections, SMA.
    Points are the datasheet's "Typical Performance Data at 25C" table, which
    spans 50 MHz to 15 GHz; outside that the response is extrapolated.
    """

    response = (
        np.asarray([50, 1000, 3600, 4200, 4700, 4800, 4950, 5050, 5200, 5500,
                    5650, 9700, 10000, 10700, 12000, 14000, 15000]) * 1e6,
        np.asarray([-60.91, -36.10, -30.42, -31.29, -13.75, -9.55, -4.71,
                    -2.71, -1.34, -0.85, -0.79, -0.53, -0.66, -1.25, -2.99,
                    -2.65, -5.25]),
    )


@register("filter.vlf6700p", category="Filters", label="Mini-Circuits VLF-6700+")
class FilterLP_VLF6700p(_InterpolatedFilter):
    """
    Mini-Circuits low-pass filter VLF-6700+

    Passband DC-6700 MHz, 3 dB cutoff 7600 MHz nominal, 7 sections, SMA.
    Points are the datasheet's "Typical Performance Data at 25C" table, which
    spans 50 MHz to 19.89 GHz; outside that the response is extrapolated. The
    passband does extend down to DC, and extending the shallow 50-500 MHz slope
    is a fair estimate there, but no measured point below 50 MHz is published.
    """

    response = (
        np.asarray([50, 500, 1000, 3500, 5000, 6700, 7600, 8000, 9000, 10000,
                    12000, 15000, 17000, 18000, 19890]) * 1e6,
        np.asarray([-0.03, -0.08, -0.15, -0.25, -0.47, -0.79, -3.12, -7.62,
                    -26.00, -55.95, -34.91, -26.32, -23.79, -21.88, -22.46]),
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
