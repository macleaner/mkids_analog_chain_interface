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


def test_move_component_reorders_and_carries_its_label_along():
    """
    A label names a component, not a position, so a move has to renumber
    ``chain.labels`` through the same permutation. If it does not, a budget
    taken by label silently starts describing whichever component slid into the
    old slot - the same failure as a mis-reindexed removal, but harder to see,
    because the chain still has every stage it did before.
    """
    result = chain_api.move_component(3, 4)        # ColdAtten past the LNA
    assert result["ok"], result.get("error")
    assert [s["label"] for s in result["stages"]] == [
        "AD9082_DAC", "InputAtten", "WarmCable_In", "CryoCable",
        "LNA", "ColdAtten", "ReturnCable", "WarmAmp1", "WarmAmp2", "AD9082_ADC",
    ]
    labels = chain_api._CHAIN.labels
    assert labels["ColdAtten"] == 4 and labels["LNA"] == 3
    for label, index in labels.items():
        assert chain_api._CHAIN._get_label_for_index(index) == label


def test_moving_a_stage_keeps_the_gain_and_changes_the_noise():
    """
    The physics the reorder exists for: cascaded gain is a product and does not
    care about order, but noise does - an attenuator ahead of the LNA costs
    noise figure, and the same attenuator behind it barely matters. A reorder
    that left the budget untouched would mean the move never reached the
    cascade.

    Referred to the chain output rather than to the LNA, because that plane is
    the thing being moved: "LNA input" is a different point in the cascade
    before and after, so a budget taken there mixes the move up with a change
    of reference. And per source rather than on the total, which this preset's
    DAC phase noise dominates from upstream of both stages either way.
    """
    def contribution(result, source):
        row, = [r for r in result["rows"] if r["source"] == source]
        return row["contribution_dBm_per_hz"]

    span = (CARRIER, CARRIER * 1.0001, 2)
    gain_before = chain_api.sweep_gain(*span)["gain_db"][0]
    before = chain_api.budget("WarmAmp2", "output", CARRIER, SPECTRAL)

    assert chain_api.move_component(3, 4)["ok"]     # ColdAtten past the LNA
    after = chain_api.budget("WarmAmp2", "output", CARRIER, SPECTRAL)

    assert chain_api.sweep_gain(*span)["gain_db"][0] == pytest.approx(
        gain_before, abs=1e-9)
    # The LNA's own noise now passes through the attenuator's flat 20 dB, and
    # the attenuator's thermal noise no longer sees the LNA's gain.
    assert contribution(after, "LNA") == pytest.approx(
        contribution(before, "LNA") - 20.0, abs=0.1)
    assert contribution(after, "ColdAtten") < contribution(before, "ColdAtten") - 20


def test_moving_a_stage_to_where_it_already_is_changes_nothing():
    """The browser sends a drop wherever the pointer landed, including back."""
    before = chain_api.describe()
    after = chain_api.move_component(2, 2)
    assert after["ok"], after.get("error")
    assert after == before


def test_a_reordered_chain_saves_in_its_new_order():
    """
    The order is the record. A move that only reordered the view would hand
    back a file describing the chain as it was built rather than as it is.
    """
    assert chain_api.move_component(7, 0)["ok"]     # WarmAmp2 to the front
    saved = json.loads(chain_api.to_json()["json"])
    reloaded = SignalChain.from_dict(saved)
    assert [c.name for c in reloaded.components][0] == "WarmAmp2"
    assert reloaded.labels["WarmAmp2"] == 0
    assert reloaded.labels["InputAtten"] == 1


def test_set_label_rejects_a_duplicate():
    result = chain_api.set_label(0, "LNA")
    assert not result["ok"]
    assert "already refers to" in result["error"]


def test_appended_converter_keeps_a_component_index():
    """
    A converter belongs at an endpoint, but nothing stops one being appended -
    from a script, or from a chain file that recorded it that way. It is then a
    normal member of ``chain.components`` and must be reported with its index:
    without one the browser can neither edit nor remove it, so the chain holds
    a stage the user cannot get rid of.
    """
    added = chain_api.add_component("converter.ad9082_dac", {}, "StrayDAC")
    assert added["ok"], added.get("error")
    stray, = [s for s in added["stages"] if s["label"] == "StrayDAC"]
    assert stray["kind"] == "dac"                    # still a DAC by class
    assert stray["component_index"] == added["n_components"] - 1
    # The installed DAC is the one without an index, identified by identity.
    installed = [s for s in added["stages"] if s["component_index"] is None]
    assert [s["kind"] for s in installed] == ["dac", "adc"]
    assert chain_api.remove_component(stray["component_index"])["ok"]


# ---------------------------------------------------------------- new chains
def test_new_chain_is_empty_and_still_describable():
    """
    The browser renders whatever ``describe`` reports, so a chain with no
    stages has to be a valid answer rather than an error: no stages, no planes,
    and no converters until :func:`set_digitizer` installs them.
    """
    result = chain_api.new_chain("Cooldown 12")
    assert result["ok"], result.get("error")
    assert result["name"] == "Cooldown 12"
    assert result["stages"] == [] and result["planes"] == []
    assert result["n_components"] == 0
    assert result["digitizer"] == {"dac": None, "adc": None}
    assert result["has_digitizer"] is False
    assert roundtrips(result)


def test_an_empty_chain_still_sweeps():
    """
    The plots are drawn on every render, including right after "new chain".
    Both sweeps must return data for an empty chain - zero gain, and a total
    noise of zero, which is non-finite in dBm and so comes back as null.
    """
    chain_api.new_chain("Empty")
    gain = chain_api.sweep_gain(1e8, 3e9, 5)
    assert gain["ok"], gain.get("error")
    assert gain["gain_db"] == [0.0] * 5

    noise = chain_api.sweep_noise(CARRIER, 1e0, 1e3, 5, True, True)
    assert noise["ok"], noise.get("error")
    assert noise["total_w_per_hz"] == [0.0] * 5
    assert noise["total_dbm_per_hz"] == [None] * 5
    assert noise["series"] == []
    assert roundtrips(gain) and roundtrips(noise)


def test_a_new_chain_can_be_built_up_and_saved():
    """
    The whole point of creating a chain in the browser: build one from nothing
    and hand back a file a notebook reloads.
    """
    chain_api.new_chain("Bench 2026-08")
    chain_api.set_digitizer("converter.ad9082_dac", "converter.ad9082_adc",
                            {"carrier_power_dbm": -10.0}, None)
    chain_api.add_component("attenuator", {"attenuation": -10.0,
                                           "temperature": 300.0}, "InputAtten")
    built = chain_api.add_component("amplifier.asu_3ghz_lna", {}, "LNA")
    assert built["ok"], built.get("error")
    assert [s["kind"] for s in built["stages"]] == \
        ["dac", "passive", "active", "adc"]

    exported = chain_api.to_json()
    assert exported["suggested_filename"] == "bench_2026-08.json"
    chain = SignalChain.from_dict(json.loads(exported["json"]))
    assert chain.name == "Bench 2026-08"
    assert chain.load_warnings == []
    assert chain.dac.params["carrier_power_dbm"] == -10.0
    assert sorted(chain.labels) == ["InputAtten", "LNA"]


# ----------------------------------------------------------------- digitizer
def test_set_digitizer_installs_endpoints_at_the_ends():
    chain_api.new_chain("Ends")
    chain_api.add_component("amplifier.asu_3ghz_lna", {}, "LNA")
    result = chain_api.set_digitizer("converter.ad9082_dac",
                                     "converter.ad9082_adc")
    assert result["ok"], result.get("error")
    assert [s["kind"] for s in result["stages"]] == ["dac", "active", "adc"]
    # Endpoints, so neither is addressable as a component.
    assert [s["component_index"] for s in result["stages"]] == [None, 0, None]
    assert result["has_digitizer"] is True
    # Omitted params come from the registry, not from anywhere in this module.
    spec = registry.resolve("converter.ad9082_dac").param("carrier_power_dbm")
    assert result["digitizer"]["dac"]["params"]["carrier_power_dbm"] == spec.default


def test_set_digitizer_matches_signal_chain_directly():
    """The facade must install the converters SignalChain would, not stand-ins."""
    chain_api.new_chain("Compare")
    chain_api.add_component("amplifier.asu_3ghz_lna", {}, "LNA")
    chain_api.set_digitizer("converter.ad9082_dac", "converter.ad9082_adc",
                            {"carrier_power_dbm": -10.0}, {"gain_db": 3.0})
    actual = chain_api.budget("LNA", "input", CARRIER, SPECTRAL)

    direct = SignalChain(name="Compare")
    direct.add_component(registry.create("amplifier.asu_3ghz_lna", {}),
                         label="LNA")
    direct.set_digitizer(
        registry.create("converter.ad9082_dac", {"carrier_power_dbm": -10.0}),
        registry.create("converter.ad9082_adc", {"gain_db": 3.0}))
    expected = direct.noise_budget("LNA", CARRIER, SPECTRAL, at="input")

    assert actual["total_w_per_hz"] == pytest.approx(
        float(expected.total_w), rel=1e-12)
    assert actual["dominant"] == expected.dominant().label


def test_set_digitizer_replaces_rather_than_merges():
    """
    A swap starts from the registry defaults - nothing is carried over from the
    converter being replaced. A caller that wants the old settings passes them,
    which is why the browser resends the end it did not touch.
    """
    chain_api.set_digitizer_param("dac", "carrier_power_dbm", -25.0)
    swapped = chain_api.set_digitizer("converter.ad9082_dac",
                                      "converter.ad9082_adc")
    assert swapped["digitizer"]["dac"]["params"]["carrier_power_dbm"] == 0.0


def test_set_digitizer_can_clear_both_ends():
    result = chain_api.set_digitizer()
    assert result["ok"], result.get("error")
    assert result["digitizer"] == {"dac": None, "adc": None}
    assert result["has_digitizer"] is False
    assert all(s["kind"] not in ("dac", "adc") for s in result["stages"])
    # Removing the DAC removes its noise, which dominated this preset.
    assert chain_api.budget("LNA", "input", CARRIER, SPECTRAL)["dominant"] != \
        "AD9082_DAC"


def test_set_digitizer_param_rebuilds_the_converter():
    """
    Same reason as ``set_param``: the DAC fits its phase-noise model in
    ``__init__``, so a carrier-power change has to rebuild it. 10 dB more
    carrier is 10 dB more phase noise, referred anywhere.
    """
    before = chain_api.budget("AD9082_DAC", "output", CARRIER, SPECTRAL)
    assert chain_api._CHAIN.dac.params["carrier_power_dbm"] == -10.0
    result = chain_api.set_digitizer_param("dac", "carrier_power_dbm", 0.0)
    assert result["ok"], result.get("error")
    after = chain_api.budget("AD9082_DAC", "output", CARRIER, SPECTRAL)

    by_source = lambda budget: {r["source"]: r for r in budget["rows"]}
    assert (by_source(after)["AD9082_DAC"]["contribution_dBm_per_hz"]
            - by_source(before)["AD9082_DAC"]["contribution_dBm_per_hz"]) == \
        pytest.approx(10.0, abs=1e-9)
    # The ADC at the other end is untouched by a DAC edit.
    assert result["digitizer"]["adc"] == \
        chain_api.describe()["digitizer"]["adc"]


def test_catalog_says_which_entries_are_endpoints():
    """
    The view has to know a converter is installed rather than appended. That
    comes from the class hierarchy, so it stays right for a converter added to
    the registry later.
    """
    roles = {item["type_id"]: item["role"]
             for group in chain_api.catalog()["categories"]
             for item in group["components"]}
    assert roles["converter.ad9082_dac"] == "dac"
    assert roles["converter.ad9082_adc"] == "adc"
    assert roles["amplifier.asu_3ghz_lna"] == "component"
    assert roles["cable.sma_ss086_cryo"] == "component"


def test_add_then_remove_restores_the_budget():
    original = chain_api.budget("LNA", "input", CARRIER, SPECTRAL)
    added = chain_api.add_component("filter.vhf1320p", {}, "OutFilter")
    assert added["ok"], added.get("error")
    chain_api.remove_component(added["n_components"] - 1)
    restored = chain_api.budget("LNA", "input", CARRIER, SPECTRAL)
    assert restored["total_w_per_hz"] == pytest.approx(
        original["total_w_per_hz"], rel=1e-12)


# -------------------------------------------------------------------- record
def test_the_record_is_saved_with_the_chain():
    """
    Name, notes and metadata cannot be recovered from the components, so if the
    facade can set them it has to be into the file the chain is saved as - not
    into view state that a download would leave behind.
    """
    chain_api.new_chain("Cooldown 12")
    chain_api.set_description("Fridge run 3, sample QD-7 in the mixing chamber")
    result = chain_api.set_metadata({"cooldown": 12, "sample": "QD-7",
                                     "dataset": "/data/2026-08/run3"})
    assert result["ok"], result.get("error")
    assert result["metadata"]["cooldown"] == 12          # an int, not "12"

    saved = json.loads(chain_api.to_json()["json"])
    assert saved["name"] == "Cooldown 12"
    assert saved["description"].startswith("Fridge run 3")
    assert saved["metadata"] == {"cooldown": 12, "sample": "QD-7",
                                 "dataset": "/data/2026-08/run3"}

    reloaded = SignalChain.from_dict(saved)
    assert reloaded.metadata == saved["metadata"]
    assert reloaded.description == saved["description"]


def test_renaming_renames_the_download():
    renamed = chain_api.set_name("  Cooldown 13  ")
    assert renamed["ok"], renamed.get("error")
    assert renamed["name"] == "Cooldown 13"              # trimmed
    assert chain_api.to_json()["suggested_filename"] == "cooldown_13.json"


def test_a_suggested_filename_is_never_a_path():
    """
    The name is free text now that it can be edited, and it is handed to a
    browser download. A slash in it must not become a directory.
    """
    chain_api.set_name("Cooldown 12/A (warm)")
    assert chain_api.to_json()["suggested_filename"] == "cooldown_12_a__warm_.json"


def test_metadata_is_replaced_not_merged():
    chain_api.set_metadata({"cooldown": 12, "operator": "mr"})
    result = chain_api.set_metadata({"cooldown": 13})
    assert result["metadata"] == {"cooldown": 13}


def test_unwritable_metadata_is_refused_at_the_edit():
    """
    Metadata is persisted verbatim, so something json.dumps cannot write makes
    the chain unsaveable. Catching it here means the failure lands on the edit
    that caused it, not on a download months later.
    """
    result = chain_api.set_metadata({"probe": {1, 2}})
    assert result["ok"] is False
    assert "not JSON serializable" in result["error"]
    assert chain_api.to_json()["ok"] is True             # chain still writable


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
    (lambda: chain_api.move_component(0, 999), "to_index 999 out of range"),
    (lambda: chain_api.move_component(-1, 0), "component_index -1 out of range"),
    (lambda: chain_api.budget("NoSuchPlane", "input", CARRIER, SPECTRAL),
     "cannot resolve"),
    (lambda: chain_api.sweep_gain(1e9, 1e9, 10), "must exceed"),
    (lambda: chain_api.sweep_gain(1e9, 2e9, 1), "at least 2 points"),
    (lambda: chain_api.sweep_gain(0.0, 2e9, 10, True), "positive start"),
    (lambda: chain_api.from_json("{not json"), ""),
    (lambda: chain_api.set_digitizer("converter.ad9082_adc"),
     "cannot be the chain's DAC"),
    (lambda: chain_api.set_digitizer(None, "amplifier.asu_3ghz_lna"),
     "cannot be the chain's ADC"),
    (lambda: chain_api.set_digitizer("converter.nope"), "unknown component"),
    (lambda: chain_api.set_digitizer_param("both", "gain_db", 1.0),
     "must be 'dac' or 'adc'"),
    (lambda: chain_api.set_digitizer_param("dac", "nonsense", 1.0),
     "no parameter"),
    (lambda: chain_api.set_digitizer_param("dac", "carrier_power_dbm", 500.0),
     "above the maximum"),
    (lambda: chain_api.set_name("   "), "a chain needs a name"),
    (lambda: chain_api.set_description(None), "description must be a string"),
    (lambda: chain_api.set_metadata([{"cooldown": 12}]),
     "metadata must be an object"),
    (lambda: chain_api.set_metadata({12: "cooldown"}),
     "metadata keys must be strings"),
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


def test_editing_a_converter_the_chain_does_not_have_is_reported():
    """A new chain has no converters, and the browser can still ask."""
    chain_api.new_chain("Bare")
    result = chain_api.set_digitizer_param("dac", "carrier_power_dbm", -10.0)
    assert result["ok"] is False
    assert "this chain has no DAC" in result["error"]


def test_a_budget_on_an_empty_chain_is_reported_not_raised():
    chain_api.new_chain("Bare")
    result = chain_api.budget(0, "input", CARRIER, SPECTRAL)
    assert result["ok"] is False
    assert "cannot resolve" in result["error"]
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
