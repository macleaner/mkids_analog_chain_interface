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
from conftest import CARRIER_FREQS, OFFSET_FREQS  # noqa: E402
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
    "gain_db": 3.25,
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
    for f in OFFSET_FREQS:
        assert _same(original.noise(f), restored.noise(f)), f"noise differs at {f} Hz"


@pytest.mark.parametrize("type_id", [e.type_id for e in registry.entries()])
def test_serialized_params_match_declared_params(type_id):
    """What gets written is exactly what the component declared - no more, no less."""
    entry = registry.resolve(type_id)
    component, _ = _build(entry, use_defaults=True)
    assert set(component.to_dict()["params"]) == {s.name for s in entry.params}


def test_chain_round_trips_through_a_file(tmp_path, sample_chain):
    """A chain survives save/load with its metadata, labels and digitizer."""
    dac = registry.create("converter.ad9082_dac", {"carrier_power_dbm": -25.0})
    adc = registry.create("converter.ad9082_adc", {"gain_db": 0.0})
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


def test_loads_legacy_flat_digitizer_format(tmp_path):
    """The intermediate format stored a flat digitizer-panel config dict."""
    legacy = {
        "digitizer": {"model": "AD9082", "carrier_power_dbm": -30.0,
                      "dac_gain_db": 1.0, "adc_gain_db": 2.0},
        "components": [
            {"class": "Attenuator", "description": "Atten",
             "parameters": {"attenuation": -10, "temperature": 300}},
        ],
    }
    path = tmp_path / "legacy2.json"
    path.write_text(json.dumps(legacy))

    chain = SignalChain.load(str(path))
    assert chain.dac is not None and chain.adc is not None
    assert chain.dac.params["carrier_power_dbm"] == -30.0
    assert chain.dac.params["gain_db"] == 1.0
    assert chain.adc.params["gain_db"] == 2.0


def test_class_names_still_resolve_as_aliases():
    """Old files reference Python class names; those must remain valid ids."""
    assert registry.resolve("SMA_SS086_cryo").type_id == "cable.sma_ss086_cryo"
    assert registry.resolve("Attenuator").type_id == "attenuator"


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
