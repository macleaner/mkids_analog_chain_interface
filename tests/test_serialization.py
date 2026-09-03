"""
Serialization tests.

The central one is test_every_registered_component_round_trips: for every
component in the registry, build it, write it out, read it back, and require
that gain and noise agree across a frequency sweep. That is the test that would
have caught the old format's silent-default substitution, and it covers new
components automatically as they are registered.
"""

import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import registry  # noqa: E402
from component import Component  # noqa: E402
from conftest import CARRIER_FREQS, SPECTRAL_FREQS  # noqa: E402
from signal_chain import FORMAT_VERSION, SignalChain  # noqa: E402


def _same(a, b):
    """Compare gain/noise results, treating NaN as equal to NaN."""
    if a is None or b is None:
        return a is None and b is None
    return np.allclose(np.asarray(a, dtype=float), np.asarray(b, dtype=float),
                       rtol=1e-12, atol=0.0, equal_nan=True)


# Non-default parameter values, so the round trip proves the *values* survive
# rather than accidentally passing because both sides used the defaults.
NON_DEFAULT = {
    "length_m": 2.75,
    "temperature": 77.0,
    "attenuation": -13.5,
    "carrier_power_dbm": -22.5,
    "phase_noise_dbc_per_hz": -97.5,
    "phase_noise_offset_hz": 1000.0,
    "phase_noise_slope_db_per_decade": -20.0,
    "noise_density_dbm_per_hz": -151.5,
    # True, so the non-default pass exercises the noiseless branch. A flag whose
    # non-default value equalled its default would round-trip whatever it was
    # set to, which is the one thing this test is not meant to allow.
    "noiseless": True,
}


def _build(entry, use_defaults):
    params = {}
    for spec in entry.params:
        if use_defaults:
            params[spec.name] = spec.default
        elif spec.choices:
            # Pick a permitted value that differs from the default where possible.
            others = [c for c in spec.choices if c != spec.default]
            params[spec.name] = others[0] if others else spec.default
        else:
            params[spec.name] = NON_DEFAULT.get(spec.name, spec.default)
    return registry.create(entry.type_id, params), params


@pytest.mark.parametrize("type_id", [e.type_id for e in registry.entries()])
@pytest.mark.parametrize("use_defaults", [True, False], ids=["defaults", "non-defaults"])
def test_every_registered_component_round_trips(type_id, use_defaults):
    """A component reloaded from its own serialization behaves identically."""
    entry = registry.resolve(type_id)
    original, params = _build(entry, use_defaults)

    payload = json.loads(json.dumps(original.to_dict()))
    restored = Component.from_dict(payload)

    assert type(restored) is type(original)
    assert restored.params == original.params, "parameters did not survive the round trip"

    for f in CARRIER_FREQS:
        assert _same(original.gain(f), restored.gain(f)), f"gain differs at {f} Hz"
    for f in SPECTRAL_FREQS:
        assert _same(original.noise(1.5e9, f), restored.noise(1.5e9, f)), \
            f"noise differs at spectral {f} Hz"


@pytest.mark.parametrize("type_id", [e.type_id for e in registry.entries()])
def test_serialized_params_match_declared_params(type_id):
    """What gets written is exactly what the component declared - no more, no less."""
    entry = registry.resolve(type_id)
    component, _ = _build(entry, use_defaults=True)
    assert set(component.to_dict()["params"]) == {s.name for s in entry.params}


def test_chain_round_trips_through_a_file(tmp_path, sample_chain):
    """A chain survives save/load with its metadata, labels and digitizer."""
    dac = registry.create("converter.ad9082_dac", {"carrier_power_dbm": -25.0})
    adc = registry.create("converter.ad9082_adc", {})
    sample_chain.set_digitizer(dac, adc)
    sample_chain.description = "Cooldown 2026-08, feedline A"
    sample_chain.metadata = {"cooldown": "CD-17", "dataset": "/data/cd17/noise.h5"}

    path = tmp_path / "chain.json"
    sample_chain.save(str(path))
    loaded = SignalChain.load(str(path))

    assert loaded.load_warnings == []
    assert loaded.name == sample_chain.name
    assert loaded.description == "Cooldown 2026-08, feedline A"
    assert loaded.metadata == {"cooldown": "CD-17", "dataset": "/data/cd17/noise.h5"}
    assert list(loaded.labels) == list(sample_chain.labels)
    assert loaded.dac is not None and loaded.adc is not None
    assert loaded.dac.params["carrier_power_dbm"] == -25.0

    for f in CARRIER_FREQS:
        assert _same(sample_chain.total_gain(f), loaded.total_gain(f))
        assert _same(sample_chain.output_noise(f, 1e3), loaded.output_noise(f, 1e3))


def test_saved_file_records_provenance(tmp_path, sample_chain):
    """The file carries a format version and a save timestamp for bookkeeping."""
    path = tmp_path / "chain.json"
    sample_chain.save(str(path))
    with open(path) as fh:
        data = json.load(fh)
    assert data["format_version"] == FORMAT_VERSION
    assert data["saved_utc"].endswith("+00:00")
    assert [c["label"] for c in data["components"]] == list(sample_chain.labels)


def test_labels_survive_so_analysis_can_reference_a_point(tmp_path, sample_chain):
    """Labels are the stable handle for 'noise at the LNA' across reloads."""
    path = tmp_path / "chain.json"
    sample_chain.save(str(path))
    loaded = SignalChain.load(str(path))
    before = sample_chain.noise_at_point("LNA", 1.5e9, 1e3, at="output")
    after = loaded.noise_at_point("LNA", 1.5e9, 1e3, at="output")
    assert _same(before, after)


# ----------------------------------------------------------------------
# Backward compatibility with the two pre-registry GUI formats
# ----------------------------------------------------------------------

def test_loads_legacy_bare_list_format(tmp_path):
    """The oldest format was a bare JSON list of components keyed by class name."""
    legacy = [
        {"class": "Attenuator", "description": "Atten",
         "parameters": {"attenuation": -10, "temperature": 300}},
        {"class": "ASU_3GHz_LNA", "description": "LNA", "parameters": {}},
    ]
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(legacy))

    chain = SignalChain.load(str(path))
    assert len(chain.components) == 2
    assert chain.components[0].params == {"attenuation": -10.0, "temperature": 300.0}
    assert chain.total_gain(1.5e9) == pytest.approx(20.0)


def _legacy_digitizer_file(tmp_path, name, digitizer):
    path = tmp_path / name
    path.write_text(json.dumps({
        "digitizer": digitizer,
        "components": [
            {"class": "Attenuator", "description": "Atten",
             "parameters": {"attenuation": -10, "temperature": 300}},
        ],
    }))
    return str(path)


def test_loads_legacy_flat_digitizer_format(tmp_path):
    """The intermediate format stored a flat digitizer-panel config dict."""
    chain = SignalChain.load(_legacy_digitizer_file(
        tmp_path, "legacy2.json",
        {"model": "AD9082", "carrier_power_dbm": -30.0,
         "dac_gain_db": 0.0, "adc_gain_db": 0.0}))

    assert chain.dac is not None and chain.adc is not None
    assert chain.dac.params["carrier_power_dbm"] == -30.0
    # The gains that format recorded are gone from the model, so they are gone
    # from what was rebuilt - and said out loud rather than dropped quietly.
    assert "gain_db" not in chain.dac.params
    assert "gain_db" not in chain.adc.params
    assert sum("gain_db" in w for w in chain.load_warnings) == 2


def test_a_legacy_file_with_real_converter_gain_is_refused(tmp_path):
    """
    1 dB of DAC gain is a statement about hardware that this model cannot
    express any more. Rebuilding the converter without it would hand back a
    chain 1 dB quieter than the file describes with nothing marking it, so that
    converter is not rebuilt at all and the reason is recorded.

    The rest of the file still loads. A refused converter must not cost the
    user the components they can still see and fix.
    """
    chain = SignalChain.load(_legacy_digitizer_file(
        tmp_path, "legacy3.json",
        {"model": "AD9082", "carrier_power_dbm": -30.0,
         "dac_gain_db": 1.0, "adc_gain_db": 0.0}))

    assert chain.dac is None
    assert chain.adc is not None            # its own gain was 0, so it loads
    assert len(chain.components) == 1
    assert any("could not load DAC" in w and "1.0" in w
               for w in chain.load_warnings), chain.load_warnings


def test_class_names_still_resolve_as_aliases():
    """Old files reference Python class names; those must remain valid ids."""
    assert registry.resolve("SMA_SS086_cryo").type_id == "cable.sma_ss086_cryo"
    assert registry.resolve("Attenuator").type_id == "attenuator"


# ----------------------------------------------------------------------
# Retired parameters
# ----------------------------------------------------------------------
# `aliases` keeps a renamed class loadable; `retired` does the same job for a
# removed parameter. Every converter used to declare `gain_db`, so every chain
# file saved before it went records it - the case these pin.

RETIRED_CONVERTERS = ["converter.ad9082_dac", "converter.ad9082_adc",
                      "converter.generic_dac", "converter.generic_adc"]


@pytest.mark.parametrize("type_id", RETIRED_CONVERTERS)
def test_a_retired_parameter_loads_at_its_old_default_with_a_warning(type_id):
    """
    A file recording the value the parameter used to default to describes the
    component the model still builds, so it loads - but the name is gone, and a
    format whose worst failure is silent substitution says so.
    """
    entry = registry.resolve(type_id)
    params = {s.name: s.default for s in entry.params}
    warnings = []
    component = registry.create(type_id, {**params, "gain_db": 0.0},
                                warnings=warnings)
    assert "gain_db" not in component.params
    assert not hasattr(component, "gain_db")
    assert any("gain_db" in w and "no longer exists" in w for w in warnings)


@pytest.mark.parametrize("type_id", RETIRED_CONVERTERS)
def test_a_retired_parameter_with_a_real_value_is_refused(type_id):
    """
    3 dB of converter gain says something about hardware the model can no
    longer express. Loading it as 0 dB would hand back a chain 3 dB quieter
    than the file describes with nothing marking it, which is the substitution
    this format exists to prevent - so it is refused, and the message says
    where the gain should go instead.
    """
    entry = registry.resolve(type_id)
    params = {s.name: s.default for s in entry.params}
    with pytest.raises(ValueError, match="no longer exists"):
        registry.create(type_id, {**params, "gain_db": 3.0})


@pytest.mark.parametrize("type_id", RETIRED_CONVERTERS)
def test_a_retired_parameter_is_not_offered_as_a_parameter(type_id):
    """
    Accepted from a file is not the same as declared. A retired name must not
    reach a view, or the GUI would build an input for a knob that does not
    exist, and `to_dict` must not write it back out.
    """
    entry = registry.resolve(type_id)
    assert "gain_db" not in {spec.name for spec in entry.params}
    assert "gain_db" in {spec.name for spec in entry.retired}
    component = registry.create(type_id,
                                {s.name: s.default for s in entry.params})
    assert "gain_db" not in component.to_dict()["params"]


def test_a_saved_file_that_records_converter_gain_still_loads(tmp_path):
    """
    The realistic case: a chain saved while converters had a gain knob, at the
    0 dB it defaulted to. The whole file has to come back - components, labels
    and both converters - with the retired name noted and nothing else changed.
    """
    data = {
        "format_version": FORMAT_VERSION,
        "name": "Saved earlier",
        "components": [{"type": "attenuator", "name": "InputAtten",
                        "params": {"attenuation": -10.0,
                                   "temperature": 300.0}}],
        "labels": {"InputAtten": 0},
        "digitizer": {
            "dac": {"type": "converter.ad9082_dac", "name": "AD9082_DAC",
                    "params": {"carrier_power_dbm": -10.0, "gain_db": 0.0}},
            "adc": {"type": "converter.ad9082_adc", "name": "AD9082_ADC",
                    "params": {"gain_db": 0.0}},
        },
    }
    path = tmp_path / "with_converter_gain.json"
    path.write_text(json.dumps(data))

    chain = SignalChain.load(str(path))
    assert chain.dac is not None and chain.adc is not None
    assert chain.dac.params == {"carrier_power_dbm": -10.0}
    assert chain.total_gain(1.5e9) == pytest.approx(-10.0)
    assert sum("gain_db" in w for w in chain.load_warnings) == 2

    # Saving it again writes the current format, so the warning is not sticky.
    again = tmp_path / "resaved.json"
    chain.save(str(again))
    assert SignalChain.load(str(again)).load_warnings == []


def test_a_name_cannot_be_declared_and_retired_at_once():
    """A parameter that is both would be read by whichever check ran first."""
    from registry import ParamSpec, RetiredParam, register

    with pytest.raises(ValueError, match="both a parameter and a retired one"):
        @register("test.clashing_retired", category="Test",
                  params=(ParamSpec("gain_db", default=0.0),),
                  retired=(RetiredParam("gain_db", 0.0),))
        class _Clashing:
            pass


# ----------------------------------------------------------------------
# Failure modes must be loud
# ----------------------------------------------------------------------

def test_unknown_component_type_is_reported_not_ignored(tmp_path):
    data = {"format_version": FORMAT_VERSION,
            "components": [{"type": "cable.does_not_exist", "params": {}}]}
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data))

    chain = SignalChain.load(str(path))
    assert chain.components == []
    assert any("does_not_exist" in w for w in chain.load_warnings)


def test_unexpected_parameter_is_rejected():
    """A stale parameter name must not be silently dropped."""
    with pytest.raises(ValueError, match="unexpected parameter"):
        registry.create("attenuator",
                        {"attenuation": -10, "temperature": 300, "lenght_m": 1.0})


def test_missing_parameter_records_a_warning():
    """Falling back to a default is allowed, but never silent."""
    warnings = []
    component = registry.create("attenuator", {"attenuation": -10},
                                warnings=warnings)
    assert component.params["temperature"] == 300.0
    assert any("temperature" in w for w in warnings)


def test_out_of_range_parameter_is_rejected():
    with pytest.raises(ValueError, match="above the maximum"):
        registry.create("attenuator", {"attenuation": 50, "temperature": 300})


@pytest.mark.parametrize("written,expected", [
    (True, True), (False, False),
    ("true", True), ("false", False),
    ("True", True), (" FALSE ", False),
    (1, True), (0, False),
])
def test_a_boolean_parameter_reads_as_what_the_file_says(written, expected):
    """
    A flag is the one parameter type where a coercion mistake inverts the
    record instead of perturbing it, so the accepted spellings are pinned.
    """
    component = registry.create("converter.generic_adc", {
        "noise_density_dbm_per_hz": -140.0, "noiseless": written})
    assert component.params["noiseless"] is expected


@pytest.mark.parametrize("written", ["off", "nope", "", "2", 2, 1.0, None])
def test_a_boolean_parameter_refuses_anything_it_cannot_read(written):
    """
    ``bool("off")`` is True, and a chain file saying ``noiseless: "off"`` that
    loaded as noiseless=True would be the format's original failure - a saved
    setting silently becoming its opposite. Refused instead.
    """
    with pytest.raises(ValueError, match="expects bool"):
        registry.create("converter.generic_adc", {
            "noise_density_dbm_per_hz": -140.0, "noiseless": written})


def test_a_split_parameter_group_is_refused_at_registration():
    """
    Grouping is presentation, but a group interrupted by an outside parameter
    becomes two sub-boxes with one heading - so it is caught where the fix is to
    move one line, not left to be noticed in the GUI.
    """
    from registry import ParamSpec, _check_groups

    split = (ParamSpec("a", default=0.0, group="Noise"),
             ParamSpec("b", default=0.0),
             ParamSpec("c", default=0.0, group="Noise"))
    with pytest.raises(ValueError, match="more than one run"):
        _check_groups("test.split", split)

    # Contiguous, and interleaving two groups back to back, are both fine.
    _check_groups("test.ok", (
        ParamSpec("a", default=0.0),
        ParamSpec("b", default=0.0, group="Noise"),
        ParamSpec("c", default=0.0, group="Noise"),
        ParamSpec("d", default=0.0, group="Levels"),
        ParamSpec("e", default=0.0)))


def test_non_serializable_parameter_is_rejected_at_construction():
    """The old format dropped these at save time; now they cannot be built."""
    from hardware_models import Attenuator

    with pytest.raises(TypeError, match="cannot be serialized"):
        Attenuator(attenuation=np.array([1.0, 2.0]), temperature=300)


def test_unregistered_component_cannot_be_serialized():
    class Rogue(Component):
        def gain(self, frequency):
            return 0.0

    with pytest.raises(TypeError, match="not registered"):
        Rogue().to_dict()
