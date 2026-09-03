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
from component import PassiveComponent
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
        chain_api.component_specs("amplifier.asu_3ghz_lna"),
        chain_api.presets(),
        chain_api.describe(),
        chain_api.budget("LNA", "input", CARRIER, SPECTRAL),
        chain_api.sweep_gain(1e8, 3e9, 21),
        chain_api.sweep_noise(CARRIER, 1e2, 1e6, 11, True, True),
        chain_api.to_json(),
        chain_api.notebook(),
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


def test_copy_component_inserts_a_twin_after_the_original():
    """
    Copying is for the chain that has the same hardware in it twice, so the
    copy has to carry the original's *values* - not the model's defaults - and
    land next to it. ``chain.labels`` maps label -> index, so the insertion
    also has to shift every index at or above the new slot up one, the mirror
    of what a removal does.
    """
    result = chain_api.copy_component(2)              # CryoCable, 0.5 m at 4 K
    assert result["ok"], result.get("error")
    assert [s["label"] for s in result["stages"]] == [
        "AD9082_DAC", "InputAtten", "WarmCable_In", "CryoCable", "CryoCable2",
        "ColdAtten", "LNA", "ReturnCable", "WarmAmp1", "WarmAmp2", "AD9082_ADC",
    ]
    original, copy = [s for s in result["stages"]
                      if s["label"] in ("CryoCable", "CryoCable2")]
    assert copy["type_id"] == original["type_id"]
    assert copy["params"] == original["params"] == {"length_m": 0.5,
                                                    "temperature": 4.0}
    labels = chain_api._CHAIN.labels
    assert labels["CryoCable"] == 2 and labels["CryoCable2"] == 3
    for label, index in labels.items():
        assert chain_api._CHAIN._get_label_for_index(index) == label


def test_a_copy_is_a_second_component_not_the_same_one_twice():
    """
    The copy is built through the registry rather than by copying the object,
    so the two stages are the same model and not one component sitting in the
    chain at two indices. If they were aliased, editing either would silently
    edit both - and a chain with two runs of cable at two temperatures could
    not be described at all.
    """
    assert chain_api.copy_component(2)["ok"]          # CryoCable -> CryoCable2
    components = chain_api._CHAIN.components
    assert components[2] is not components[3]

    result = chain_api.set_param(3, "temperature", 50.0)
    assert result["ok"], result.get("error")
    stages = {s["label"]: s for s in result["stages"]}
    assert stages["CryoCable2"]["params"]["temperature"] == 50.0
    assert stages["CryoCable"]["params"]["temperature"] == 4.0


def test_a_copied_stage_is_in_the_cascade():
    """
    A second pad is a second 20 dB of loss. A copy that only showed up in the
    stage list would leave the budget describing a chain that no longer exists.
    """
    span = (CARRIER, CARRIER * 1.0001, 2)
    before = chain_api.sweep_gain(*span)["gain_db"][0]
    assert chain_api.copy_component(3)["ok"]          # ColdAtten, -20 dB
    after = chain_api.sweep_gain(*span)["gain_db"][0]
    assert after - before == pytest.approx(-20.0, abs=1e-9)


def test_a_copy_takes_the_next_free_number_in_its_family():
    """
    Labels are unique within a chain, so the copy cannot reuse the original's,
    and counting up from the original's own number can land on one already in
    use - here WarmAmp1's copy cannot be WarmAmp2.
    """
    result = chain_api.copy_component(6)              # WarmAmp1, WarmAmp2 taken
    assert result["ok"], result.get("error")
    assert [s["label"] for s in result["stages"]][-4:] == [
        "WarmAmp1", "WarmAmp3", "WarmAmp2", "AD9082_ADC"]


def test_an_unregistered_component_is_refused_rather_than_shallow_copied():
    """
    A component a script appended directly cannot be rebuilt from a type id,
    and putting the same object in the chain twice would alias two stages. The
    call says so instead.
    """
    class BespokeThing(PassiveComponent):
        def gain(self, frequency):
            return 0.0

    chain_api._CHAIN.add_component(BespokeThing(), label="Mystery")
    result = chain_api.copy_component(len(chain_api._CHAIN.components) - 1)
    assert not result["ok"]
    assert "not registered" in result["error"]
    assert len(chain_api._CHAIN.components) == 9      # nothing was added


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


def test_stages_report_the_model_name_the_library_lists():
    """
    A label is free text, so it cannot be relied on to say what a stage is:
    "CryoCable" could be any of nine cable models. ``type_label`` is the one
    part of a stage's identity the user does not choose, and it has to be the
    same string the component library offers, or the chain view and the library
    would name the same model two different ways.
    """
    stages = {s["label"]: s for s in chain_api.describe()["stages"]}
    assert stages["CryoCable"]["type_label"] == \
        registry.resolve("cable.sma_ss086_cryo").label
    assert stages["ColdAtten"]["type_label"] == "Attenuator"
    assert stages["AD9082_DAC"]["type_label"] == "AD9082 DAC"


def test_an_unregistered_component_still_says_what_it_is():
    """
    Not every component in a chain came from the registry - a script can append
    one directly. Its stage still needs a model name, so the class name stands
    in rather than the view being handed None to render.
    """
    class BespokeThing(PassiveComponent):
        def gain(self, frequency):
            return 0.0

    chain_api._CHAIN.add_component(BespokeThing(), label="Mystery")
    stage, = [s for s in chain_api.describe()["stages"]
              if s["label"] == "Mystery"]
    assert stage["type_id"] is None
    assert stage["type_label"] == "BespokeThing"


def test_a_component_added_without_a_label_is_named_for_its_family():
    """
    Every component needs a label the moment it is added - it is what a budget
    refers to and what the file records - so the browser adds one with none and
    gets a generic name back. It is named for the family, not the position:
    a reorder moves a component and its label together, so a number that meant
    "third in the chain" would be wrong as soon as anything moved.
    """
    result = chain_api.add_component("cable.sma_generic")
    assert result["ok"], result.get("error")
    assert result["stages"][-2]["label"] == "Cable1"          # before the ADC

    assert chain_api.add_component("cable.rg58c")["ok"]
    assert chain_api.add_component("attenuator")["ok"]
    added = chain_api.add_component("amplifier.zx60_3018g_plus")
    assert [s["label"] for s in added["stages"]][-5:-1] == [
        "Cable1", "Cable2", "Attenuator1", "Amplifier1"]


def test_a_generated_label_never_collides_with_one_in_use():
    """
    Two stages cannot share a label: ``chain.labels`` maps label -> index, so a
    reused name would silently repoint at the newer component and leave the
    older one unaddressable. The counter therefore looks at what the chain
    already has, including names the user typed and gaps left by a removal.
    """
    assert chain_api.add_component("attenuator", None, "Attenuator2")["ok"]
    first = chain_api.add_component("attenuator")
    assert first["stages"][-2]["label"] == "Attenuator1"
    second = chain_api.add_component("attenuator")
    assert second["stages"][-2]["label"] == "Attenuator3"     # 2 is taken

    labels = chain_api._CHAIN.labels
    assert len(labels) == len(chain_api._CHAIN.components)

    # A removal frees its name for the next component added.
    assert chain_api.remove_component(labels["Attenuator1"])["ok"]
    assert chain_api.add_component("attenuator")["stages"][-2]["label"] \
        == "Attenuator1"


def test_an_explicit_label_is_never_overridden():
    """A generated name is a fallback, not a rename."""
    result = chain_api.add_component("attenuator", {}, "Mixing_Chamber_Pad")
    assert result["stages"][-2]["label"] == "Mixing_Chamber_Pad"


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
    assert roles["converter.generic_dac"] == "dac"
    assert roles["converter.generic_adc"] == "adc"
    assert roles["amplifier.asu_3ghz_lna"] == "component"
    assert roles["cable.sma_ss086_cryo"] == "component"


def test_the_catalog_carries_the_groups_a_card_is_laid_out_from():
    """
    The view opens a sub-box when a parameter's ``group`` changes, so the schema
    has to carry it - and carry it in an order where that works. The Generic
    DAC's four noise knobs are one run, with the carrier power and the gain
    outside it: what the DAC puts out is not part of its skirt.
    """
    entry = next(item for group in chain_api.catalog()["categories"]
                 for item in group["components"]
                 if item["type_id"] == "converter.generic_dac")
    groups = [(p["name"], p["group"]) for p in entry["params"]]
    assert groups == [
        ("carrier_power_dbm", None),
        ("phase_noise_dbc_per_hz", "Noise parameters"),
        ("phase_noise_offset_hz", "Noise parameters"),
        ("phase_noise_slope_db_per_decade", "Noise parameters"),
        ("noiseless", "Noise parameters"),
        ("gain_db", None),
    ]


def test_every_declared_group_is_one_unbroken_run():
    """
    A group split in two renders as two sub-boxes under one heading, which reads
    as two different things sharing a name. ``registry.register`` refuses that at
    import; this asserts the whole catalog is in fact laid out that way, for the
    view that renders straight down the list.
    """
    for category in chain_api.catalog()["categories"]:
        for item in category["components"]:
            runs = []
            for param in item["params"]:
                if not runs or runs[-1] != param["group"]:
                    runs.append(param["group"])
            named = [g for g in runs if g is not None]
            assert len(named) == len(set(named)), (
                f"{item['type_id']} renders a group twice: {runs}")


def test_a_generic_digitizer_can_replace_the_modelled_one():
    """
    The point of the generic converters: evaluate this chain against an
    arbitrary digitizer, stated rather than fitted. They install through the
    same call as any other converter and appear in the budget as any other
    source.
    """
    result = chain_api.set_digitizer(
        "converter.generic_dac", "converter.generic_adc",
        {"carrier_power_dbm": -10.0, "phase_noise_dbc_per_hz": -80.0,
         "phase_noise_offset_hz": 1000.0,
         "phase_noise_slope_db_per_decade": -10.0,
         "noiseless": False, "gain_db": 0.0},
        {"noise_density_dbm_per_hz": -145.0, "noiseless": False,
         "gain_db": 0.0})
    assert result["ok"], result.get("error")
    assert result["digitizer"]["dac"]["params"]["phase_noise_dbc_per_hz"] == -80.0

    rows = chain_api.budget("LNA", "input", CARRIER, SPECTRAL)["rows"]
    sources = {row["source"] for row in rows}
    assert {"GenericDAC", "GenericADC"} <= sources


def test_a_noiseless_digitizer_leaves_the_components_to_be_judged():
    """
    Noiseless is not "turned down": the two converters must be *absent* from the
    budget, and the budget identical to the one for a chain with no converters
    installed at all. That is the question the flag exists to answer - how good
    is this chain, separately from how good the digitizer on each end is.
    """
    ideal = {"noiseless": True, "gain_db": 0.0}
    chain_api.set_digitizer(
        "converter.generic_dac", "converter.generic_adc",
        {"carrier_power_dbm": -10.0, "phase_noise_dbc_per_hz": -80.0,
         "phase_noise_offset_hz": 1000.0,
         "phase_noise_slope_db_per_decade": -10.0, **ideal},
        {"noise_density_dbm_per_hz": -145.0, **ideal})
    with_ideal = chain_api.budget("LNA", "input", CARRIER, SPECTRAL)
    assert {"GenericDAC", "GenericADC"}.isdisjoint(
        row["source"] for row in with_ideal["rows"])

    # Both ends removed. The generic converters default to 0 dB of gain, so the
    # gain from the chain input to the LNA is the same either way and the two
    # totals are comparable at all - which is why this asserts equality rather
    # than merely "smaller than with a real digitizer".
    chain_api.set_digitizer()
    without = chain_api.budget("LNA", "input", CARRIER, SPECTRAL)
    assert with_ideal["total_w_per_hz"] == pytest.approx(
        without["total_w_per_hz"], rel=1e-12)


# ------------------------------------------------------------ component specs
def test_every_registered_model_can_describe_itself():
    """
    The library panel calls this for whatever entry is clicked, so a model that
    cannot be probed is a blank panel with an error toast, not a degraded one.
    Every entry, including the converters the library itself does not list.
    """
    for entry in registry.entries():
        spec = chain_api.component_specs(entry.type_id)
        assert spec["ok"], (entry.type_id, spec.get("error"))
        assert roundtrips(spec), entry.type_id
        assert spec["label"] == entry.label
        assert spec["span_to_hz"] > spec["span_from_hz"]
        assert len(spec["gain_db"]) == len(spec["freq_hz"])


def test_specs_report_the_models_own_numbers():
    """
    A spec panel that disagreed with the chain the component then joins would be
    worse than no panel. Both come from the component, so assert they are the
    same call and not a second path.
    """
    component = registry.create("amplifier.zx60_3018g_plus")
    spec = chain_api.component_specs("amplifier.zx60_3018g_plus",
                                     carrier_hz=CARRIER, spectral_hz=SPECTRAL)
    assert spec["gain_at_carrier_db"] == pytest.approx(
        float(component.gain(CARRIER)), rel=1e-12)
    assert spec["noise"]["w_per_hz"] == pytest.approx(
        float(component.noise(CARRIER, SPECTRAL)), rel=1e-12)


def test_a_datasheet_span_is_found_by_probing_the_model():
    """
    The sweep runs over the band a model answers for, which is discovered by
    asking it rather than by reading its interpolator's knots. These two
    filters tabulate different spans, and the edges are the datasheet's.
    """
    low_pass = chain_api.component_specs("filter.vlf6700p")
    assert low_pass["span_source"] == "model"
    assert low_pass["span_from_hz"] == pytest.approx(50e6, rel=1e-6)
    assert low_pass["span_to_hz"] == pytest.approx(19.89e9, rel=1e-6)

    high_pass = chain_api.component_specs("filter.vhf1320p")
    assert high_pass["span_from_hz"] == pytest.approx(1e6, rel=1e-6)
    assert high_pass["span_to_hz"] == pytest.approx(3.7e9, rel=1e-6)


def test_a_model_that_answers_everywhere_uses_the_span_it_was_given():
    """
    An attenuator has no band of its own, so there is nothing to discover and
    the caller's span is used - and the payload says which, because "0.1-3 GHz"
    means something different in the two cases.
    """
    spec = chain_api.component_specs("attenuator", start_hz=2e8, stop_hz=4e9)
    assert spec["span_source"] == "requested"
    assert (spec["span_from_hz"], spec["span_to_hz"]) == (2e8, 4e9)
    assert spec["gain_flat"] is True
    assert spec["gain_min_db"] == pytest.approx(-10.0)


# -------------------------------------------------------- extrapolation flags
def test_a_sweep_past_the_datasheets_has_a_curve_and_says_which_stages():
    """
    The case this exists for: a sweep to 12 GHz of a chain whose amplifiers are
    tabulated to 3 GHz. Every point has a gain - one NaN in the dB sum used to
    blank the curve from 3 GHz up - and every stage that ran out of data is
    named, with the band it does cover and the part of the sweep it does not.
    """
    result = chain_api.sweep_gain(1e8, 12e9, 41)
    assert result["ok"], result.get("error")
    assert all(gain is not None for gain in result["gain_db"])

    flagged = {stage["label"]: stage for stage in result["extrapolated"]}
    # The two ZX60s and the ASU LNA stop at 3 GHz; both cryo cables at 10 GHz.
    # The warm cable (0-18 GHz), the attenuators and the converters cover the
    # sweep and so are not in the list at all.
    assert set(flagged) == {"LNA", "WarmAmp1", "WarmAmp2",
                            "CryoCable", "ReturnCable"}
    assert flagged["LNA"]["span_to_hz"] == pytest.approx(3e9)
    assert flagged["LNA"]["regions_hz"] == [[pytest.approx(3e9),
                                             pytest.approx(12e9)]]
    assert flagged["CryoCable"]["regions_hz"] == [[pytest.approx(10e9),
                                                   pytest.approx(12e9)]]
    # Enough to draw and to name: the model's label, not just an index.
    assert flagged["LNA"]["type_label"] == "ASU 3 GHz LNA (~6 K)"
    assert roundtrips(result)


def test_nothing_is_flagged_where_every_stage_has_data():
    """
    An empty list is a statement, not a missing feature: inside every stage's
    band the whole curve is measured, and a view that shades nothing there is
    right to.
    """
    assert chain_api.sweep_gain(5e8, 2.5e9, 21)["extrapolated"] == []


def test_a_flagged_region_is_cut_at_the_band_edge_not_at_a_sample():
    """
    The edge is a datasheet figure; the grid is only where this sweep happened
    to look. A region reported to the nearest sampled frequency would move when
    the point count changed, and would shade measured data or leave estimated
    data unshaded depending on which way it rounded.
    """
    coarse = chain_api.sweep_gain(1e8, 12e9, 7)["extrapolated"]
    fine = chain_api.sweep_gain(1e8, 12e9, 401)["extrapolated"]
    assert coarse == fine
    lna = next(s for s in coarse if s["label"] == "LNA")
    assert lna["regions_hz"][0][0] == pytest.approx(3e9)     # not 2 or 4 GHz


def test_a_sweep_below_a_band_is_flagged_at_the_bottom_end():
    """
    Both ends, and both at once. The CMT LNA is tabulated from 1 GHz, so a
    sweep from 100 MHz leaves its band at the bottom - and a sweep that starts
    below and ends above one band gets two regions for that stage.
    """
    assert chain_api.add_component("amplifier.cmt_citcryo1_12d", {}, "CMT")["ok"]

    below = {s["label"]: s for s in
             chain_api.sweep_gain(1e8, 2e9, 21)["extrapolated"]}
    assert below["CMT"]["regions_hz"] == [[pytest.approx(1e8), pytest.approx(1e9)]]

    both = {s["label"]: s for s in
            chain_api.sweep_gain(1e8, 20e9, 21)["extrapolated"]}
    assert both["CMT"]["regions_hz"] == [[pytest.approx(1e8), pytest.approx(1e9)],
                                         [pytest.approx(14e9), pytest.approx(20e9)]]


def test_a_sloped_model_is_not_reported_as_flat():
    """``gain_flat`` decides how the view quotes a gain, so it has to be the
    model's own answer and not a comparison of two rounded figures."""
    spec = chain_api.component_specs("cable.sma_ss086_cryo", {"length_m": 2.0})
    assert spec["gain_flat"] is False
    assert spec["gain_min_db"] < spec["gain_max_db"]


def test_noise_kind_separates_a_skirt_from_a_temperature():
    """
    A noise temperature only means anything for a source that is white near the
    carrier. The AD9082's phase noise falls about 10 dB per decade of offset, so
    quoting it as one temperature would be wrong however it were rounded - and
    the powers involved are around 1e-12 W/Hz, small enough that a comparison
    made on absolute tolerance calls every source in the library flat.
    """
    dac = chain_api.component_specs("converter.ad9082_dac")
    assert dac["noise"]["kind"] == "spectral"

    for type_id in ("attenuator", "amplifier.asu_3ghz_lna",
                    "converter.ad9082_adc"):
        assert chain_api.component_specs(type_id)["noise"]["kind"] == "flat", \
            type_id

    # Lossy, but not a source: a filter passes noise on without adding any.
    assert chain_api.component_specs("filter.vhf1910p")["noise"]["kind"] == "none"


def test_a_temperature_is_quoted_where_the_model_refers_it():
    """
    Whether a figure stands at the component's input or its output decides
    whether its own gain acts on it, so the panel has to be able to say which.
    """
    amplifier = chain_api.component_specs("amplifier.asu_3ghz_lna")
    assert amplifier["noise"]["referred_to"] == "input"
    assert amplifier["noise"]["temperature_k"] == pytest.approx(6.0, rel=1e-3)

    attenuator = chain_api.component_specs("attenuator",
                                           {"attenuation": -20.0,
                                            "temperature": 4.0})
    assert attenuator["noise"]["referred_to"] == "output"
    assert attenuator["noise"]["temperature_k"] == pytest.approx(4.0, rel=1e-9)


def test_describing_a_component_does_not_touch_the_chain():
    """The panel is read-only: looking at a model must not edit the record."""
    before = chain_api.to_json()["json"]
    for entry in registry.entries():
        chain_api.component_specs(entry.type_id)
    assert chain_api.to_json()["json"] == before


def test_specs_default_the_parameters_and_say_what_they_used():
    """
    Called with no parameters, this describes the entry as a double-click would
    install it - so the figures are the defaults', and the payload reports them
    rather than leaving that to be assumed.
    """
    spec = chain_api.component_specs("attenuator")
    assert spec["params_used"] == {"attenuation": -10.0, "temperature": 300.0}

    edited = chain_api.component_specs("attenuator", {"attenuation": -3.0})
    assert edited["params_used"]["attenuation"] == -3.0
    assert edited["gain_min_db"] == pytest.approx(-3.0)


def test_a_bad_parameter_is_reported_not_raised():
    """Same validation as an edit, and the same shape of failure."""
    result = chain_api.component_specs("attenuator", {"attenuation": 50.0})
    assert result["ok"] is False
    assert "above the maximum" in result["error"]


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
