"""
Tests for the JSON facade the browser build drives.

The facade's job is to expose the chain machinery across a language boundary
without becoming a second implementation of it. So these tests check two
things: that everything it returns really is JSON (a numpy scalar that reaches
``json.dumps`` is an exception in the browser, not a warning), and that its
numbers are the ones ``SignalChain`` produces rather than anything computed
here.
"""

import json

import numpy as np
import pytest

import chain_api
import registry
from signal_chain import SignalChain

CARRIER = 1.5e9
SPECTRAL = 1.0e3


@pytest.fixture(autouse=True)
def fresh_preset():
    """Every test starts from the same preset; the facade holds module state."""
    result = chain_api.load_preset("cryo_example")
    assert result["ok"], result.get("error")
    yield result


def roundtrips(payload):
    """True if the payload survives json.dumps -> json.loads unchanged."""
    return json.loads(json.dumps(payload)) == payload


# ---------------------------------------------------------------- JSON safety
def test_every_endpoint_returns_real_json():
    """
    A numpy float32 is not JSON-serializable, and the failure surfaces in the
    browser as an opaque bridge error rather than at the call site. Assert the
    coercion for every endpoint the view uses.
    """
    payloads = [
        chain_api.provenance(),
        chain_api.catalog(),
        chain_api.presets(),
        chain_api.describe(),
        chain_api.budget("LNA", "input", CARRIER, SPECTRAL),
        chain_api.sweep_gain(1e8, 3e9, 21),
        chain_api.sweep_noise(CARRIER, 1e2, 1e6, 11, True, True),
        chain_api.to_json(),
    ]
    for payload in payloads:
        assert payload["ok"], payload.get("error")
        assert roundtrips(payload)


def test_non_finite_becomes_null_not_nan():
    """
    JSON has no NaN. ``json.dumps`` emits a bare ``NaN`` token by default,
    which ``JSON.parse`` rejects - so the whole response would fail to parse
    because of one bad point. The DAC phase-noise fit does go non-finite just
    outside its datasheet range, so this is a live path, not a hypothetical.
    """
    result = chain_api.sweep_noise(CARRIER, 1e0, 1e7, 61, True, False)
    assert result["ok"]
    serialized = json.dumps(result, allow_nan=False)      # raises on NaN/Inf
    assert "NaN" not in serialized and "Infinity" not in serialized


# ------------------------------------------------------- no second math path
def test_budget_matches_signal_chain_directly():
    """The facade must report SignalChain's numbers, not its own."""
    chain = SignalChain(name="direct")
    for type_id, params, label in [
        ("attenuator", {"attenuation": -10.0, "temperature": 300.0}, "InputAtten"),
        ("cable.fm_f141", {"length_m": 2.0}, "WarmCable_In"),
        ("cable.sma_ss086_cryo", {"length_m": 0.5, "temperature": 4.0}, "CryoCable"),
        ("attenuator", {"attenuation": -20.0, "temperature": 4.0}, "ColdAtten"),
        ("amplifier.asu_3ghz_lna", {}, "LNA"),
        ("cable.sma_ss086_cryo", {"length_m": 0.5, "temperature": 50.0}, "ReturnCable"),
        ("amplifier.zx60_3018g_plus", {}, "WarmAmp1"),
        ("amplifier.zx60_3018g_plus", {}, "WarmAmp2"),
    ]:
        chain.add_component(registry.create(type_id, params), label=label)
    chain.set_digitizer(
        registry.create("converter.ad9082_dac", {"carrier_power_dbm": -10.0}),
        registry.create("converter.ad9082_adc", {}))

    expected = chain.noise_budget("LNA", CARRIER, SPECTRAL, at="input")
    actual = chain_api.budget("LNA", "input", CARRIER, SPECTRAL)

    assert actual["total_w_per_hz"] == pytest.approx(float(expected.total_w), rel=1e-12)
    assert actual["total_k"] == pytest.approx(float(expected.total_k), rel=1e-12)
    assert actual["dominant"] == expected.dominant().label

    by_source = {row["source"]: row for row in actual["rows"]}
    for contribution in expected.contributions:
        assert by_source[contribution.label]["contribution_w_per_hz"] == \
            pytest.approx(float(contribution.power_w), rel=1e-12)


def test_sweep_gain_matches_total_gain():
    freq = np.linspace(1e8, 3e9, 17)
    result = chain_api.sweep_gain(1e8, 3e9, 17)
    expected = np.asarray(chain_api._CHAIN.total_gain(freq), dtype=float)
    assert result["gain_db"] == pytest.approx(list(expected), rel=1e-12)


def test_referred_noise_sweep_matches_the_budget_at_that_offset():
    """
    The plot and the table are the same decomposition, one swept and one at a
    single offset. Referred to the same plane they must agree exactly, or the
    curve a user reads off the plot is not the number the budget reports.
    """
    swept = chain_api.sweep_noise(CARRIER, 1e0, SPECTRAL, 5, True, True,
                                  "LNA", "input")
    assert swept["ok"], swept.get("error")
    table = chain_api.budget("LNA", "input", CARRIER, SPECTRAL)

    assert swept["reference"] == table["reference"] == "LNA (input)"
    # The sweep ends on SPECTRAL, so its last point is the table's column.
    assert swept["total_w_per_hz"][-1] == pytest.approx(
        table["total_w_per_hz"], rel=1e-12)

    by_source = {row["source"]: row for row in table["rows"]}
    for entry in swept["series"]:
        assert entry["w_per_hz"][-1] == pytest.approx(
            by_source[entry["label"]]["contribution_w_per_hz"], rel=1e-12)


def test_noise_sweep_defaults_to_the_chain_output():
    """No reference means the output, as it did before planes were selectable."""
    result = chain_api.sweep_noise(CARRIER, 1e2, 1e5, 13, True, False)
    assert result["reference"] == "chain output"
    expected = chain_api._CHAIN.output_noise(
        CARRIER, np.logspace(2, 5, 13))
    assert result["total_w_per_hz"] == pytest.approx(list(expected), rel=1e-12)


def test_noise_sweep_units_are_consistent():
    """dBm/Hz is reported alongside W/Hz so the view never converts. Check the
    two columns describe the same numbers."""
    result = chain_api.sweep_noise(CARRIER, 1e2, 1e5, 13, True, False)
    for watts, dbm in zip(result["total_w_per_hz"], result["total_dbm_per_hz"]):
        if watts is None or dbm is None:
            continue
        assert dbm == pytest.approx(10 * np.log10(watts * 1e3), rel=1e-12)


# ------------------------------------------------------------ chain mutation
def test_set_param_rebuilds_so_derived_state_is_not_stale():
    """
    Several models precompute interpolators in ``__init__``. Changing a
    parameter has to rebuild the component, or the gain would keep coming from
    the interpolator built for the old value.
    """
    before = chain_api.sweep_gain(CARRIER, CARRIER * 1.0001, 2)["gain_db"][0]
    result = chain_api.set_param(3, "attenuation", -6.0)     # ColdAtten, -20 -> -6
    assert result["ok"], result.get("error")
    after = chain_api.sweep_gain(CARRIER, CARRIER * 1.0001, 2)["gain_db"][0]
    assert after - before == pytest.approx(14.0, abs=1e-9)


def test_remove_component_reindexes_labels():
    """
    ``chain.labels`` maps label -> index, so removing a component must drop the
    label pointing at it and shift every higher index down. Getting this
    backwards leaves labels addressing the wrong components, which then
    silently mis-references every budget taken by label.
    """
    result = chain_api.remove_component(1)                   # WarmCable_In
    assert result["ok"], result.get("error")

    labels = chain_api._CHAIN.labels
    assert "WarmCable_In" not in labels
    components = chain_api._CHAIN.components
    for label, index in labels.items():
        assert 0 <= index < len(components)
        # The label must still name the component it originally named.
        assert chain_api._CHAIN._get_label_for_index(index) == label
    assert labels["CryoCable"] == 1                           # was 2
    assert labels["InputAtten"] == 0                          # unmoved


def test_set_label_rejects_a_duplicate():
    result = chain_api.set_label(0, "LNA")
    assert not result["ok"]
    assert "already refers to" in result["error"]


def test_add_then_remove_restores_the_budget():
    original = chain_api.budget("LNA", "input", CARRIER, SPECTRAL)
    added = chain_api.add_component("filter.vhf1320p", {}, "OutFilter")
    assert added["ok"], added.get("error")
    chain_api.remove_component(added["n_components"] - 1)
    restored = chain_api.budget("LNA", "input", CARRIER, SPECTRAL)
    assert restored["total_w_per_hz"] == pytest.approx(
        original["total_w_per_hz"], rel=1e-12)


# ------------------------------------------------------------- round tripping
def test_round_trip_preserves_the_chain():
    exported = chain_api.to_json()
    assert exported["ok"]
    before = chain_api.describe()
    reloaded = chain_api.from_json(exported["json"])
    assert reloaded["ok"], reloaded.get("error")
    assert reloaded["stages"] == before["stages"]
    assert reloaded["name"] == before["name"]


def test_exported_json_loads_as_a_signal_chain():
    """What the browser's download button hands back must be the file format a
    notebook reloads, not a private view format."""
    exported = chain_api.to_json()
    chain = SignalChain.from_dict(json.loads(exported["json"]))
    assert len(chain.components) == chain_api.describe()["n_components"]
    assert chain.dac is not None and chain.adc is not None


# --------------------------------------------------------------- error paths
@pytest.mark.parametrize("call, fragment", [
    (lambda: chain_api.load_preset("nope"), "unknown preset"),
    (lambda: chain_api.set_param(0, "attenuation", 500.0), "above the maximum"),
    (lambda: chain_api.set_param(0, "nonsense", 1.0), "no parameter"),
    (lambda: chain_api.remove_component(999), "out of range"),
    (lambda: chain_api.budget("NoSuchPlane", "input", CARRIER, SPECTRAL),
     "cannot resolve"),
    (lambda: chain_api.sweep_gain(1e9, 1e9, 10), "must exceed"),
    (lambda: chain_api.sweep_gain(1e9, 2e9, 1), "at least 2 points"),
    (lambda: chain_api.sweep_gain(0.0, 2e9, 10, True), "positive start"),
    (lambda: chain_api.from_json("{not json"), ""),
])
def test_failures_come_back_as_data(call, fragment):
    """
    A view on the other side of a language boundary can display a message but
    cannot inspect a traceback, so nothing here may raise.
    """
    result = call()
    assert result["ok"] is False
    assert fragment in result["error"]
    assert roundtrips(result)


def test_validation_message_comes_from_the_registry():
    """
    The browser's form constraints and the Qt panel's are the same ParamSpec,
    so the rejection message should be the one ParamSpec.validate produces -
    declared once, in registry.py.
    """
    result = chain_api.set_param(0, "attenuation", 500.0)
    spec = registry.resolve("attenuator").param("attenuation")
    with pytest.raises(ValueError) as raised:
        spec.validate(500.0)
    assert str(raised.value) in result["error"]
