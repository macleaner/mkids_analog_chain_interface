"""
Physical sanity checks on the cable models.

These assert against values derived from the datasheets rather than against a
snapshot, so they would have caught the two bugs the golden file had merely
recorded: loss scaling as length**2, and unnegated attenuation making a passive
cable appear to have gain.
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import registry  # noqa: E402

# Every registered cable, with a frequency inside its datasheet range.
CABLES = [
    ("cable.sma_generic", 1.5e9),
    ("cable.fm_f141", 1.5e9),
    ("cable.rg58c", 1.0e9),
    ("cable.rg174a", 4.0e8),
    ("cable.sma_cuni_cryo", 1.0e9),
    ("cable.sma_cuni086_cryo", 1.0e9),
    ("cable.sma_ss086_cryo", 1.0e9),
    ("cable.sma_ss219_cryo", 1.0e9),
    ("cable.sma_nbti086_cryo", 1.0e9),
    ("cable.bcb029_ss034", 1.0e9),
    ("cable.bcb014_ss085", 1.0e9),
    ("cable.bcb024_sp034", 1.0e9),
    ("cable.bcb012_nbti034", 1.0e9),
]


def _make(type_id, length_m):
    entry = registry.resolve(type_id)
    params = {"length_m": length_m}
    if any(s.name == "temperature" for s in entry.params):
        params["temperature"] = 4.0
    return registry.create(type_id, params)


@pytest.mark.parametrize("type_id,freq", CABLES)
def test_a_passive_cable_never_has_gain(type_id, freq):
    """A length of coax cannot amplify."""
    gain = float(_make(type_id, 1.0).gain(freq))
    assert gain <= 0.0, f"{type_id} reports +{gain:.3f} dB of gain"


@pytest.mark.parametrize("type_id,freq", CABLES)
def test_loss_is_linear_in_length(type_id, freq):
    """
    Doubling the length must double the dB loss. Two models previously folded
    length into the datasheet array and multiplied it in again in gain(),
    scaling loss as length**2.
    """
    one = float(_make(type_id, 1.0).gain(freq))
    two = float(_make(type_id, 2.0).gain(freq))
    four = float(_make(type_id, 4.0).gain(freq))

    if abs(one) < 1e-12:
        pytest.skip(f"{type_id} is lossless at {freq:g} Hz")

    assert two == pytest.approx(2 * one, rel=1e-9)
    assert four == pytest.approx(4 * one, rel=1e-9)


@pytest.mark.parametrize("type_id,freq", CABLES)
def test_zero_length_is_lossless(type_id, freq):
    assert float(_make(type_id, 0.0).gain(freq)) == pytest.approx(0.0)


def test_loss_matches_the_datasheet_for_a_known_case():
    """
    Spot-check against numbers read straight off the datasheets, independent of
    the implementation.
    """
    # RG58C/U: 65.62 dB per 100 m at 1 GHz -> -0.6562 dB/m.
    rg58 = registry.create("cable.rg58c", {"length_m": 10.0})
    assert float(rg58.gain(1.0e9)) == pytest.approx(-6.562, rel=1e-6)

    # RG174A/U: 104.99 dB per 100 m at 1 GHz -> -1.0499 dB/m.
    rg174 = registry.create("cable.rg174a", {"length_m": 10.0})
    assert float(rg174.gain(1.0e9)) == pytest.approx(-10.499, rel=1e-6)

    # Fairview F141: -0.37 dB/m at 1 GHz.
    f141 = registry.create("cable.fm_f141", {"length_m": 3.0})
    assert float(f141.gain(1.0e9)) == pytest.approx(-1.11, rel=1e-6)

    # SS086 cryo at 4 K: -6.6 dB/m at 1 GHz.
    ss086 = registry.create("cable.sma_ss086_cryo",
                            {"length_m": 0.5, "temperature": 4.0})
    assert float(ss086.gain(1.0e9)) == pytest.approx(-3.3, rel=1e-6)


def test_cryo_cables_are_less_lossy_cold_than_warm():
    """Every temperature-switched cable should improve on cooling."""
    for type_id, freq in CABLES:
        entry = registry.resolve(type_id)
        if not any(s.name == "temperature" for s in entry.params):
            continue
        spec = entry.param("temperature")
        warm_value = 300.0
        if spec.choices and warm_value not in spec.choices:
            continue
        warm = float(registry.create(
            type_id, {"length_m": 1.0, "temperature": warm_value}).gain(freq))
        cold = float(registry.create(
            type_id, {"length_m": 1.0, "temperature": 4.0}).gain(freq))
        assert cold >= warm, f"{type_id} is lossier at 4 K than at 300 K"


def test_room_temperature_cables_get_lossier_with_frequency():
    for type_id in ("cable.sma_generic", "cable.fm_f141", "cable.rg58c"):
        cable = registry.create(type_id, {"length_m": 1.0})
        low = float(cable.gain(1.0e8))
        high = float(cable.gain(1.0e9))
        assert high <= low, f"{type_id} loss does not increase with frequency"
