"""
Characterization ("golden value") tests.

These pin the *current* numerical output of every component so that a refactor
cannot silently change results. They deliberately assert on a stored snapshot
rather than on physically-derived expectations: their job is to detect change,
not to certify correctness.

Some snapshotted values are known to be physically wrong - see KNOWN_BAD below.
Those entries are recorded so the refactor is provably behaviour-preserving, and
are flagged so nobody mistakes the snapshot for a statement of correctness.

To regenerate after an *intentional* numerical change:
    python tests/test_characterization.py --regenerate
and review the diff to tests/data/golden_components.json carefully.
"""

import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import CARRIER_FREQS, SPECTRAL_FREQS  # noqa: E402

# Held constant while sweeping the other axis.
REF_CARRIER = 1.5e9
REF_SPECTRAL = 1.0e3

GOLDEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "data", "golden_components.json")

# Constructor arguments used to instantiate each component for snapshotting.
# Every concrete component in hardware_models must appear here, so that adding a
# component without a snapshot fails test_every_component_is_characterized.
COMPONENT_SPECS = {
    "AD9082_DAC": {"carrier_power_dbm": -20.0, "gain_db": 0.0},
    "AD9082_ADC": {"gain_db": 0.0},
    "ASU_3GHz_LNA": {},
    "ZX60_3018Gplus": {},
    "CryoElec_LNA": {},
    "CMT_CITCRYO1_12D": {},
    "LNF_LNC1_5_6B": {},
    "Attenuator": {"attenuation": -10, "temperature": 300},
    "SMA_cables": {"length_m": 0.5},
    "SMA_CuNi_cryo": {"length_m": 0.5, "temperature": 4},
    "SMA_CuNi086_cryo": {"length_m": 0.5, "temperature": 4},
    "SMA_SS086_cryo": {"length_m": 0.5, "temperature": 4},
    "SMA_SS219_cryo": {"length_m": 0.5, "temperature": 4},
    "SMA_NbTi086_cryo": {"length_m": 0.5, "temperature": 4},
    "SMA_FM_F141_cables": {"length_m": 0.5},
    "SMA_RG58C_cables": {"length_m": 0.5},
    "SMA_RG174A_cables": {"length_m": 0.5},
    "FilterHP_VHF1320p": {},
    "FilterHP_VHF1760p": {},
    "FilterHP_VHF1910p": {},
    "FilterHP_VHF5050p": {},
    "FilterLP_VLF6700p": {},
    "BCB029_SS034_cryo": {"length_m": 0.5, "temperature": 4},
    "BCB014_SS085_cryo": {"length_m": 0.5, "temperature": 4},
    "BCB024_SP034_cryo": {"length_m": 0.5, "temperature": 4},
    "BCB012_NbTi034_cryo": {"length_m": 0.5, "temperature": 4},
}

# Components whose snapshot records physically wrong behaviour. Documented here
# so the snapshot is never mistaken for a correctness claim. See the notes in
# the repo issue list; fixing these is a deliberate, separate change.
KNOWN_BAD = {}


def _jsonable(value):
    """Normalize a gain/noise result into something JSON can round-trip."""
    if value is None:
        return None
    arr = np.asarray(value, dtype=float)
    if arr.ndim == 0:
        v = float(arr)
        return None if np.isnan(v) else v
    return [None if np.isnan(float(v)) else float(v) for v in arr.ravel()]


def _snapshot_component(name, kwargs):
    """Build a component and record its gain/noise, or the error it raised."""
    import hardware_models as hm

    cls = getattr(hm, name)
    try:
        obj = cls(**kwargs)
    except Exception as exc:  # construction itself is part of the behaviour
        return {"construct_error": f"{type(exc).__name__}: {exc}"}

    record = {"gain": {}, "noise": {}}
    for f in CARRIER_FREQS:
        try:
            record["gain"][repr(f)] = _jsonable(obj.gain(f))
        except Exception as exc:
            record["gain"][repr(f)] = f"ERROR {type(exc).__name__}"

    # noise() depends on both frequencies, so sweep each axis with the other
    # held at a reference value. A model that mixes the two axes up shows a
    # change on both sweeps.
    noise_attr = getattr(obj, "noise", None)
    if noise_attr is None:
        record["noise"] = None
    else:
        record["noise"] = {"vs_carrier": {}, "vs_spectral": {}}
        for f in CARRIER_FREQS:
            try:
                record["noise"]["vs_carrier"][repr(f)] = _jsonable(
                    noise_attr(f, REF_SPECTRAL))
            except Exception as exc:
                record["noise"]["vs_carrier"][repr(f)] = f"ERROR {type(exc).__name__}"
        for f in SPECTRAL_FREQS:
            try:
                record["noise"]["vs_spectral"][repr(f)] = _jsonable(
                    noise_attr(REF_CARRIER, f))
            except Exception as exc:
                record["noise"]["vs_spectral"][repr(f)] = f"ERROR {type(exc).__name__}"
    return record


def build_snapshot():
    """Snapshot every component in COMPONENT_SPECS."""
    return {name: _snapshot_component(name, kwargs)
            for name, kwargs in sorted(COMPONENT_SPECS.items())}


def load_golden():
    with open(GOLDEN_PATH) as fh:
        return json.load(fh)


@pytest.mark.parametrize("name", sorted(COMPONENT_SPECS))
def test_component_matches_golden(name):
    """Each component reproduces its recorded gain/noise exactly."""
    golden = load_golden()
    assert name in golden, f"{name} missing from golden file; regenerate it"
    assert _snapshot_component(name, COMPONENT_SPECS[name]) == golden[name], (
        f"{name} numerics changed. If this was intentional, regenerate the "
        f"golden file and review the diff."
    )


def test_every_component_is_characterized():
    """Adding a component to hardware_models requires adding a snapshot."""
    import inspect

    import hardware_models as hm
    from component import Component

    concrete = set()
    for cls_name, obj in inspect.getmembers(hm, inspect.isclass):
        if cls_name.startswith("_") or obj.__module__ != hm.__name__:
            continue
        # Skip abstract bases; they are not usable components.
        if inspect.isabstract(obj) or obj is Component:
            continue
        concrete.add(cls_name)

    # The legacy AD9082 shim has no gain()/noise() and is not a chain component.
    concrete.discard("AD9082")

    missing = concrete - set(COMPONENT_SPECS)
    assert not missing, f"components with no characterization snapshot: {sorted(missing)}"


def test_known_bad_components_are_still_documented():
    """Keeps KNOWN_BAD honest: every entry must name a real component."""
    unknown = set(KNOWN_BAD) - set(COMPONENT_SPECS)
    assert not unknown, f"KNOWN_BAD names components that do not exist: {sorted(unknown)}"


if __name__ == "__main__":
    if "--regenerate" in sys.argv:
        os.makedirs(os.path.dirname(GOLDEN_PATH), exist_ok=True)
        with open(GOLDEN_PATH, "w") as fh:
            json.dump(build_snapshot(), fh, indent=2, sort_keys=True)
        print(f"wrote {GOLDEN_PATH}")
    else:
        print(__doc__)
