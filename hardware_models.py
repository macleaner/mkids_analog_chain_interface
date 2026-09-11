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

from dataclasses import replace

import numpy as np
import scipy.interpolate as interpolate
from scipy.optimize import curve_fit

from component import (ActiveComponent, ADCComponent, DACComponent,
                       PassiveComponent, flat_in_spectral)
from registry import ParamSpec, RetiredParam, register
from utils import kb


def exponential(f, A, n, b):
    return A * f**-n + b


# Every converter used to declare a gain, which a converter does not have - see
# `ConverterComponent`. Files that recorded it are still loadable at the 0 dB it
# defaulted to; one that recorded real gain there is refused rather than quietly
# flattened, since that gain belongs to a stage nobody has written down yet.
RETIRED_CONVERTER_GAIN = RetiredParam(
    "gain_db", 0.0,
    "a converter is the boundary of the analog path, not a stage along it, so "
    "gain at either end is an amplifier or an attenuator and belongs in the "
    "chain as one")


# Parameter specs reused across the cable models.
LENGTH_PARAM = ParamSpec("length_m", default=1.0, label="Length", unit="m",
                         minimum=0.0, maximum=100.0, step=0.1,
                         help="Physical cable length in metres.")
TEMPERATURE_PARAM = ParamSpec("temperature", default=4.0, label="Temperature",
                              unit="K", minimum=0.0, maximum=400.0, step=1.0,
                              help="Physical temperature of the component.")


def _datasheet_curve(frequencies_hz, values):
    """
    An interpolator over one datasheet column that answers outside it as well.

    Returns ``(curve, ceiling, span_hz)``:

    * ``curve`` extends the endpoint slope past either end of the tabulated
      range instead of filling with NaN. A NaN in a chain's dB sum takes the
      whole total with it, so one part tabulated over a narrower band than the
      sweep used to leave the chain with no gain curve at all rather than with
      an estimate over the part of it nobody measured.
    * ``ceiling`` is the highest tabulated value, which callers clamp the curve
      to. An extension can therefore never claim more gain - or less loss - than
      the datasheet actually measured, whichever end it runs off. There is
      deliberately no clamp the other way: a part driven past its band loses
      gain, and an extension that keeps losing it errs toward the pessimistic
      side of a budget.
    * ``span_hz`` is the tabulated range, low and high in Hz, which a model
      reports as ``defined_span_hz``. Nothing in the returned curve marks that
      boundary any more, which is exactly why the model has to state it.

    Values outside the span are an indication, not a specification: an
    amplifier's out-of-band response is set by its matching networks, a real
    filter's far stopband is re-entrant, and coax loss climbs as sqrt(f). No
    straight line predicts any of the three. They differ in how they fail,
    though, and only the first two are reported per stage - see
    ``flags_extrapolation`` on :class:`_DatasheetSpan`.
    """
    freqs = np.asarray(frequencies_hz, dtype=float)
    tabulated = np.asarray(values, dtype=float)
    curve = interpolate.interp1d(freqs, tabulated, fill_value='extrapolate',
                                 bounds_error=False)
    return (curve, float(tabulated.max()),
            (float(freqs.min()), float(freqs.max())))


class _DatasheetSpan:
    """
    Mixin for a model that answers outside its datasheet and says where it ends.

    ``_span_hz`` is set at construction from the tabulated range (see
    :func:`_datasheet_curve`); ``defined_span_hz`` is how the model states it.
    A caller that needs the distinction has to ask, because the gain itself no
    longer shows it - ``chain_api`` asks per stage and the GUI shades the rest
    of the sweep.

    ``flags_extrapolation`` is a separate question from where the band ends:
    whether leaving it is worth telling the reader about. It is the model's call
    and not the view's, because it depends on what the curve is a curve of - see
    the cables, which set it False.
    """

    #: (low_hz, high_hz) the gain curve is tabulated over; set at construction.
    _span_hz = None

    #: Whether a sweep past ``_span_hz`` is worth reporting as an estimate.
    #: True by default: for most parts the extension is a straight line through
    #: behaviour no straight line describes - an amplifier's matching networks,
    #: a filter's re-entrant stopband - so a reader who cannot see the band edge
    #: in the curve needs to be told where it was. A model whose loss follows a
    #: known trend outside its table sets this False.
    flags_extrapolation = True

    def defined_span_hz(self):
        """The carrier band the gain curve is tabulated over, low and high in Hz."""
        return self._span_hz


class _DatasheetGain(_DatasheetSpan):
    """
    Gain from one tabulated curve, extrapolated and clamped as above.

    For the models whose gain is a single column against frequency: the
    amplifiers. ``_set_gain_response`` builds the curve and hands it back, so a
    class can keep whatever attribute name it has always exposed it under.

    Every amplifier here used to return NaN outside its table. That stated the
    band the other way round - and ``chain_api`` bisected for the NaN to find it
    - but it also meant a chain swept past its narrowest part had no total gain
    anywhere, which is a worse answer than a flagged estimate.
    """

    def _set_gain_response(self, frequencies_hz, gains_db):
        """Build the gain curve, and hand it back for a class to alias."""
        (self._gain_curve, self._gain_ceiling_db,
         self._span_hz) = _datasheet_curve(frequencies_hz, gains_db)
        return self._gain_curve

    def gain(self, carrier_frequency):
        return np.minimum(self._gain_curve(carrier_frequency),
                          self._gain_ceiling_db)


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
          ),
          retired=(RETIRED_CONVERTER_GAIN,))
class AD9082_DAC(DACComponent):
    """
    AD9082 Digital-to-Analog Converter.

    Produces frequency-dependent phase noise that scales with carrier power.
    """

    def __init__(self, carrier_power_dbm=0.0, name=None):
        super().__init__(name=name, params={
            "carrier_power_dbm": carrier_power_dbm,
        })
        self.carrier_power_dbm = carrier_power_dbm

        # Phase noise model (identical to the legacy AD9082).
        f_datasheet = np.asarray([0.0001, 0.001, 0.01, 0.1, 1, 10, 100, 1000, 10000])
        pnoise_dbc_simple = np.asarray([-45, -55, -65, -75, -85, -95, -105, -115, -125])
        pnoise_W = 10**(pnoise_dbc_simple / 10) * 1e-3
        self.popt, self.pcov = curve_fit(exponential, f_datasheet, pnoise_W)

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
          retired=(RETIRED_CONVERTER_GAIN,))
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

    def __init__(self, name=None):
        super().__init__(name=name, params={})

        # SNR (dB below full scale) -> noise power (dBm) -> W -> W/Hz.
        noise_w_per_hz = (
            10**((self.full_scale_dbm - self.snr_dbfs) / 10) * 1e-3
            / self.nyquist_bandwidth_hz)
        self.noise_f = interpolate.interp1d(
            self.snr_frequencies_hz, noise_w_per_hz,
            fill_value='extrapolate', bounds_error=False)

    def noise(self, carrier_frequency, spectral_frequency):
        """
        Return ADC noise PSD in W/Hz at the ADC input.

        Interpolated from the datasheet SNR curve at the carrier frequency, and
        white across the spectral axis.
        """
        return flat_in_spectral(self.noise_f(carrier_frequency),
                                spectral_frequency)


# Shared by the two generic converters: the switch that turns a converter into
# an ideal one. It exists so a chain can be judged on the components alone -
# with a real digitizer at both ends the converters routinely dominate the
# budget, and "how good is this chain" and "how good is this chain with this
# digitizer" are different questions. Setting the level knobs to their minimum
# would not answer the first one: -220 dBm/Hz is small, not absent, and it still
# appears in the budget as a line to be discounted by eye.
NOISELESS_PARAM = ParamSpec(
    "noiseless", default=False, kind="bool", label="Noiseless",
    help="Make this converter an ideal one: for a DAC it still sets the "
         "carrier, but it contributes no noise at all and so drops out of the "
         "budget entirely.")

# The Generic DAC's four noise knobs are collected under one heading in the GUI,
# so the one that describes what the DAC *puts out* - the carrier power - is not
# read as part of the skirt. The carrier power does scale the skirt, being what
# it is quoted relative to, but it is the output level first and a noise setting
# only consequently, so it stays outside the box; the help text on both is where
# that relationship is stated.
NOISE_GROUP = "Noise parameters"


@register("converter.generic_dac", category="Converters", label="Generic DAC",
          params=(
              ParamSpec("carrier_power_dbm", default=0.0, label="Carrier Power",
                        unit="dBm", minimum=-80.0, maximum=30.0, step=1.0,
                        help="Carrier power at the DAC output. The phase-noise "
                             "skirt scales with it, so raising the carrier "
                             "raises the noise by the same number of dB."),
              ParamSpec("phase_noise_dbc_per_hz", default=-85.0,
                        label="Phase Noise", unit="dBc/Hz",
                        minimum=-200.0, maximum=0.0, step=1.0,
                        group=NOISE_GROUP,
                        help="Single-sideband phase noise at the reference "
                             "offset below, relative to the carrier."),
              ParamSpec("phase_noise_offset_hz", default=1.0,
                        label="Quoted At", unit="Hz",
                        minimum=0.001, maximum=1e12, step=1.0,
                        group=NOISE_GROUP,
                        help="Offset from the carrier the figure above is "
                             "quoted at. Datasheets usually pick 1 kHz or "
                             "10 kHz; this defaults to 1 Hz. Bounded away from "
                             "0 Hz, which is the carrier and not an offset "
                             "from it."),
              ParamSpec("phase_noise_slope_db_per_decade", default=-10.0,
                        label="Slope", unit="dB/decade",
                        minimum=-40.0, maximum=0.0, step=1.0,
                        group=NOISE_GROUP,
                        help="How the skirt falls with offset. -10 dB/decade "
                             "is 1/f in power, -20 is 1/f^2, and 0 is a white "
                             "phase-noise floor."),
              replace(NOISELESS_PARAM, group=NOISE_GROUP),
          ),
          retired=(RETIRED_CONVERTER_GAIN,))
class GenericDAC(DACComponent):
    """
    Configurable DAC: a carrier at a chosen power with a power-law noise skirt.

    For evaluating a chain against an arbitrary digitizer rather than the one
    part this library happens to model. The skirt is a straight line on a
    log-log plot, stated the way a datasheet states it - a level in dBc/Hz, the
    offset it is quoted at, and a slope in dB/decade:

        L(f) = phase_noise_dbc_per_hz
               + slope * log10(f / phase_noise_offset_hz)      [dBc/Hz]

    and the density in W/Hz is that plus the carrier power. Two decisions worth
    naming:

    * There is no broadband floor term. The AD9082 model here fits one and it
      comes out at zero, so a pure power law is what the library's real DAC
      already is; adding a floor knob to the generic one would offer a shape
      nothing has been checked against. A white floor is instead reached by
      setting the slope to 0.
    * The defaults reproduce the AD9082's simple phase-noise model exactly
      (-85 dBc/Hz at 1 Hz falling 10 dB/decade), so an unedited Generic DAC is
      a familiar part rather than an arbitrary one, and swapping the two shows
      what the datasheet SNR curve on the ADC side is worth on its own.

    The declared slope range stops at 0, so a skirt that rises with offset -
    which is not a phase-noise skirt - is refused by anything going through the
    registry: the GUI, and a chain loaded from a file. Constructing the class
    directly skips that, as it does for every component here.
    """

    def __init__(self, carrier_power_dbm=0.0, phase_noise_dbc_per_hz=-85.0,
                 phase_noise_offset_hz=1.0,
                 phase_noise_slope_db_per_decade=-10.0, noiseless=False,
                 name=None):
        super().__init__(name=name, params={
            "carrier_power_dbm": carrier_power_dbm,
            "phase_noise_dbc_per_hz": phase_noise_dbc_per_hz,
            "phase_noise_offset_hz": phase_noise_offset_hz,
            "phase_noise_slope_db_per_decade": phase_noise_slope_db_per_decade,
            "noiseless": noiseless,
        })
        # A zero or negative reference offset makes log10(f/f_ref) meaningless
        # and would return inf or nan for every offset rather than failing, so
        # it is refused here and not only by the registry's parameter range -
        # the class is constructed directly by scripts and by the
        # characterization tests too.
        if not phase_noise_offset_hz > 0:
            raise ValueError(
                f"phase_noise_offset_hz must be positive, got "
                f"{phase_noise_offset_hz!r}: the skirt is quoted at an offset "
                f"from the carrier, and 0 Hz is the carrier itself.")
        self.carrier_power_dbm = carrier_power_dbm
        self.phase_noise_dbc_per_hz = phase_noise_dbc_per_hz
        self.phase_noise_offset_hz = phase_noise_offset_hz
        self.phase_noise_slope_db_per_decade = phase_noise_slope_db_per_decade
        self.noiseless = noiseless

    def noise(self, carrier_frequency, spectral_frequency):
        """
        Return the phase-noise PSD in W/Hz.

        Evaluated as a power law in linear units rather than as a level plus
        ``slope * log10(offset)``: the two agree wherever both are defined, but
        the log form returns nan for a white skirt at zero offset (0 * -inf)
        where the power law returns the level, and a white skirt at the carrier
        is a perfectly sensible thing to ask about. A falling skirt at zero
        offset is infinite either way, which is what a 1/f law says.

        Carrier-frequency independent: a generic part is not claiming a measured
        carrier dependence it does not have.
        """
        if self.noiseless:
            return flat_in_spectral(0.0, spectral_frequency)
        offset = np.asarray(spectral_frequency, dtype=float)
        level_w_per_hz = 10**((self.phase_noise_dbc_per_hz
                               + self.carrier_power_dbm) / 10) * 1e-3
        ratio = (offset / self.phase_noise_offset_hz) ** (
            self.phase_noise_slope_db_per_decade / 10)
        return level_w_per_hz * ratio


@register("converter.generic_adc", category="Converters", label="Generic ADC",
          params=(
              ParamSpec("noise_density_dbm_per_hz", default=-140.0,
                        label="Input Noise", unit="dBm/Hz",
                        minimum=-220.0, maximum=0.0, step=1.0,
                        help="White noise floor at the digitizer input. "
                             "-174 dBm/Hz is a 300 K thermal floor; the AD9082 "
                             "datasheet's flat figure is -140."),
              NOISELESS_PARAM,
          ),
          retired=(RETIRED_CONVERTER_GAIN,))
class GenericADC(ADCComponent):
    """
    Configurable ADC: one white noise density, flat in carrier and in offset.

    For evaluating a chain against an arbitrary digitizer. A single number is
    the whole model, because that is the form a noise floor is usually available
    in - a datasheet's noise spectral density, or an SNR and a bandwidth worked
    out by hand - and inventing a frequency dependence for it would be putting
    in structure the number does not carry.

    The density stands at the ADC input, which is where the analog path ends
    and the only plane the figure could be quoted at - a converter has no gain
    to refer it across (see ``ConverterComponent``).

    Compare with ``AD9082_ADC``, which derives a carrier-dependent floor from a
    datasheet SNR curve. Its own datasheet also quotes a flat -140 dBm/Hz, which
    is this model's default - so the two side by side are the discrepancy noted
    in the README, in a form a budget can be run against.
    """

    def __init__(self, noise_density_dbm_per_hz=-140.0, noiseless=False,
                 name=None):
        super().__init__(name=name, params={
            "noise_density_dbm_per_hz": noise_density_dbm_per_hz,
            "noiseless": noiseless,
        })
        self.noise_density_dbm_per_hz = noise_density_dbm_per_hz
        self.noiseless = noiseless

    def noise(self, carrier_frequency, spectral_frequency):
        """Return the input noise PSD in W/Hz, white across both axes."""
        if self.noiseless:
            return flat_in_spectral(0.0, spectral_frequency)
        return flat_in_spectral(
            10**(self.noise_density_dbm_per_hz / 10) * 1e-3, spectral_frequency)


@register("amplifier.cryoelec_lna", category="Amplifiers",
          label="CryoElec LNA (~4 K)")
class CryoElec_LNA(_DatasheetGain, ActiveComponent):
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
        self.gain_f = self._set_gain_response(self.f_datasheet,
                                              self.gain_datasheet)

    def noise(self, carrier_frequency, spectral_frequency):
        """Noise temperature varies with carrier; white in spectral frequency."""
        return flat_in_spectral(self.noise_f(carrier_frequency),
                                spectral_frequency)


@register("amplifier.zx60_3018g_plus", category="Amplifiers",
          label="Mini-Circuits ZX60-3018G+")
class ZX60_3018Gplus(_DatasheetGain, ActiveComponent):
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

        # The measured response is what gain() answers with; the datasheet fit
        # above is kept for comparison. So it is the measurement's span that
        # this model reports as its band, and past 3 GHz the extension runs off
        # a part specified to 3 GHz - flagged, and worth distrusting.
        meas_gainf = np.asarray([0, 58, 470, 961.8, 1302, 1806, 2356, 2939, 3000]) * 1e6
        meas_gain = [23, 23., 22.45, 21.6, 20.7, 20.1, 19., 17.85, 17.8]
        self.meas_gain_func = self._set_gain_response(meas_gainf, meas_gain)

    def noise(self, carrier_frequency, spectral_frequency):
        """Noise figure varies with carrier; white in spectral frequency."""
        return flat_in_spectral(self.noise_f(carrier_frequency),
                                spectral_frequency)


@register("attenuator", category="Attenuators", label="Attenuator",
          params=(
              ParamSpec("attenuation", default=-10.0, label="Attenuation",
                        unit="dB", minimum=-100.0, maximum=0.0, step=1.0,
                        help="Insertion loss, negative for attenuation."),
              # No upper bound: the noise this model adds is k_B*T exactly,
              # proportional to temperature at any temperature, so there is no
              # datasheet edge for a ceiling to stand on. Whether the part
              # survives the temperature asked about is the user's business.
              ParamSpec("temperature", default=300.0, label="Temperature",
                        unit="K", minimum=0.0, step=1.0,
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
class ASU_3GHz_LNA(_DatasheetGain, ActiveComponent):
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
        self.gain_f = self._set_gain_response(self.f_datasheet,
                                              self.gain_datasheet)

    def noise(self, carrier_frequency, spectral_frequency):
        """Noise temperature varies with carrier; white in spectral frequency."""
        return flat_in_spectral(self.noise_f(carrier_frequency),
                                spectral_frequency)


class _InterpolatedLNA(_DatasheetGain, ActiveComponent):
    """
    Shared implementation for the fixed low-noise amplifier models, cryogenic
    and room-temperature alike.

    Subclasses set ``gain_response`` and ``noise_response``, each a
    ``(frequencies_Hz, values)`` pair - gain in dB, noise as a temperature in K,
    which is how the cold parts are specified and measured. A part quoted as a
    noise figure instead converts at the subclass, ``290 * (10**(NF/10) - 1)``,
    so the datasheet's own numbers stay legible in the source and only one unit
    reaches the interpolator.

    The two curves treat their edges differently, on purpose. Gain extrapolates
    and reports its band (see :class:`_DatasheetGain`), because a chain's total
    gain is a dB sum and one NaN in it leaves the whole sweep blank. Noise still
    returns NaN outside its table, because there is no honest cap on it the way
    there is on gain: a HEMT's noise rises steeply at both band edges and a
    linear extension would understate it, which is the direction that flatters a
    budget. So a carrier outside the band gets a flagged gain estimate and no
    noise figure at all, and the budget says so rather than quoting one.

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
        self.gain_f = self._set_gain_response(self.f_datasheet,
                                              self.gain_datasheet)

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

    Source: component_references/CITCRYO1-12D_Technical_DataSheet_04.13.26.pdf,
    Cosmic Microwave Technology, Rev. 04/13/2026. Its 12 K noise and gain data
    is a plot rather than a table - the specification table only bounds noise
    at "< 5 K", which is the figure held flat here - and the SN216D s2p behind
    the gain curve is still not in the repo.
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

    Source: component_references/lnf-lnc1-5_6b.pdf, dated 2023-02-23.
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

    Source: component_references/lnf-lnc0-3_14b.pdf, dated 2023-02-24.
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


#: ZX60-83LN-S+ noise figure in dB at VDD = +6 V, from the swept typical
#: performance table. Kept as the datasheet quotes it; the class converts.
_ZX60_83LN_NF_DB = np.asarray(
    [1.57, 1.34, 1.28, 1.31, 1.35, 1.50, 1.54, 1.55, 1.54, 1.55, 1.57, 1.57,
     1.53, 1.87, 2.21])


@register("amplifier.zx60_83ln_s_plus", category="Amplifiers",
          label="Mini-Circuits ZX60-83LN-S+")
class ZX60_83LN_Splus(_InterpolatedLNA):
    """
    Room temperature low noise amplifier, 0.5-8 GHz, roughly 22 dB gain.

    Mini-Circuits ZX60-83LN-S+ on its +6 V supply, from the swept "Typical
    Performance Data" table rather than the four spot frequencies in the
    electrical specifications. Noise figure runs 1.28 dB at 1 GHz to 2.21 dB at
    8 GHz, which is 100-190 K equivalent - two orders of magnitude above the
    cold parts here, and the reason the stage this sits behind decides what a
    chain's noise figure actually is.

    The datasheet also tabulates +5 V, where gain drops about 0.8 dB across the
    band and noise figure is within 0.03 dB of these numbers. Only +6 V is
    modelled, being the bias its specifications are headlined at; there is no
    supply parameter to choose the other with.

    Output P1dB (+18 to +21.7 dBm), IP3 (+28.5 to +38.9 dBm) and return loss
    are on the datasheet and not here, nothing in this model representing
    compression, intermodulation or matching.

    Source: component_references/ZX60-83LN-S+.pdf, REV. C / ECO-015740.
    """

    gain_response = (
        1e6 * np.asarray([500, 750, 1000, 1500, 2000, 2500, 3000, 3500, 4000,
                          4500, 5000, 5500, 6000, 7000, 8000]),
        np.asarray([22.16, 22.58, 22.61, 22.52, 22.40, 22.22, 21.94, 21.91,
                    21.78, 21.60, 21.43, 21.37, 21.25, 20.58, 18.94]),
    )
    # Same 15 frequencies as the gain: the table sweeps both together, so the
    # noise curve spans the gain curve exactly and nothing is extended here.
    noise_response = (
        1e6 * np.asarray([500, 750, 1000, 1500, 2000, 2500, 3000, 3500, 4000,
                          4500, 5000, 5500, 6000, 7000, 8000]),
        290.0 * (10 ** (_ZX60_83LN_NF_DB / 10) - 1),
    )


#: ZX60-14LN-S+ noise figure in dB at VDD = +6 V, from the swept typical
#: performance table. Kept as the datasheet quotes it; the class converts.
_ZX60_14LN_NF_DB = np.asarray(
    [1.81, 1.03, 1.07, 1.31, 1.22, 1.40, 1.40, 1.52, 1.71, 1.90, 2.20, 2.92,
     3.62])


@register("amplifier.zx60_14ln_s_plus", category="Amplifiers",
          label="Mini-Circuits ZX60-14LN-S+")
class ZX60_14LN_Splus(_InterpolatedLNA):
    """
    Room temperature low noise amplifier, 0.05-10 GHz, roughly 22 dB gain.

    Mini-Circuits ZX60-14LN-S+ on its single +6 V supply, from the swept
    "Typical Performance Data" table. Flat is the point of this part: 22.5 dB
    at 500 MHz to 21.4 dB at 7 GHz, within a dB across seven octaves, before
    it falls away to 18.2 dB at 10 GHz. Noise figure is 1.03 dB at 500 MHz and
    under 2 dB to 7 GHz - 75 to 170 K equivalent - rising steeply past that to
    3.62 dB at 10 GHz, which is 360 K.

    Both ends of the band cost more than the headline suggests, and in
    different ways. The 50 MHz point carries the worst noise figure below
    8 GHz, 1.81 dB against 1.03 half a decade up, so the bottom of the band is
    noisy while its gain is not. The top is the reverse and steeper: 8 to
    10 GHz drops 2.4 dB of gain and adds 1.4 dB of noise figure together.

    The swept table is used rather than the eight spot frequencies in the
    electrical specifications, which agree with it to 0.02 dB wherever the two
    share a frequency. The tabulated band, 50 MHz to 10 GHz, is the part's full
    specified range, so nothing here is narrower than the datasheet.

    Output P1dB (+15.9 to +22.9 dBm), OIP3 (+30.8 to +33.5 dBm), VSWR and the
    0.6 W dissipation are on the datasheet and not here; nothing in this model
    represents compression, intermodulation or matching.

    Source: component_references/ZX60-14LN-S+.pdf, REV. OR, ECO-016347.
    """

    gain_response = (
        1e6 * np.asarray([50, 500, 1000, 1600, 2000, 3000, 4000, 5000, 6000,
                          7000, 8000, 9000, 10000]),
        np.asarray([21.99, 22.49, 22.41, 22.25, 22.19, 22.06, 21.92, 21.79,
                    21.61, 21.35, 20.62, 19.53, 18.21]),
    )
    # Same 13 frequencies as the gain: the table sweeps both together, so the
    # noise curve spans the gain curve exactly and nothing is extended here.
    noise_response = (
        1e6 * np.asarray([50, 500, 1000, 1600, 2000, 3000, 4000, 5000, 6000,
                          7000, 8000, 9000, 10000]),
        290.0 * (10 ** (_ZX60_14LN_NF_DB / 10) - 1),
    )


#: ZX60-153LN-S+ noise figure in dB at VDD = +12 V, from the swept typical
#: performance table. Kept as the datasheet quotes it; the class converts.
#: The specification table's 15 GHz figure is deliberately not appended - see
#: the class docstring.
_ZX60_153LN_NF_DB = np.asarray(
    [2.29, 2.21, 2.29, 2.23, 2.26, 2.41, 2.50, 2.49, 2.50, 2.49, 2.42, 2.72,
     3.10])


@register("amplifier.zx60_153ln_s_plus", category="Amplifiers",
          label="Mini-Circuits ZX60-153LN-S+")
class ZX60_153LN_Splus(_InterpolatedLNA):
    """
    Room temperature low noise amplifier, 0.5-15 GHz, roughly 17 dB gain.

    Mini-Circuits ZX60-153LN-S+ on its +12 V supply. Half again the bandwidth
    of the ZX60-14LN-S+ and reaching 15 GHz, paid for at both ends of the
    ledger: 5 dB less gain, 19.2 dB at 600 MHz sloping to 14.6 dB at 14 GHz,
    and a noise figure around 2.3-2.5 dB where the 14LN holds 1.0-1.9 over the
    band they share. In noise temperature that is roughly 200-225 K against
    75-160 K, so on the same chain this part costs about 100 K at the front.
    What it buys is the 12-15 GHz decade the other one does not have.

    Noise is unusually flat for a wideband MMIC - 2.21 dB at 500 MHz, 2.50 at
    6 GHz, still 2.42 at 10 GHz - and only turns up in the last two rows, 2.72
    at 12 GHz and 3.10 at 14 GHz. There is no quiet middle to aim a chain at
    the way there is with the cryogenic parts here.

    Two things about the span. The swept table starts at 200 MHz, below the
    0.5 GHz the part is specified from, and that point is kept: it is measured
    data, and ``defined_span_hz`` reports the range the curve is tabulated
    over, not the range the vendor warrants. Read 200-500 MHz as real
    measurement outside a specification rather than as an extrapolation.

    At the other end the model stops at 14 GHz where the swept table does,
    one GHz short of the band the part is sold over, and that shortfall is
    deliberate. The specification table does give 15 GHz typicals - 14.9 dB
    gain, 3.6 dB noise figure - and joining them on would cover the full band,
    the way the LNC0.3_14B carries an estimated 0.3 GHz noise point rather than
    narrow a part whose name is its band. The difference is which way the added
    point errs. That one continues a measured slope and errs pessimistic; this
    one would not. 14.9 dB at 15 GHz sits *above* the swept table's 14.63 dB at
    14 GHz - not because the part recovers there but because the two tables
    disagree by 0.3 dB, inside their mutual scatter - so joining them reverses
    the sign of the band-edge slope. Since an extrapolation extends that slope,
    the model would then climb with frequency past 15 GHz instead of rolling
    off, reaching its gain ceiling somewhere out where the real part is long
    finished. An out-of-band estimate that is too generous is the one kind this
    library will not carry, so the 15 GHz points stay on the datasheet. A chain
    that needs the top of this part's band wants its own measurement.

    Output P1dB (+14.4 to +17.6 dBm), OIP3 (+27.1 to +32.8 dBm), the input VSWR
    that reaches 4.4:1 at 15 GHz, and the directivity column are on the
    datasheet and not here.

    Source: component_references/ZX60-153LN-S+.pdf, REV. D, ECO-016183.
    """

    gain_response = (
        1e6 * np.asarray([200, 500, 600, 1000, 2000, 3000, 4000, 5000, 6000,
                          8000, 10000, 12000, 14000]),
        np.asarray([18.39, 19.12, 19.16, 19.09, 18.70, 18.07, 17.40, 16.92,
                    16.68, 16.28, 16.28, 16.18, 14.63]),
    )
    # Same 13 frequencies as the gain: the table sweeps both together, so the
    # noise curve spans the gain curve exactly and nothing is extended here.
    noise_response = (
        1e6 * np.asarray([200, 500, 600, 1000, 2000, 3000, 4000, 5000, 6000,
                          8000, 10000, 12000, 14000]),
        290.0 * (10 ** (_ZX60_153LN_NF_DB / 10) - 1),
    )


class _InterpolatedFilter(_DatasheetSpan, PassiveComponent):
    """
    Shared implementation for the fixed filter models, high- and low-pass alike.

    Also serves any other fixed passive whose whole model is one tabulated
    insertion loss with no parameters - the LNF circulator at the end of this
    file - since the clamp below is a statement about passive loss rather than
    about filtering. The name is the majority case, not the contract.

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
        # The ceiling is 0 dB here rather than the least loss measured, and
        # there is a floor as well, so this keeps its own clamp instead of
        # _DatasheetGain's: a passive filter cannot amplify, and a linear
        # extension run far into a stopband would otherwise claim absurd
        # rejection. Both bounds are inert inside the tabulated span.
        self.gain_f, _ceiling, self._span_hz = _datasheet_curve(freqs, gains)
        self.gain_floor_db = float(gains.min())

    def gain(self, carrier_frequency):
        return np.clip(self.gain_f(carrier_frequency), self.gain_floor_db, 0.0)


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

    Source: component_references/VHF-5050+.pdf, REV. B.
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

    Source: component_references/VLF-6700+.pdf.
    """

    response = (
        np.asarray([50, 500, 1000, 3500, 5000, 6700, 7600, 8000, 9000, 10000,
                    12000, 15000, 17000, 18000, 19890]) * 1e6,
        np.asarray([-0.03, -0.08, -0.15, -0.25, -0.47, -0.79, -3.12, -7.62,
                    -26.00, -55.95, -34.91, -26.32, -23.79, -21.88, -22.46]),
    )


@register("filter.vlfg2000p", category="Filters", label="Mini-Circuits VLFG-2000+")
class FilterLP_VLFG2000p(_InterpolatedFilter):
    """
    Mini-Circuits low-pass filter VLFG-2000+

    Passband DC-2000 MHz at 1.1 dB typical, 3 dB cutoff 2350 MHz nominal,
    unibody SMA, 5.5 W at 25C. Points are the dashboard's temperature-resolved
    "Typical Performance Data" table, +25C column, which spans 10 MHz to
    13.5 GHz; outside that the response is extrapolated. As with VLF-6700+ the
    passband does extend to DC, and the 10-100 MHz slope is nearly flat, so
    extending it there is a fair estimate - but no point below 10 MHz is
    published.

    The +25C column is the only one carried. The part is sold as temperature
    stable and over -55C to +125C it is, but not to the tenth of a dB the table
    prints: the passband loss at 2 GHz runs 0.73 dB cold and 1.15 dB hot around
    the 0.92 dB used here, and the skirt moves with it. A chain that needs the
    hot or cold column needs a temperature parameter this model does not have.

    Two documents are bundled in the dashboard PDF and they disagree in the deep
    stopband. The REV. A spec sheet's own sparser table reads 54.29 dB at 5 GHz
    and 44.25 dB at 7.5 GHz where the REV. OR table used here reads 73.67 and
    52.57; the two agree to about a dB from 9 GHz up and through the skirt. The
    denser table is taken as it stands rather than reconciled - the region they
    differ over is 44 dB down at worst, where nothing in a cascade turns on
    which one is right, and the disagreement is recorded rather than averaged
    away because a mean of two measurements of different units is neither.

    Source: component_references/VLFG-2000+_dashboard.pdf, performance data
    REV. OR, 210812; specifications REV. A, ECO-013807.
    """

    response = (
        np.asarray([10, 100, 200, 250, 300, 350, 400, 500, 550, 600,
                    650, 700, 750, 1000, 1500, 1800, 2000, 2100, 2200, 2350,
                    2400, 2500, 2600, 2660, 2700, 2760, 2800, 2850, 3000, 3100,
                    3200, 3300, 4000, 4500, 5000, 5400, 5500, 5600, 5700, 5800,
                    5900, 6000, 6100, 6200, 6300, 6400, 6500, 6600, 6700, 6800,
                    7000, 7500, 8500, 9000, 10000, 11000, 11500, 12000, 13000,
                    13500]) * 1e6,
        np.asarray([-0.10, -0.12, -0.16, -0.17, -0.19, -0.20, -0.22, -0.24,
                    -0.26, -0.27, -0.28, -0.30, -0.31, -0.38, -0.51, -0.68,
                    -0.92, -1.08, -1.29, -2.32, -3.30, -7.57, -14.88, -20.23,
                    -24.14, -30.69, -35.78, -43.52, -50.58, -51.00, -55.22,
                    -63.10, -64.23, -90.81, -73.67, -69.48, -68.59, -67.41,
                    -66.79, -66.99, -67.02, -66.28, -63.79, -62.55, -62.24,
                    -61.12, -60.43, -59.80, -58.61, -57.71, -54.97, -52.57,
                    -44.48, -41.61, -36.95, -33.27, -31.78, -31.25, -29.93,
                    -29.94]),
    )



#: Carrier grid the three t0 band-defining filters were swept on: 1 to 9 GHz
#: in 40 MHz steps, 201 points, identical across the three files.
_T0_BANDDEF_FREQ_HZ = np.linspace(1e9, 9e9, 201)

#: Measured S21 in dB for each filter, on _T0_BANDDEF_FREQ_HZ, rounded to
#: 0.01 dB from the twelve figures the instrument writes - a change of at most
#: 0.005 dB, and far below anything the measurement resolves. Row order is the
#: file's, so any value here is the corresponding line of the CSV.
_T0_NYQ1_S21_DB = np.asarray([
     -2.59, -1.80, -2.66, -1.77, -2.52, -1.78, -2.30, -1.84, -2.07,
     -1.89, -1.96, -1.95, -2.00, -2.05, -2.21, -2.34, -2.62, -2.85,
     -3.09, -3.42, -3.36, -3.58, -3.22, -3.17, -2.78, -2.71, -3.13,
     -3.58, -4.54, -5.11, -5.03, -4.91, -4.34, -7.20, -12.64, -16.90,
     -22.16, -24.52, -29.38, -30.94, -34.99, -36.68, -39.53, -41.88,
     -43.84, -46.05, -48.28, -49.51, -52.78, -53.03, -56.43, -56.46,
     -58.68, -59.61, -62.13, -63.63, -63.61, -68.23, -69.61, -68.85,
     -71.75, -72.38, -73.67, -72.08, -73.51, -84.39, -78.39, -75.01,
     -73.24, -92.14, -83.41, -82.21, -82.00, -70.77, -88.22, -84.42,
     -76.76, -91.98, -82.52, -82.38, -86.03, -83.03, -75.17, -80.06,
     -84.77, -72.67, -70.51, -74.03, -70.15, -68.45, -79.72, -72.03,
     -70.55, -70.35, -75.53, -73.56, -68.56, -71.67, -66.93, -69.75,
     -65.72, -65.86, -67.00, -64.22, -65.85, -68.35, -70.09, -67.21,
     -66.80, -66.03, -63.87, -63.79, -64.09, -64.26, -63.22, -63.64,
     -63.26, -62.62, -70.07, -69.37, -72.26, -70.92, -70.54, -71.71,
     -81.77, -73.37, -70.46, -72.36, -74.42, -71.38, -78.58, -74.90,
     -73.99, -72.40, -87.72, -62.96, -79.21, -64.00, -78.91, -71.58,
     -98.03, -69.48, -75.89, -67.21, -85.18, -70.76, -89.96, -72.53,
     -84.76, -81.48, -76.97, -73.20, -68.54, -60.17, -65.20, -65.26,
     -65.20, -84.11, -68.25, -60.58, -67.87, -71.63, -66.01, -66.13,
     -67.05, -68.27, -71.94, -78.66, -76.39, -88.92, -71.53, -75.77,
     -69.36, -81.78, -83.58, -75.74, -75.96, -87.21, -75.33, -79.76,
     -78.36, -81.78, -93.36, -88.21, -79.01, -75.39, -76.36, -74.34,
     -72.68, -73.13, -73.12, -71.12, -74.62, -70.74, -70.57, -69.54,
     -67.89, -69.52, -64.71, -66.60, -64.49])

_T0_NYQ2_S21_DB = np.asarray([
     -76.98, -85.66, -86.31, -91.85, -85.60, -90.78, -88.57, -85.13,
     -79.53, -83.47, -87.43, -84.21, -81.63, -72.92, -78.65, -78.36,
     -82.12, -78.01, -83.08, -80.36, -81.55, -74.62, -78.68, -81.52,
     -75.98, -76.65, -74.95, -75.95, -72.77, -79.30, -81.28, -71.34,
     -70.64, -67.00, -64.53, -60.62, -54.64, -49.55, -42.47, -34.08,
     -23.59, -10.35, -7.49, -5.68, -5.17, -5.11, -4.70, -4.75, -4.98,
     -4.86, -4.66, -4.55, -5.18, -4.70, -4.84, -4.62, -4.75, -4.93,
     -4.85, -4.71, -4.80, -4.77, -5.09, -4.84, -4.93, -5.16, -5.02,
     -5.37, -5.12, -5.15, -5.20, -5.27, -5.40, -5.35, -5.46, -5.55,
     -5.58, -5.82, -5.84, -5.95, -6.07, -6.23, -6.45, -6.71, -7.01,
     -7.48, -8.30, -9.47, -11.97, -19.30, -30.38, -38.37, -47.23,
     -53.04, -60.04, -64.96, -65.62, -67.36, -65.19, -69.05, -68.31,
     -66.01, -68.91, -63.64, -64.02, -62.55, -64.13, -60.89, -62.45,
     -62.36, -61.74, -65.05, -63.76, -64.12, -65.00, -65.87, -69.23,
     -64.16, -64.99, -63.64, -64.47, -66.07, -65.25, -66.84, -72.83,
     -73.61, -70.68, -70.87, -73.77, -87.76, -82.13, -69.75, -74.95,
     -66.17, -75.31, -65.48, -68.17, -62.82, -64.68, -64.69, -73.74,
     -62.12, -70.62, -67.74, -66.01, -74.75, -66.38, -68.70, -64.69,
     -65.20, -65.21, -64.75, -66.44, -64.29, -70.63, -70.97, -55.12,
     -59.93, -54.90, -59.89, -52.83, -51.81, -49.11, -45.54, -44.62,
     -48.34, -52.30, -57.76, -58.23, -62.14, -67.64, -70.11, -69.17,
     -53.00, -58.93, -58.35, -61.76, -63.13, -62.89, -66.83, -65.01,
     -64.00, -68.36, -65.47, -71.15, -67.56, -70.37, -70.30, -70.59,
     -71.76, -66.59, -61.78, -53.52, -49.21, -41.72, -39.00, -37.18,
     -40.57, -43.30, -44.63, -48.69])

_T0_NYQ3_S21_DB = np.asarray([
     -80.98, -81.21, -88.14, -82.42, -87.88, -79.64, -91.57, -82.91,
     -75.57, -82.33, -82.18, -76.18, -82.38, -80.46, -77.81, -82.73,
     -82.42, -75.66, -96.16, -71.07, -89.39, -97.37, -86.61, -76.27,
     -89.65, -80.54, -84.08, -77.99, -88.41, -83.81, -94.76, -95.49,
     -90.20, -94.06, -78.37, -81.79, -88.39, -84.64, -101.25, -81.30,
     -84.00, -86.82, -96.26, -84.72, -86.27, -80.78, -83.17, -85.02,
     -94.34, -85.22, -80.89, -79.56, -85.45, -84.63, -87.76, -85.13,
     -95.79, -92.45, -83.69, -81.79, -75.07, -78.33, -74.00, -75.67,
     -75.09, -71.15, -78.41, -69.84, -72.13, -69.35, -69.80, -69.47,
     -75.44, -67.66, -68.12, -68.44, -69.65, -66.01, -67.13, -67.00,
     -68.14, -67.12, -68.37, -68.72, -68.75, -70.32, -68.22, -67.10,
     -64.55, -63.37, -62.29, -59.55, -52.47, -43.26, -30.45, -30.71,
     -28.98, -21.56, -13.57, -12.35, -10.92, -8.77, -7.31, -8.14,
     -7.18, -6.57, -7.00, -6.71, -7.60, -6.48, -6.17, -6.45, -6.51,
     -7.37, -6.98, -6.92, -6.26, -5.90, -6.44, -6.53, -6.94, -7.02,
     -6.38, -6.45, -6.12, -6.47, -7.32, -7.38, -8.21, -7.53, -7.69,
     -6.77, -6.46, -6.42, -6.28, -6.83, -6.63, -6.78, -6.63, -6.38,
     -6.52, -6.61, -6.67, -7.22, -6.76, -7.29, -6.77, -7.04, -7.01,
     -7.20, -7.49, -7.64, -7.89, -7.96, -8.02, -8.88, -9.09, -11.83,
     -10.98, -13.34, -11.81, -15.70, -19.93, -24.05, -26.05, -26.80,
     -28.80, -37.96, -43.55, -51.36, -52.60, -57.78, -59.82, -59.71,
     -65.18, -65.64, -67.21, -69.91, -67.36, -74.57, -73.61, -84.36,
     -84.02, -78.32, -78.82, -79.32, -71.66, -76.53, -74.01, -72.49,
     -76.92, -77.97, -77.19, -78.57, -71.17, -70.99, -67.09, -67.73,
     -63.76, -62.12, -61.65])


class _T0BandDefiningFilter(_InterpolatedFilter):
    """
    Shared notes for the three t0 band-defining filters.

    These are the only models here built from a measurement of a specific unit
    rather than from a vendor's published typical, and they read differently
    because of it. What is tabulated is one trace off one filter on one day -
    the ``-a`` in each filename is the unit - so it carries that unit's ripple
    and that measurement's noise, where a datasheet curve would have had both
    averaged or idealised away. A second unit will not reproduce it point for
    point.

    Sweep: Siglent SHN914A, S21, 1 to 9 GHz in 40 MHz steps, 201 points,
    2026-09-12. The files also hold S21 phase, which nothing here models.

    Two limits of the measurement bound every one of these models, and both
    matter more than the numbers suggest:

    * **The stopband is the instrument's floor, not the filter's rejection.**
      Out of band these traces sit at -65 to -90 dB scattering by 15 dB between
      neighbouring points, with phase uniform over the full circle - which is
      what a VNA writes down when it is measuring its own dynamic range. Read
      any of it as "below -60 dB and not resolved", never as the specific
      figure tabulated. Nothing in a cascade turns on the difference, since a
      stage 60 dB down has already left the budget, but the numbers are not
      measurements of the part and should not be quoted as though they were.
    * **The sweep starts at 1 GHz**, which is inside the passband for the
      Nyquist 1 filter, so the bottom third of zone 1 is unswept. That one is a
      low pass and is flat to DC, which is asserted rather than measured; see
      that class.

    Outside the sweep these hold the edge value rather than extending the
    endpoint slope, which is the one place they depart from the vendor filters
    and is a consequence of the two limits above. A vendor table ends on an
    exact number partway down a real skirt, so its endpoint slope means
    something and extending it is an estimate. These traces end in noise at
    both ends, so the endpoint slope is whatever two neighbouring random points
    happened to do, and extending it produces confident nonsense: doing so has
    the Nyquist 2 model report 0 dB at DC - deep in its stopband, with the
    slope running up into the passband ceiling - and the Nyquist 1 model
    report -12 dB at 10 GHz, both the direction of error that flatters a
    budget.

    Holding the edge says the only thing a sweep supports about where it
    stopped: this is what the filter was doing when the measurement ended. It
    is still continuous at the band edge, still flagged as outside the measured
    span, and still bounded by the filter rule - but it is a weaker claim than
    the vendor models make there, deliberately. The 0 dB ceiling that suits a
    low pass tabulated from 50 MHz is actively wrong for a band pass whose
    region beyond the table is stopband, and rather than reason about which of
    these three is which, none of them guesses.
    """

    def gain(self, carrier_frequency):
        """Tabulated loss inside the sweep; the edge value held outside it."""
        low, high = self._span_hz
        held = np.clip(np.asarray(carrier_frequency, dtype=float), low, high)
        return super().gain(held)


@register("filter.t0_banddef_nyq1", category="Filters",
          label="t0 band-def. Nyquist 1")
class T0_BandDef_Nyquist1(_T0BandDefiningFilter):
    """
    t0 band-defining filter for Nyquist zone 1, DC-2.5 GHz at 5 GSa/s.

    A low pass in behaviour: flat at -2.1 dB mean from the bottom of the sweep
    to 1.6 GHz, 0.89 dB of ripple over that window, then rolling off through
    -3 dB at 2.28 GHz to -29 dB at the 2.5 GHz zone edge and -49 dB half a GHz
    past it. Of the three it has much the lowest insertion loss.

    The sweep starts at 1 GHz with the filter already passing at -2.6 dB, so
    the DC-to-1 GHz third of zone 1 is not in the file - but the part has no
    low cutoff to find there. It is a low pass, its passband is flat to DC, and
    the model holds -2.59 dB down to zero for that reason rather than because
    the base class had nothing better to hold. That is the one number here
    asserted from what the filter is rather than read off a trace, which is why
    it is written down: a later sweep starting near DC would confirm it rather
    than discover it.

    The held value carries the measurement's own uncertainty even so. -2.59 dB
    is the first swept point and it sits at the bottom of the mismatch ripple
    described below, where the neighbouring points run to -1.77 dB, so the flat
    region is better read as -2.1 dB with a few tenths either way. Holding the
    endpoint keeps the model continuous at the band edge, which is worth more
    than the tenth of a dB, but do not take the DC value as a measurement of
    the passband level.

    The first ten points are also worth knowing about before reading fine
    structure into the passband: -2.59, -1.80, -2.66, -1.77, -2.52, -1.78 and
    so on, alternating by most of a dB between neighbouring 40 MHz points and
    damping out by 1.4 GHz. A period of 80 MHz is a standing wave on about two
    metres of line, so that is a mismatch ripple in the measurement setup
    rather than anything the filter does, and it is the reason the endpoint
    slope here is meaningless.

    Everything above 2.5 GHz is stopband and is at the instrument floor; see
    the base class.

    Source: component_references/bpnyq1-a.csv.
    """

    response = (_T0_BANDDEF_FREQ_HZ, _T0_NYQ1_S21_DB)


@register("filter.t0_banddef_nyq2", category="Filters",
          label="t0 band-def. Nyquist 2")
class T0_BandDef_Nyquist2(_T0BandDefiningFilter):
    """
    t0 band-defining filter for Nyquist zone 2, 2.5-5 GHz at 5 GSa/s.

    A band pass sitting inside its zone rather than filling it: -3 dB corners
    at 2.68 and 4.40 GHz against zone edges at 2.5 and 5.0, so roughly 300 and
    600 MHz of the zone are given up at the two ends to get the skirts. Mean
    loss is -5.11 dB over the flat 2.8-4.2 GHz, with 1.53 dB of ripple - three
    dB more loss than the Nyquist 1 filter for the same job.

    Both skirts are steep and both are measured properly, unlike the Nyquist 1
    filter's low edge: -50 dB by 2.5 GHz going down, -49 dB by 5.0 GHz going
    up, so it rejects the neighbouring zones at the zone boundary itself.

    It is also the one with visible re-entrance. Above 8.4 GHz the response
    climbs back out of the noise floor to -37 dB at 8.84 GHz, 32 dB below its
    own passband and climbing at the top of the sweep. Where that goes past
    9 GHz is not measured, so a chain carrying real power near 9 GHz should not
    assume this filter still rejects it.

    Source: component_references/bpnyq2-a.csv.
    """

    response = (_T0_BANDDEF_FREQ_HZ, _T0_NYQ2_S21_DB)


@register("filter.t0_banddef_nyq3", category="Filters",
          label="t0 band-def. Nyquist 3")
class T0_BandDef_Nyquist3(_T0BandDefiningFilter):
    """
    t0 band-defining filter for Nyquist zone 3, 5-7.5 GHz at 5 GSa/s.

    A band pass with -3 dB corners at 5.04 and 7.20 GHz, which lines its lower
    edge up with the 5 GHz zone boundary almost exactly and leaves 300 MHz at
    the top. The most lossy and least flat of the three: -6.81 dB mean over
    5.2-7.0 GHz with 2.31 dB of ripple, against -5.11 and 0.89 for the zones
    below it. Insertion loss rising and flatness worsening with zone number is
    the pattern across this set, and for a chain it means the stage in front of
    the Nyquist 3 filter is doing more work than its counterpart in zone 1.

    Its lower skirt is the one place to be careful: at 4.92 GHz, just 80 MHz
    below the zone edge, it is still only 11 dB down, so it does not reject the
    top of zone 2 the way the zone 2 filter rejects the bottom of zone 3.

    Source: component_references/bpnyq3-a.csv.
    """

    response = (_T0_BANDDEF_FREQ_HZ, _T0_NYQ3_S21_DB)

class _TemperatureSwitchedCable(_DatasheetSpan, PassiveComponent):
    """
    Shared implementation for cryogenic cables that carry separate warm and cold
    datasheet curves and pick between them by physical temperature.

    Subclasses set ``frequencies_hz``, ``warm_db_per_m``, ``cold_db_per_m`` and
    ``transition_k``. The total loss is the per-metre curve scaled by length,
    matching the original per-class implementations.

    Both curves extrapolate, clamped to the least loss the datasheet measured so
    an extension cannot turn a length of coax into an amplifier. The tabulated
    span is reported through ``defined_span_hz`` and is the same for both
    curves: the two temperatures are columns of one table.

    That extension is not flagged, and this is the class the reasoning lives in
    for every cable here. Coax loss has no features: it is resistive loss going
    as sqrt(f) plus dielectric loss going as f, both monotonic, so past the last
    tabulated row there is nothing to be surprised by - unlike an amplifier's
    matching networks or a filter's re-entrant stopband, which is what flagging
    an extrapolation is for. Extending the endpoint slope of a table models the
    sqrt(f) term as if it grew like f, so the error is an overstatement of loss,
    smooth and in the direction that does not flatter a budget. What it does not
    cover is the mechanisms the loss curve never described in the first place: a
    braided outer conductor leaking as the weave approaches a wavelength, or a
    connector's own response. Those are reasons to distrust a cable well past
    its band, and no shaded lane was reporting them either.
    """

    frequencies_hz = None
    warm_db_per_m = None
    cold_db_per_m = None
    transition_k = 100
    flags_extrapolation = False

    def __init__(self, length_m, temperature=4, name=None):
        super().__init__(name=name, params={
            "length_m": length_m,
            "temperature": temperature,
        })
        self.length = length_m
        self.temperature = temperature

        freqs = np.asarray(self.frequencies_hz)
        self.warm_gain, self._warm_ceiling_db, self._span_hz = _datasheet_curve(
            freqs, np.asarray(self.warm_db_per_m) * self.length)
        self.cold_gain, self._cold_ceiling_db, _span = _datasheet_curve(
            freqs, np.asarray(self.cold_db_per_m) * self.length)

    def _curve(self):
        """The ``(curve, ceiling)`` pair this cable's temperature selects."""
        if self.temperature > self.transition_k:
            return self.warm_gain, self._warm_ceiling_db
        return self.cold_gain, self._cold_ceiling_db

    def gain(self, carrier_frequency):
        """Insertion loss in dB, using the warm curve above ``transition_k``."""
        # Which curve is a subclass's business; the clamp is not, so it lives
        # here and a cable that picks differently still cannot report gain.
        curve, ceiling = self._curve()
        return np.minimum(curve(carrier_frequency), ceiling)


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

    def _curve(self):
        # Preserves the original exact-match behaviour rather than a threshold;
        # the constructor above accepts no other temperature anyway.
        if self.temperature == 300:
            return self.warm_gain, self._warm_ceiling_db
        return self.cold_gain, self._cold_ceiling_db


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


class _RoomTemperatureCable(_DatasheetSpan, PassiveComponent):
    """
    Shared implementation for room-temperature cables with a single loss curve.

    ``db_per_m`` is per-metre loss in dB and must be negative; the total is
    scaled by length exactly once, in gain(). The curve extrapolates and is
    clamped exactly as :class:`_TemperatureSwitchedCable`'s is, and goes
    unflagged outside its span for the reason given there.
    """

    frequencies_hz = None
    db_per_m = None
    flags_extrapolation = False

    def __init__(self, length_m, name=None):
        super().__init__(name=name, params={"length_m": length_m})
        self.length = length_m

        (self.atten_per_m, self._ceiling_db_per_m,
         self._span_hz) = _datasheet_curve(self.frequencies_hz, self.db_per_m)

    def gain(self, carrier_frequency):
        """Total insertion loss in dB over ``self.length`` metres."""
        # Clamped per metre and then scaled: length only ever multiplies the
        # loss, so clamping before or after it is the same number for any
        # length >= 0, and the cap stays the datasheet figure it came from.
        return np.minimum(self.atten_per_m(carrier_frequency),
                          self._ceiling_db_per_m) * self.length


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


#: ZN4PD-4R722+ total loss in dB from the typical performance table, one column
#: per output arm - S-1, S-2, S-3, S-4 - against _ZN4PD_FREQ_HZ. Total Loss is
#: the datasheet's own quantity: "Insertion Loss + 6dB splitter loss", so each
#: figure is the whole loss from the input to that one output and needs no split
#: term added to it. Kept per arm rather than pre-averaged so the published
#: numbers stay checkable against the PDF.
_ZN4PD_FREQ_HZ = 1e6 * np.asarray(
    [400, 500, 600, 700, 1000, 2000, 3000, 4000, 5000, 6000, 7000, 7200])
_ZN4PD_TOTAL_LOSS_DB = np.asarray([
    [6.64, 6.59, 6.84, 6.63],
    [6.71, 6.67, 6.82, 6.70],
    [6.43, 6.36, 6.46, 6.41],
    [6.41, 6.34, 6.34, 6.40],
    [6.52, 6.47, 6.55, 6.51],
    [6.67, 6.61, 6.65, 6.65],
    [6.92, 6.89, 6.86, 6.90],
    [7.08, 7.06, 7.11, 7.03],
    [7.22, 7.22, 7.32, 7.17],
    [7.48, 7.53, 7.48, 7.42],
    [7.53, 7.59, 7.52, 7.48],
    [7.67, 7.68, 7.34, 7.61],
])


class _TotalLossSplitter(_DatasheetSpan, PassiveComponent):
    """
    Shared implementation for the splitter/combiner models.

    Subclasses set ``total_loss``, a ``(frequencies_Hz, loss_dB)`` pair holding
    the datasheet's own Total Loss - insertion loss with the 10*log10(N) of
    splitting already in it - so nothing needs adding for the split. Where the
    datasheet measures several arms, ``loss_dB`` is one column per arm and they
    are averaged; where it publishes one, it is a plain column.

    Every one of these is the loss along a single output arm and nothing else,
    which is all a linear cascade can represent: SignalChain is a chain, so
    there is nowhere to put the other N-1 ports. Read one as "the signal goes
    into this splitter and I follow one output".

    None of them contributes noise. The 10*log10(N) is power division rather
    than dissipation, so the split itself is not a lossy process in the
    thermodynamic sense, and no physical temperature is carried here to turn
    the excess insertion loss above it into a thermal contribution either.
    """

    #: (frequencies_Hz, loss_dB) datasheet Total Loss, set by each subclass.
    #: 2-D loss is one column per measured arm; 1-D is a single published arm.
    total_loss = None

    def __init__(self, name=None):
        super().__init__(name=name, params={})
        freqs, loss_db = self.total_loss
        loss = np.asarray(loss_db, dtype=float)
        # Averaged in dB, which is what "typical loss along an arm" means for
        # figures that spread by a tenth of a dB; converting to power to average
        # would move the result by far less than the unbalance it is
        # summarising. Negated because gain() reports loss as negative gain.
        if loss.ndim == 2:
            loss = loss.mean(axis=1)
        (self.loss_f, self._ceiling_db, self._span_hz) = _datasheet_curve(
            np.asarray(freqs, dtype=float), -loss)

    def gain(self, carrier_frequency):
        """Loss in dB from the input to one output, the split included."""
        return np.minimum(self.loss_f(carrier_frequency), self._ceiling_db)


@register("splitter.zn4pd_4r722_plus", category="Splitters",
          label="Mini-Circuits ZN4PD-4R722+ (one arm)")
class ZN4PD_4R722plus(_TotalLossSplitter):
    """
    Mini-Circuits ZN4PD-4R722+ 4-way 0 degree splitter/combiner, 400-7200 MHz.

    Modelled as the loss along one output arm and nothing else, which is the
    only thing a linear cascade can represent: SignalChain is a chain, so there
    is nowhere to put the other three ports. Read it as "the signal goes into
    this splitter and I follow one output", and read the loss as the datasheet's
    Total Loss - insertion loss with the 6 dB of splitting already in it, 6.4 dB
    at 700 MHz rising to 7.6 dB at 7.2 GHz. Nothing needs adding for the split.

    The four arms are averaged at each frequency. They are the four ports of one
    measured unit and differ by the amplitude unbalance, at most 0.36 dB and
    typically under 0.1, so no arm is the right one to privilege - a different
    unit would permute them. The mean is therefore an estimate of "an arm" and
    not a measurement of any particular one.

    What this cannot tell you, and what the part is usually chosen for: the
    amplitude and phase unbalance between arms, the 19-49 dB isolation between
    outputs, and the fact that a combiner sums four inputs rather than dividing
    one. A chain that cares about any of those is not a chain this model belongs
    in. Nor is the 30 W rating or the DC-pass path represented.

    Contributes no noise: the 6 dB is power division rather than dissipation, so
    the part is treated as non-lossy. Only the 0.4-1.6 dB of insertion loss
    above the split is absorbed at all, and no physical temperature is carried
    here to turn that into a thermal contribution.

    Source: component_references/ZN4PD-4R722+_dashboard.pdf, REV. OR,
    ECO-011123.
    """

    total_loss = (_ZN4PD_FREQ_HZ, _ZN4PD_TOTAL_LOSS_DB)


#: ZN8PD-02183+ Total Loss in dB, one column per measured output arm - S-1,
#: S-2, S-3, S-4, S-6, S-8 - against _ZN8PD_FREQ_HZ. Six of the eight arms are
#: what the datasheet publishes; ports 5 and 7 are not tabulated. Total Loss
#: here is insertion loss with the 9 dB of splitting already included.
_ZN8PD_FREQ_HZ = 1e6 * np.asarray(
    [2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000, 12000, 14000,
     15000, 16000, 17000, 18000])
_ZN8PD_TOTAL_LOSS_DB = np.asarray([
    [9.34, 9.34, 9.35, 9.34, 9.33, 9.33],
    [9.50, 9.51, 9.51, 9.51, 9.50, 9.49],
    [9.56, 9.57, 9.58, 9.58, 9.56, 9.56],
    [9.56, 9.57, 9.58, 9.59, 9.56, 9.58],
    [9.69, 9.70, 9.70, 9.69, 9.68, 9.68],
    [9.75, 9.76, 9.76, 9.75, 9.74, 9.74],
    [9.79, 9.80, 9.82, 9.79, 9.78, 9.77],
    [9.86, 9.85, 9.87, 9.86, 9.82, 9.81],
    [9.98, 9.93, 9.93, 9.92, 9.93, 9.90],
    [10.17, 10.11, 10.19, 10.13, 10.09, 10.05],
    [10.18, 10.14, 10.19, 10.15, 10.12, 10.09],
    [10.26, 10.21, 10.27, 10.28, 10.19, 10.17],
    [10.44, 10.34, 10.39, 10.38, 10.32, 10.26],
    [10.47, 10.38, 10.46, 10.42, 10.33, 10.25],
    [10.72, 10.55, 10.70, 10.62, 10.53, 10.40],
])


@register("splitter.zn8pd_02183_plus", category="Splitters",
          label="Mini-Circuits ZN8PD-02183+ (one arm)")
class ZN8PD_02183plus(_TotalLossSplitter):
    """
    Mini-Circuits ZN8PD-02183+ 8-way 0 degree splitter/combiner, 2-18 GHz.

    Reactive, not resistive. The 9 dB the datasheet calls "splitter loss" is
    10*log10(8), the ideal reactive figure; a resistive 8-way star would divide
    at 20*log10(8) = 18 dB, and the measured Total Loss starts at 9.34 dB. The
    20 dB isolation between outputs says the same thing from the other side -
    a resistive star gives no isolation to speak of, and getting 20 dB takes
    the isolation resistors of a Wilkinson - as does the separate 0.5 W
    "Internal Dissipation" rating beside a 20 W input rating, which is what
    those resistors are allowed to absorb. So the loss modelled here is
    conductor and dielectric loss in a three-stage corporate network, not power
    burned in a divider.

    The loss is the datasheet's Total Loss, the 9 dB split already in it,
    averaged across the six arms it tabulates. That is 9.34 dB at 2 GHz rising
    to 10.6 dB at 18 GHz - so 0.3 to 1.6 dB of real insertion loss above the
    split, against the 1.4 dB typical and 2.4 dB max its specification table
    quotes over the whole band.

    Six of the eight arms are published, S-1 through S-4 plus S-6 and S-8, and
    they are averaged for the reason the ZN4PD's four are: they are arms of one
    measured unit differing by the amplitude unbalance, here 0.00 to 0.17 dB,
    so no arm is the right one to privilege. Ports 5 and 7 are not tabulated at
    all, which is a gap in the datasheet rather than in this model.

    Not represented, and on the datasheet: the 16-20 dB isolation between
    outputs, the 0.3 dB amplitude and 5 degree phase unbalance, the fact that a
    combiner sums eight inputs rather than dividing one, the 20 W splitter
    rating and the 1.2 A DC-pass path.

    Source: component_references/ZN8PD-02183+.pdf, REV. OR, M163108.
    """

    total_loss = (_ZN8PD_FREQ_HZ, _ZN8PD_TOTAL_LOSS_DB)


#: ZC16PD-02183-S+ Total Loss in dB against _ZC16PD_FREQ_HZ. One column, S-1:
#: unlike the other two splitters here the datasheet tabulates a single arm.
#: Total Loss is insertion loss with the 12 dB of splitting already included.
_ZC16PD_FREQ_HZ = 1e6 * np.asarray(
    [2000, 3000, 4000, 5000, 6000, 7000, 8000, 10000, 12000, 14000, 16000,
     18000])
_ZC16PD_TOTAL_LOSS_DB = np.asarray(
    [12.78, 13.00, 13.23, 13.40, 13.56, 13.75, 14.01, 14.30, 14.64, 14.95,
     15.35, 15.72])


@register("splitter.zc16pd_02183_s_plus", category="Splitters",
          label="Mini-Circuits ZC16PD-02183-S+ (one arm)")
class ZC16PD_02183_Splus(_TotalLossSplitter):
    """
    Mini-Circuits ZC16PD-02183-S+ 16-way 0 degree splitter/combiner, 2-18 GHz.

    Reactive, not resistive, on the same evidence as the ZN8PD. Its 12 dB of
    "splitter loss" is 10*log10(16), the ideal reactive figure, where a
    resistive 16-way star would cost 20*log10(16) = 24 dB; measured Total Loss
    starts at 12.78 dB. Isolation runs 24-37 dB, which needs isolation
    resistors, and the ratings make those resistors explicit: 20 W in as a
    splitter but 1.6 W of internal dissipation and only 1.6 W as a combiner.
    That asymmetry is the Wilkinson signature - uncorrelated inputs to a
    combiner land in the isolation resistors rather than in the sum port.

    The loss is the datasheet's Total Loss, the 12 dB split already in it, 12.78
    dB at 2 GHz rising to 15.72 dB at 18 GHz. That is 0.74 to 3.68 dB of
    insertion loss above the split, and the frequency dependence is worth
    reading before budgeting from the headline: the specification table quotes
    1.4 dB typical over 2-8 GHz and 2.9 dB over 8-18 GHz, two figures for a
    quantity that moves by a factor of five across the band.

    Against the ZN8PD this part is the more lossy per arm in both terms - 3 dB
    more of split, and about 2.4 times the excess loss above it at every
    frequency the two share, from four stages of combining rather than three in
    a longer package. A chain that needs only eight ways should not reach for
    this one.

    One arm is all the datasheet tabulates, S-1, so unlike the other two
    splitters here nothing is averaged and this is a measurement of one port of
    one unit. The amplitude unbalance it quotes, 0.06 to 0.24 dB, is the scale
    on which the other fifteen differ from it.

    Not represented, and on the datasheet: the 24-37 dB isolation, the
    amplitude and phase unbalance, combining rather than splitting, the 20 W
    rating and the 510 mA DC-pass path.

    Source: component_references/ZC16PD-02183-S+.pdf, REV. OR, ECO-004360.
    """

    total_loss = (_ZC16PD_FREQ_HZ, _ZC16PD_TOTAL_LOSS_DB)


class _FormulaCable(_DatasheetSpan, PassiveComponent):
    """
    Shared implementation for cables whose datasheet gives a loss formula.

    Subclasses set ``atten_a``, ``atten_b`` and ``datasheet_fmax_ghz``, for

        attenuation = atten_a * sqrt(f_GHz) + atten_b * f_GHz    [dB/m]

    which is not a curve fit but the two loss mechanisms written down. The
    sqrt term is resistive loss in the conductors, going as sqrt(f) because
    skin depth does; the linear term is dielectric loss, going as f because the
    loss tangent is roughly constant over these bands. Cable vendors publish the
    pair of coefficients precisely because the form holds.

    This is the reason to evaluate a formula rather than tabulate its output.
    Extending a table's endpoint slope past the last row models resistive loss
    as if it grew like f, which overstates it and increasingly so with distance
    from the band; the formula keeps each term's exponent wherever it is
    evaluated, so the only thing out of warranty above the datasheet's range is
    the calibration of two coefficients. ``defined_span_hz`` still reports the
    range the vendor validates - a spec panel draws that band and says so - but
    a sweep past it is not flagged per stage, as for the tabulated cables and
    for the same reason (see :class:`_TemperatureSwitchedCable`), which this
    form only strengthens.

    No clamp, unlike the tabulated cables. Their extrapolation needs one because
    a linear extension toward DC runs a loss curve up through zero and out the
    other side into gain; here loss is monotonic in f and zero at DC by
    construction, so for non-negative coefficients no frequency can produce
    gain and there is nothing to bound.
    """

    #: dB/m at 1 GHz from conductor loss, the sqrt(f) term.
    atten_a = None
    #: dB/m per GHz from dielectric loss, the linear term.
    atten_b = None
    #: Highest frequency the vendor quotes the coefficients for, in GHz.
    datasheet_fmax_ghz = None
    flags_extrapolation = False

    def __init__(self, length_m, name=None):
        super().__init__(name=name, params={"length_m": length_m})
        self.length = length_m
        self._span_hz = (0.0, float(self.datasheet_fmax_ghz) * 1e9)

    def atten_db_per_m(self, carrier_frequency):
        """Attenuation in dB/m, positive, at ``carrier_frequency`` in Hz."""
        f_ghz = np.asarray(carrier_frequency, dtype=float) / 1e9
        return self.atten_a * np.sqrt(f_ghz) + self.atten_b * f_ghz

    def gain(self, carrier_frequency):
        """Total insertion loss in dB over ``self.length`` metres."""
        return -self.atten_db_per_m(carrier_frequency) * self.length


@register("cable.rg316", category="Cables", label="RG316/U (room temp)",
          params=(LENGTH_PARAM,))
class SMA_RG316_cables(_FormulaCable):
    """
    HUBER+SUHNER RG316/U, 50 ohm, silver-plated braid, 2.5 mm FEP jacket.

    The coefficients are the datasheet's own, printed above its attenuation
    table under the heading it gives them for - ``a*f^0.5 + b*f`` - so the loss
    here is not a fit of the table but the thing the table was generated from.
    Evaluating it reproduces every published row: 0.31 dB/m at 150 MHz, 0.89 at
    1.05 GHz, 1.63 at 3 GHz.

    Validated to 3 GHz, which is the operating frequency on the front page and
    the ``fmax`` beside the coefficients, and that band is what the spec panel
    draws. Above it the formula is still a well-founded estimate - both terms
    keep their physical meaning at higher frequency - but the coefficients were
    only ever checked below 3 GHz, and a braided outer conductor starts to leak
    as the weave approaches a wavelength, which this form does not describe at
    all. Screening is only specified to 1 GHz. Worth knowing before trusting
    this model at 10 GHz; not something a chain sweep flags, since a cable's
    loss curve has no out-of-band features to warn about.

    Not modelled: the 135 W CW rating at 1 GHz falling as 1/sqrt(f), the -65 to
    +200 C range, 1.5 kVrms operating voltage, or the 4.86 ns/m delay. This is
    loss against frequency and nothing else.

    Source: component_references/RG316-SMAcable-HUBERSUHNERRG316UDataSheet.pdf,
    DOC-0000177782, published 2020-10-14.
    """

    atten_a = 0.7727
    atten_b = 0.0972
    datasheet_fmax_ghz = 3.0


@register("circulator.lnf_c4_12a", category="Circulators",
          label="LNF-xxxxC4_12A (4-12 GHz cryo)")
class LNF_C4_12A(_InterpolatedFilter):
    """
    Low Noise Factory LNF-xxxxC4_12A, 4-12 GHz cryogenic dual junction
    isolator/circulator, modelled as its insertion loss and nothing else.

    One model covers the whole family. The ``xxxx`` is the order code -
    ISIS, CICI, ISCI or CIIS, for dual isolator, dual circulator and the two
    mixed pairs - and the four share this datasheet, one chassis and one
    insertion-loss chart, so there is nothing here to tell them apart by.

    Insertion loss only, by intent. Absent, and on the datasheet if you need
    them: the 30 dB isolation and the direction it runs in, the 16 dB port
    match, the third port, the internal magnet's stray field (<4 Gauss at 6 mm,
    <0.1 with the optional shield) and the 650/1500 Gauss external field the
    part tolerates before its band edge shifts, the 30 dBm drive limit and the
    +-50 V DC rating. Most of that is unrepresentable rather than merely
    omitted: a SignalChain is a linear one-way cascade, so there is nowhere in
    it to put the non-reciprocity that is the entire reason to fit one of
    these. This model says what the signal loses going the way it is meant to.

    The numbers are the datasheet's "Insertion Loss of 5 Units at 77 K" chart,
    which is drawn as vector art rather than as an image, so its five polylines
    are the plotted samples themselves - 201 points each, 3 to 13 GHz in 50 MHz
    steps - recovered from the page rather than read off it by eye. The plot
    frame supplies the calibration, 3 and 13 GHz at its left and right edges
    and 0.0 and -2.0 dB at its top and bottom, each checked against where the
    printed tick label sits. The five units are then averaged at each
    frequency, in dB as with the splitter arms. Averaging in power instead
    moves nothing through the band by 0.01 dB - but the two do diverge in the
    roll-off, by 3 dB at 12.95 GHz, which is the arithmetic noticing what the
    spread below says outright: past 12.2 GHz there is no typical unit to
    average towards, and a mean of five parts that have stopped agreeing is
    not a measurement of anything.

    That average comes to 0.38 dB over 4-12 GHz against the specification
    table's "0.4 dB typical", which is the cross-check that the chart was read
    correctly - and also the last point at which the headline figure describes
    the part. The loss is 0.9 dB at the 4 GHz corner, falls to 0.18 dB at
    7 GHz, and is back to 0.4 dB by 12 GHz; a chain that puts this at the
    bottom of its band pays more than twice what the front page quotes.

    Unit to unit the five agree to about 0.15 dB through the band, which is the
    other reason to average them. They stop agreeing above roughly 12.2 GHz,
    where their band edges part company: at 12.5 GHz they span 0.57 to 2.73 dB.
    The mean is carried there for continuity into the roll-off but it describes
    no particular unit, and a chain working the top 300 MHz of this band wants
    a measurement of its own device rather than this curve.

    The table runs out to 3 and 13 GHz, past the specified band at both ends,
    because the chart's samples do - they are plotted below its -2 dB axis
    floor, clipped out of the picture but present in the drawing, so the two
    roll-offs come out with the rest and the model reaches its band edges with
    a measured skirt instead of an extrapolated one.

    Measured at 77 K, and modelled there. The datasheet says only that
    insertion loss "improves slightly when cooled to 5 K and 10 mK" without
    quantifying it, so a chain at millikelvin gets the pessimistic end of the
    part's range; there is no temperature parameter here to say otherwise.

    Contributes no noise, in common with every passive here but ``Attenuator``:
    nothing turns this loss into the thermal contribution it physically makes.
    That gap is worth more here than in a warm filter, since the part exists to
    sit at the cold stage immediately around an LNA, where a few tenths of a dB
    is being spent precisely because it is cheap in noise temperature there -
    and this model prices the loss while ignoring what it buys.

    Source: component_references/lnf-xxxxc4_12a.pdf, dated 2022-05-02.
    """

    response = (
        1e9 * np.asarray(
            [3.0, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9,
             4.0, 4.25, 4.5, 4.75, 5.0, 5.25, 5.5, 5.75, 6.0, 6.25,
             6.5, 6.75, 7.0, 7.25, 7.5, 7.75, 8.0, 8.25, 8.5, 8.75,
             9.0, 9.25, 9.5, 9.75, 10.0, 10.25, 10.5, 10.75, 11.0, 11.25,
             11.5, 11.75, 12.0, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7,
             12.8, 12.9, 13.0]),
        np.asarray(
            [-18.56, -14.94, -10.83, -7.20, -4.56, -2.87, -1.95, -1.46, -1.17,
             -1.02, -0.93, -0.85, -0.72, -0.52, -0.37, -0.40, -0.55, -0.69,
             -0.68, -0.55, -0.36, -0.23, -0.18, -0.22, -0.24, -0.29, -0.27,
             -0.22, -0.20, -0.26, -0.28, -0.31, -0.35, -0.40, -0.35, -0.34,
             -0.32, -0.27, -0.26, -0.27, -0.31, -0.37, -0.39, -0.42, -0.51,
             -0.69, -0.98, -1.46, -2.10, -2.98, -5.76, -11.54, -17.67]),
    )


@register("cable.rg223", category="Cables", label="RG223/U (room temp)",
          params=(LENGTH_PARAM,))
class SMA_RG223_cables(_FormulaCable):
    """
    McGill Microwave RG223, 50 ohm, double silver-plated copper braid, PE
    dielectric, 5.40 mm PVC jacket, 66% velocity of propagation.

    The coefficients are fitted here rather than published. Unlike the RG316
    this datasheet prints no loss formula, only eight attenuation rows from
    50 MHz to 3 GHz, and the band of interest runs well past the last of them -
    so the two-term form is fitted to the table and evaluated above it, which
    keeps each loss mechanism's exponent wherever it lands instead of running a
    table's endpoint slope out into a region where it means nothing. At 10 GHz
    that is the difference between 1.69 dB/m and the 2.14 dB/m extending the
    2-3 GHz slope would claim, and the gap widens with every GHz past it.

    Read the fit as an estimate with a real error bar, because the table it
    comes from is not self-consistent. Coax loss cannot grow more slowly than
    sqrt(f) - that is conductor loss, and dielectric loss only steepens it -
    and three of the seven intervals in this table do exactly that: 14 to
    16 dB/100m from 50 to 100 MHz where sqrt alone demands 19.8, 16 to 28
    across 100-400 MHz where it demands 32, and 37 to 44 across 500-900 where
    it demands 49.6. Around a pure sqrt law anchored at 3 GHz the rows scatter
    by -13% to +23%. This is a compiled or rounded table, not a measurement
    series, and no choice of a and b can fit it.

    What that costs: fitting all eight rows in absolute terms, as here, gives
    1.69 dB/m at 10 GHz, while fitting only the 900 MHz-3 GHz rows - the part
    that does obey the sqrt floor - gives 1.87. Treat anything above 3 GHz as
    carrying 10-15% on top of whatever the fit says. Absolute least squares is
    used deliberately rather than relative: it weights the large
    high-frequency rows, which are both the self-consistent ones and the ones
    that set the extrapolation. Fitting in log space instead lets the bad
    50 MHz row pull the dielectric term negative, which would have loss turn
    over and fall at high frequency.

    The fit reproduces the rows that matter - 60.2 dB/100m at 1500 MHz against
    59, 70.1 at 2000 against 70, 87.0 at 3000 against 88 - and understates the
    50 MHz row, 10.5 against 14, which is the row that cannot be right.

    Validated to 3 GHz, the top of the table, so that is what ``defined_span_hz``
    reports and a sweep past it is flagged as an estimate like any other. The
    datasheet's own 12.4 GHz "Max Frequency" is a different claim - the usable
    limit of the cable, not a range over which its loss was characterised.

    Not modelled: the 1400 V rating, the -20/+85 C range, the 100 pF/m
    capacitance or the 66% velocity factor and the delay it implies. This is
    loss against frequency and nothing else.

    Source: component_references/rg223-data-sheet.pdf, McGill Microwave
    Systems Ltd, part RG223 (undated).
    """

    # Least squares on all eight published rows, in dB/m against GHz; see the
    # docstring for why absolute rather than relative, and for the error bar.
    atten_a = 0.4647
    atten_b = 0.0218
    datasheet_fmax_ghz = 3.0
