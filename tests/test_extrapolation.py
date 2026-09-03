"""
What a model may say outside its datasheet.

Every model with a tabulated gain curve answers at any carrier frequency, so a
chain swept wider than its narrowest part still has a total gain instead of a
hole - a dB sum takes one NaN and loses the whole curve. That is only defensible
if the extension is bounded and if the model still says where the measurements
stopped, which is what these assert:

* it cannot claim more gain, or less loss, than the datasheet measured;
* it joins the measured curve continuously at the band edge, so the estimate
  starts from the last real point rather than from a jump;
* inside the band nothing changed - the datasheet still governs;
* the band itself is reported, because the gain no longer shows it.

These are physical properties, not a snapshot; tests/test_characterization.py
pins the numbers.
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import registry  # noqa: E402

# Every model that holds a tabulated curve, with the arguments to build it.
TABULATED = {
    "amplifier.asu_3ghz_lna": {},
    "amplifier.zx60_3018g_plus": {},
    "amplifier.cryoelec_lna": {},
    "amplifier.cmt_citcryo1_12d": {},
    "amplifier.lnf_lnc1_5_6b": {},
    "amplifier.lnf_lnc0_3_14b": {},
    "filter.vhf1320p": {},
    "filter.vhf5050p": {},
    "filter.vlf6700p": {},
    "cable.sma_generic": {"length_m": 1.0},
    "cable.fm_f141": {"length_m": 1.0},
    "cable.rg58c": {"length_m": 1.0},
    "cable.rg174a": {"length_m": 1.0},
    "cable.sma_cuni_cryo": {"length_m": 1.0, "temperature": 4.0},
    "cable.sma_cuni086_cryo": {"length_m": 1.0, "temperature": 4.0},
    "cable.sma_ss086_cryo": {"length_m": 1.0, "temperature": 300.0},
    "cable.sma_ss219_cryo": {"length_m": 1.0, "temperature": 4.0},
    "cable.sma_nbti086_cryo": {"length_m": 1.0, "temperature": 4.0},
    "cable.bcb029_ss034": {"length_m": 1.0, "temperature": 4.0},
    "cable.bcb014_ss085": {"length_m": 1.0, "temperature": 4.0},
    "cable.bcb024_sp034": {"length_m": 1.0, "temperature": 4.0},
    "cable.bcb012_nbti034": {"length_m": 1.0, "temperature": 4.0},
}

# The filters clamp to their own pair of bounds instead - see
# test_a_filter_is_bounded_by_its_own_rule.
FILTERS = {k for k in TABULATED if k.startswith("filter.")}

# Far enough past every band in the library to be an extrapolation for all of
# them, and low enough at the other end to leave the ones tabulated from 1 GHz.
FAR_HZ = np.asarray([0.0, 1e6, 5e7, 1e8, 2e10, 3e10, 4e10])


def build(type_id):
    return registry.create(type_id, TABULATED[type_id])


@pytest.mark.parametrize("type_id", sorted(TABULATED))
def test_every_tabulated_model_answers_everywhere(type_id):
    """A NaN anywhere in a stage's gain blanks the chain's whole gain curve."""
    component = build(type_id)
    gain = np.asarray(component.gain(FAR_HZ), dtype=float)
    assert np.isfinite(gain).all(), f"{type_id} is silent at some carrier"


@pytest.mark.parametrize("type_id", sorted(TABULATED))
def test_every_tabulated_model_states_its_band(type_id):
    """
    The gain no longer shows where the datasheet ended, so the model has to
    say. This is what the GUI shades and what a notebook prints.
    """
    low, high = build(type_id).defined_span_hz()
    assert 0.0 <= low < high


@pytest.mark.parametrize("type_id", sorted(set(TABULATED) - FILTERS))
def test_extrapolation_never_beats_the_measured_curve(type_id):
    """
    The bound on an amplifier's or a cable's extension: it may not report more
    gain, or less loss, than the datasheet actually measured. Without it a
    linear extension off a rising band edge climbs forever, and a chain gets
    free gain in the region where nobody looked - the direction of error that
    flatters a budget.
    """
    component = build(type_id)
    low, high = component.defined_span_hz()
    inside = np.linspace(low, high, 401)
    best_measured = float(np.nanmax(np.asarray(component.gain(inside), dtype=float)))

    outside = np.asarray(component.gain(FAR_HZ), dtype=float)
    assert (outside <= best_measured + 1e-9).all(), (
        f"{type_id} reports {outside.max():.2f} dB outside its band, better "
        f"than the {best_measured:.2f} dB it measures inside it")


@pytest.mark.parametrize("type_id", sorted(TABULATED))
def test_the_estimate_starts_where_the_measurement_stops(type_id):
    """
    The extension continues the measured curve rather than stepping off it: a
    discontinuity at the band edge would be a visible artifact of the model's
    storage, and the first estimated point is the one most likely to be right.
    """
    component = build(type_id)
    low, high = component.defined_span_hz()
    step = max(1.0, (high - low) * 1e-6)
    for edge, just_outside in ((low, low - step), (high, high + step)):
        if just_outside < 0:
            continue                    # nothing below DC to extrapolate into
        at_edge = float(np.asarray(component.gain(edge), dtype=float))
        beyond = float(np.asarray(component.gain(just_outside), dtype=float))
        assert beyond == pytest.approx(at_edge, abs=1e-3), (
            f"{type_id} jumps at {edge/1e9:g} GHz: {at_edge:.3f} dB inside, "
            f"{beyond:.3f} dB just outside")


@pytest.mark.parametrize("type_id", sorted(TABULATED))
def test_inside_the_band_the_datasheet_still_governs(type_id):
    """
    Extrapolating is a statement about the outside only. The clamp that bounds
    it is inert within the band, so an interpolated point is the datasheet's
    own linear interpolation and not a clipped version of it.
    """
    component = build(type_id)
    low, high = component.defined_span_hz()
    inside = np.linspace(low, high, 97)
    gain = np.asarray(component.gain(inside), dtype=float)
    assert np.isfinite(gain).all()
    # A clamp biting inside the band would flatten the curve onto one value.
    assert gain.max() > gain.min()


def test_an_amplifier_out_of_band_still_reports_no_noise():
    """
    Gain extrapolates; noise does not. There is no honest cap on a noise
    extension - a HEMT's noise rises steeply at both band edges and a straight
    line understates it, which is again the direction that flatters a budget -
    so a carrier outside the band gets a flagged gain estimate and no noise
    figure, rather than an invented one.
    """
    lna = build("amplifier.lnf_lnc1_5_6b")
    low, high = lna.defined_span_hz()
    assert np.isfinite(float(lna.gain(high * 2)))
    assert not np.isfinite(float(np.asarray(lna.noise(high * 2, 1e3)).ravel()[0]))


@pytest.mark.parametrize("type_id", sorted(FILTERS))
def test_a_filter_is_bounded_by_its_own_rule(type_id):
    """
    A filter is clamped to 0 dB rather than to the least loss it measured, and
    has a floor as well. Both differ from the amplifiers' rule on purpose: a
    passband is lossless in principle - VLF-6700+ is specified down to DC but
    tabulated only from 50 MHz - while a linear extension run far into a
    stopband would claim rejection deeper than any measurement supports.
    """
    component = build(type_id)
    low, high = component.defined_span_hz()
    inside = np.asarray(component.gain(np.linspace(low, high, 401)), dtype=float)
    outside = np.asarray(component.gain(FAR_HZ), dtype=float)
    assert (outside <= 0.0).all()
    assert (outside >= inside.min() - 1e-9).all(), (
        f"{type_id} claims {outside.min():.2f} dB outside its band, deeper "
        f"than the {inside.min():.2f} dB it measures inside it")


@pytest.mark.parametrize("type_id", sorted(TABULATED))
def test_a_passive_part_cannot_amplify_outside_its_band_either(type_id):
    """
    What the clamps buy for a cable or a filter: extending a loss curve toward
    DC runs it toward zero loss, and one step further would be gain from a
    passive part. tests/test_cable_physics.py asserts the same thing inside
    the band, where the datasheet is what guarantees it.
    """
    component = build(type_id)
    if component.component_type != "passive":
        pytest.skip(f"{type_id} is not passive")
    gain = np.asarray(component.gain(FAR_HZ), dtype=float)
    assert (gain <= 0.0).all(), f"{type_id} reports gain: {gain.max():.3f} dB"
