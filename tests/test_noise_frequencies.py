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


def test_attenuator_and_adc_are_flat_in_both_axes():
    atten = registry.create("attenuator",
                            {"attenuation": -10, "temperature": 300})
    adc = _make("converter.ad9082_adc")
    for component in (atten, adc):
        grid = [float(component.noise(c, s))
                for c in CARRIER_FREQS for s in SPECTRAL_FREQS]
        assert np.allclose(grid, grid[0], rtol=0.0, atol=0.0)
    assert float(atten.noise(1.5e9, 1e3)) == pytest.approx(kb * 300, rel=1e-12)


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
