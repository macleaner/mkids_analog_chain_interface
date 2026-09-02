"""
The uniform noise interface: every component takes
``noise(carrier_frequency, spectral_frequency)``.

The carrier sets the level, the spectral frequency the shape. A source that is
white near the carrier returns a flat spectrum at its carrier-determined level;
a source with spectral structure returns that shape, shifted by whatever the
carrier implies.
"""

import inspect
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import registry  # noqa: E402
from component import flat_in_spectral  # noqa: E402
from conftest import CARRIER_FREQS, SPECTRAL_FREQS  # noqa: E402
from utils import kb  # noqa: E402


def _make(type_id):
    entry = registry.resolve(type_id)
    return registry.create(type_id, {s.name: s.default for s in entry.params})


@pytest.mark.parametrize("type_id", [e.type_id for e in registry.entries()])
def test_every_component_takes_both_frequencies(type_id):
    """The whole point: one calling convention for every source."""
    component = _make(type_id)
    signature = inspect.signature(type(component).noise)
    assert list(signature.parameters)[1:3] == [
        "carrier_frequency", "spectral_frequency"], (
        f"{type_id} does not take (carrier_frequency, spectral_frequency)")
    # And it is actually callable that way.
    assert component.noise(1.5e9, 1e3) is not None


@pytest.mark.parametrize("type_id", [e.type_id for e in registry.entries()])
def test_noise_shape_follows_the_swept_axis(type_id):
    """Sweeping either axis yields a result shaped like that axis."""
    component = _make(type_id)
    spectral = np.logspace(0, 5, 7)
    assert np.shape(component.noise(1.5e9, spectral)) in ((), (7,))

    carriers = np.asarray(CARRIER_FREQS)
    assert np.shape(component.noise(carriers, 1e3)) in ((), carriers.shape)


# ----------------------------------------------------------------------
# Which axis each source actually depends on
# ----------------------------------------------------------------------

AMPLIFIERS = ["amplifier.asu_3ghz_lna", "amplifier.cryoelec_lna",
              "amplifier.zx60_3018g_plus"]


@pytest.mark.parametrize("type_id", AMPLIFIERS)
def test_amplifier_noise_varies_with_carrier(type_id):
    """A noise temperature is a function of RF frequency."""
    amp = _make(type_id)
    values = [float(amp.noise(f, 1e3)) for f in CARRIER_FREQS]
    assert not np.allclose(values, values[0], rtol=1e-6, atol=0.0)


@pytest.mark.parametrize("type_id", AMPLIFIERS)
def test_amplifier_noise_is_white_in_spectral(type_id):
    """...and flat in offset from the carrier, near the carrier."""
    amp = _make(type_id)
    values = [float(amp.noise(1.5e9, f)) for f in SPECTRAL_FREQS]
    assert np.allclose(values, values[0], rtol=0.0, atol=0.0)


@pytest.mark.parametrize("type_id,expected_k", [
    ("amplifier.asu_3ghz_lna", 6.0),
    ("amplifier.cryoelec_lna", 4.0),
])
def test_amplifier_reports_its_datasheet_noise_temperature(type_id, expected_k):
    """
    The regression this interface fixes: these used to be handed the spectral
    frequency and returned their near-DC value - 30 K for the ASU LNA.
    """
    amp = _make(type_id)
    assert float(amp.noise(1.5e9, 1e3)) / kb == pytest.approx(expected_k, rel=1e-6)


def test_dac_noise_varies_with_spectral_frequency():
    """Phase noise is a 1/f skirt around the carrier."""
    dac = _make("converter.ad9082_dac")
    values = [float(dac.noise(1.5e9, f)) for f in SPECTRAL_FREQS]
    # Monotonically falling with offset.
    assert all(a > b for a, b in zip(values, values[1:]))


def test_dac_level_scales_with_carrier_power():
    """The spectral shape is preserved and shifted by the carrier power."""
    quiet = registry.create("converter.ad9082_dac", {"carrier_power_dbm": -30.0})
    loud = registry.create("converter.ad9082_dac", {"carrier_power_dbm": -20.0})
    for f in SPECTRAL_FREQS:
        ratio = float(loud.noise(1.5e9, f)) / float(quiet.noise(1.5e9, f))
        assert ratio == pytest.approx(10.0, rel=1e-9)


def test_dac_carrier_level_hook_is_a_documented_no_op():
    """
    The interface allows a carrier-frequency dependence; the fitted model has
    none, so the hook returns 0 dB and the noise is carrier-independent.
    """
    dac = _make("converter.ad9082_dac")
    assert dac.carrier_level_db(1.5e9) == 0.0
    assert float(dac.noise(1e8, 1e3)) == float(dac.noise(2.5e9, 1e3))


# ----------------------------------------------------------------------
# The generic converters - an arbitrary digitizer, stated rather than fitted
# ----------------------------------------------------------------------

def test_generic_dac_defaults_reproduce_the_ad9082_skirt():
    """
    The defaults are the AD9082's simple phase-noise model - -85 dBc/Hz at 1 Hz
    falling 10 dB/decade - so an unedited Generic DAC is a familiar part and a
    swap between the two isolates what the ADC side contributes.
    """
    generic = _make("converter.generic_dac")
    fitted = _make("converter.ad9082_dac")
    for f in SPECTRAL_FREQS:
        assert float(generic.noise(1.5e9, f)) == pytest.approx(
            float(fitted.noise(1.5e9, f)), rel=1e-6)


@pytest.mark.parametrize("slope,decade_ratio", [
    (-10.0, 0.1),      # 1/f in power
    (-20.0, 0.01),     # 1/f^2
    (0.0, 1.0),        # a white phase-noise floor
])
def test_generic_dac_slope_is_per_decade(slope, decade_ratio):
    """The slope means dB per decade of offset, at every decade."""
    dac = registry.create("converter.generic_dac",
                          {"phase_noise_slope_db_per_decade": slope})
    values = [float(dac.noise(1.5e9, f)) for f in (1e1, 1e2, 1e3, 1e4)]
    for here, next_decade in zip(values, values[1:]):
        assert next_decade / here == pytest.approx(decade_ratio, rel=1e-9)


def test_generic_dac_level_is_the_quoted_figure_at_the_quoted_offset():
    """
    dBc/Hz at an offset plus the carrier power in dBm is a density in dBm/Hz,
    which is the whole arithmetic of this model.
    """
    dac = registry.create("converter.generic_dac", {
        "carrier_power_dbm": -12.0,
        "phase_noise_dbc_per_hz": -110.0,
        "phase_noise_offset_hz": 1e4,
    })
    expected = 10**((-110.0 - 12.0) / 10) * 1e-3
    assert float(dac.noise(1.5e9, 1e4)) == pytest.approx(expected, rel=1e-12)


def test_generic_dac_scales_with_the_carrier_it_puts_out():
    """A skirt is relative to the carrier, so raising it raises the noise 1:1."""
    quiet = registry.create("converter.generic_dac", {"carrier_power_dbm": -30.0})
    loud = registry.create("converter.generic_dac", {"carrier_power_dbm": -20.0})
    for f in SPECTRAL_FREQS:
        assert float(loud.noise(1.5e9, f)) / float(quiet.noise(1.5e9, f)) == \
            pytest.approx(10.0, rel=1e-9)


def test_generic_dac_is_carrier_frequency_independent():
    """A stated part claims no measured dependence on the RF frequency."""
    dac = _make("converter.generic_dac")
    values = [float(dac.noise(f, 1e3)) for f in CARRIER_FREQS]
    assert np.allclose(values, values[0], rtol=0.0, atol=0.0)


def test_generic_dac_refuses_a_zero_reference_offset():
    """
    0 Hz is the carrier, not an offset from it, and dividing by it would return
    inf or nan for every offset instead of failing.
    """
    from hardware_models import GenericDAC

    with pytest.raises(ValueError, match="phase_noise_offset_hz"):
        GenericDAC(phase_noise_offset_hz=0.0)
    # And through the registry, which range-checks before constructing.
    with pytest.raises(ValueError, match="below the minimum"):
        registry.create("converter.generic_dac", {"phase_noise_offset_hz": 0.0})


def test_generic_adc_is_the_density_it_was_given():
    """dBm/Hz in, W/Hz out, flat in both axes."""
    adc = registry.create("converter.generic_adc",
                          {"noise_density_dbm_per_hz": -150.0})
    expected = 10**(-150.0 / 10) * 1e-3
    grid = [float(adc.noise(c, s))
            for c in CARRIER_FREQS for s in SPECTRAL_FREQS]
    assert np.allclose(grid, expected, rtol=1e-12, atol=0.0)


def test_generic_adc_default_is_the_ad9082_flat_datasheet_figure():
    """
    -140 dBm/Hz is the flat spec the AD9082 datasheet also quotes; the SNR-derived
    model sits below it. Having both means the discrepancy can be run, not just
    read about in the README.
    """
    generic = _make("converter.generic_adc")
    fitted = _make("converter.ad9082_adc")
    assert float(generic.noise(1.5e9, 1e3)) == pytest.approx(
        10**(-140.0 / 10) * 1e-3, rel=1e-12)
    assert float(generic.noise(1.5e9, 1e3)) > float(fitted.noise(1.5e9, 1e3))


@pytest.mark.parametrize("type_id", ["converter.generic_dac",
                                     "converter.generic_adc"])
def test_noiseless_converters_contribute_exactly_zero(type_id):
    """
    Not "very small": zero, on both axes and swept or scalar. A budget skips a
    stage with no noise, so an ideal converter leaves the chain to be judged on
    its components rather than leaving a line to be discounted by eye.
    """
    entry = registry.resolve(type_id)
    params = {s.name: s.default for s in entry.params}
    params["noiseless"] = True
    ideal = registry.create(type_id, params)

    for c in CARRIER_FREQS:
        for s in SPECTRAL_FREQS:
            assert float(ideal.noise(c, s)) == 0.0
    swept = ideal.noise(1.5e9, np.asarray(SPECTRAL_FREQS, dtype=float))
    assert np.shape(swept) == (len(SPECTRAL_FREQS),)
    assert np.all(np.asarray(swept) == 0.0)


@pytest.mark.parametrize("type_id", ["converter.generic_dac",
                                     "converter.generic_adc"])
def test_noiseless_still_applies_its_gain(type_id):
    """Noise-free is not transparent: the gain knob is untouched by the flag."""
    entry = registry.resolve(type_id)
    params = {s.name: s.default for s in entry.params}
    params.update(noiseless=True, gain_db=-3.5)
    ideal = registry.create(type_id, params)
    assert float(ideal.gain(1.5e9)) == pytest.approx(-3.5)


def test_attenuator_is_flat_in_both_axes():
    atten = registry.create("attenuator",
                            {"attenuation": -10, "temperature": 300})
    grid = [float(atten.noise(c, s))
            for c in CARRIER_FREQS for s in SPECTRAL_FREQS]
    assert np.allclose(grid, grid[0], rtol=0.0, atol=0.0)
    assert float(atten.noise(1.5e9, 1e3)) == pytest.approx(kb * 300, rel=1e-12)


def test_adc_noise_follows_the_datasheet_snr_curve():
    """
    The ADC floor comes from SNR versus input frequency, so it rises with the
    carrier. It replaced a flat -140 dBm/Hz figure.
    """
    adc = _make("converter.ad9082_adc")
    values = [float(adc.noise(f, 1e3)) for f in (1e9, 1.5e9, 2e9, 2.5e9, 3e9)]
    # SNR degrades with frequency, so the noise floor rises monotonically.
    assert all(a < b for a, b in zip(values, values[1:]))


def test_adc_noise_matches_the_datasheet_arithmetic():
    """SNR (dB below full scale) -> dBm -> W -> W/Hz, at a datasheet point."""
    from hardware_models import AD9082_ADC

    adc = _make("converter.ad9082_adc")
    # 1.5 GHz is a datasheet point: SNR 55 dBFS.
    expected = (10**((AD9082_ADC.full_scale_dbm - 55.0) / 10) * 1e-3
                / AD9082_ADC.nyquist_bandwidth_hz)
    assert float(adc.noise(1.5e9, 1e3)) == pytest.approx(expected, rel=1e-12)


def test_adc_reproduces_the_legacy_helper_curve():
    """The legacy AD9082 shim carries the same curve; they must not diverge."""
    from hardware_models import AD9082

    adc = _make("converter.ad9082_adc")
    legacy = AD9082()
    for f in (1e8, 1e9, 1.5e9, 2.5e9, 3e9):
        assert float(adc.noise(f, 1e3)) == pytest.approx(
            float(legacy.adc_noise(f)), rel=1e-12)


def test_adc_noise_is_white_in_spectral():
    adc = _make("converter.ad9082_adc")
    values = [float(adc.noise(1.5e9, f)) for f in SPECTRAL_FREQS]
    assert np.allclose(values, values[0], rtol=0.0, atol=0.0)


# ----------------------------------------------------------------------
# flat_in_spectral
# ----------------------------------------------------------------------

def test_flat_in_spectral_broadcasting():
    assert flat_in_spectral(2.0, 1e3) == 2.0
    assert isinstance(flat_in_spectral(2.0, 1e3), float)

    spread = flat_in_spectral(2.0, np.logspace(0, 4, 5))
    assert spread.shape == (5,)
    assert np.all(spread == 2.0)

    # A carrier sweep with a scalar spectral frequency keeps the sweep shape.
    levels = np.array([1.0, 2.0, 3.0])
    assert np.array_equal(flat_in_spectral(levels, 1e3), levels)


def test_legacy_single_frequency_noise_still_works():
    """
    Duck-typed components predating the two-argument convention are still
    accepted by the chain, receiving the spectral frequency as before.
    """
    from signal_chain import _evaluate_noise

    class OneArg:
        def noise(self, frequency):
            return 1e-20 if frequency == 1e3 else 0.0

    class NoArg:
        def noise(self):
            return 5e-21

    assert _evaluate_noise(OneArg(), 1.5e9, 1e3) == 1e-20
    assert _evaluate_noise(NoArg(), 1.5e9, 1e3) == 5e-21
