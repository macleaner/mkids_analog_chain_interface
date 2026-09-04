"""
Characterization ("golden value") tests.

These pin the *current* numerical output of every component so that a refactor
cannot silently change results. They deliberately assert on a stored snapshot
rather than on physically-derived expectations: their job is to detect change,
not to certify correctness.

Some snapshotted values are known to be physically wrong - see KNOWN_BAD below.
Those entries are recorded so the refactor is provably behaviour-preserving, and
are flagged so nobody mistakes the snapshot for a statement of correctness.

To regenerate after an *intentional* numerical change, name what changed:
    python tests/test_characterization.py --regenerate LNF_LNC1_5_6B
Every other entry is written back from disk unaltered, so the diff is the
entries named and nothing else, and anything still disagreeing with its model
is listed rather than quietly blessed.

Naming nothing rewrites the whole file:
    python tests/test_characterization.py --regenerate
which re-blesses every difference in the tree at once. Reach for it when
creating the file or when the tree holds exactly one change; adding a component
with someone else's numerical change in flight is how an unreviewed change gets
recorded as the expectation. Either way, review the diff to
tests/data/golden_components.json carefully.
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
    "AD9082_DAC": {"carrier_power_dbm": -20.0},
    "AD9082_ADC": {},
    # Snapshotted noisy, at non-default settings: the noiseless switch returns
    # zero for every input, so a snapshot of it would pin nothing that could
    # change. tests/test_noise_frequencies.py covers that branch instead.
    "GenericDAC": {"carrier_power_dbm": -20.0, "phase_noise_dbc_per_hz": -100.0,
                   "phase_noise_offset_hz": 1000.0,
                   "phase_noise_slope_db_per_decade": -20.0,
                   "noiseless": False},
    "GenericADC": {"noise_density_dbm_per_hz": -150.0, "noiseless": False},
    "ASU_3GHz_LNA": {},
    "ZX60_3018Gplus": {},
    "ZX60_83LN_Splus": {},
    "CryoElec_LNA": {},
    "CMT_CITCRYO1_12D": {},
    "LNF_LNC1_5_6B": {},
    "LNF_LNC0_3_14B": {},
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
    "SMA_RG316_cables": {"length_m": 0.5},
    "ZN4PD_4R722plus": {},
    "FilterHP_VHF1320p": {},
    "FilterHP_VHF1760p": {},
    "FilterHP_VHF1910p": {},
    "FilterHP_VHF5050p": {},
    "FilterLP_VLF6700p": {},
    "FilterLP_VLFG2000p": {},
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


def _write_golden(snapshot):
    """Write the file in the one format the byte-for-byte guarantee needs."""
    os.makedirs(os.path.dirname(GOLDEN_PATH), exist_ok=True)
    with open(GOLDEN_PATH, "w") as fh:
        json.dump(snapshot, fh, indent=2, sort_keys=True)


def regenerate(names=None):
    """
    Rewrite the golden file - all of it, or only the entries in ``names``.

    A whole-file rewrite re-blesses every difference in the working tree at
    once. That is fine when the only difference is the one being blessed, and a
    trap otherwise: adding a component runs this, so an unrelated numerical
    change someone has in flight gets written into the snapshot and lands in
    the commit that added the component, under a message that says nothing
    about it. The change is then invisible - it is recorded as the expectation,
    and the test that would have flagged it now passes.

    Naming entries avoids that. Only those are recomputed; every other entry is
    written back from the value already on disk, in the same format, so it
    comes out byte for byte identical and the diff is exactly the entries
    asked for.

    Returns ``(written, stale)``: what was rewritten, and which entries still
    disagree with their model afterwards - the ones a selective rewrite has
    deliberately left for someone to look at. ``stale`` is empty after a whole-
    file rewrite, by construction.
    """
    if names:
        unknown = sorted(set(names) - set(COMPONENT_SPECS))
        if unknown:
            raise SystemExit(
                f"not characterized: {', '.join(unknown)}\n"
                f"known components are: {', '.join(sorted(COMPONENT_SPECS))}")
        if not os.path.exists(GOLDEN_PATH):
            raise SystemExit(
                f"{GOLDEN_PATH} does not exist, so there is nothing to preserve"
                f" around the named entries; run --regenerate with no names to "
                f"create it")
        snapshot = load_golden()
        for name in names:
            snapshot[name] = _snapshot_component(name, COMPONENT_SPECS[name])
        written = sorted(set(names))
    else:
        snapshot = build_snapshot()
        written = sorted(snapshot)

    _write_golden(snapshot)

    # Compared the same way test_component_matches_golden compares, so "stale"
    # here means precisely "would fail that test".
    stale = [name for name, kwargs in sorted(COMPONENT_SPECS.items())
             if snapshot.get(name) != _snapshot_component(name, kwargs)]
    return written, stale


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


def test_naming_an_entry_leaves_an_unrelated_change_alone(tmp_path, monkeypatch):
    """
    The reason --regenerate takes names: someone else's numerical change, in
    flight in the same tree, must survive being adjacent to a component being
    added. It stays on disk as it was and is reported, rather than being
    recorded as the expectation by a rewrite that never mentioned it.
    """
    golden = build_snapshot()
    in_flight, adding = "Attenuator", "ZX60_3018Gplus"
    # Stands in for a model whose numbers have moved since it was snapshotted.
    golden[in_flight]["gain"]["1000000000.0"] = -12345.0

    path = tmp_path / "golden_components.json"
    monkeypatch.setattr(sys.modules[__name__], "GOLDEN_PATH", str(path))
    _write_golden(golden)

    written, stale = regenerate([adding])

    assert written == [adding]
    assert in_flight in stale, "an entry left disagreeing was not reported"
    assert adding not in stale
    after = json.loads(path.read_text())
    assert after[in_flight] == golden[in_flight], "an unnamed entry was rewritten"
    assert after[adding] == _snapshot_component(adding, COMPONENT_SPECS[adding])


def test_naming_a_current_entry_rewrites_no_bytes(tmp_path, monkeypatch):
    """
    The byte-for-byte half of that promise. Rewriting an entry that already
    agrees with its model has to leave the file alone entirely - a reformat or
    a reordered key would put every other entry in the diff and bury the one
    line that matters.
    """
    path = tmp_path / "golden_components.json"
    monkeypatch.setattr(sys.modules[__name__], "GOLDEN_PATH", str(path))
    _write_golden(build_snapshot())
    before = path.read_bytes()

    regenerate(["Attenuator"])

    assert path.read_bytes() == before


def test_regenerating_an_unknown_name_refuses(tmp_path, monkeypatch):
    """A typo must not silently write nothing and report success."""
    path = tmp_path / "golden_components.json"
    monkeypatch.setattr(sys.modules[__name__], "GOLDEN_PATH", str(path))
    _write_golden(build_snapshot())

    with pytest.raises(SystemExit, match="Attenuatorr"):
        regenerate(["Attenuatorr"])


def test_known_bad_components_are_still_documented():
    """Keeps KNOWN_BAD honest: every entry must name a real component."""
    unknown = set(KNOWN_BAD) - set(COMPONENT_SPECS)
    assert not unknown, f"KNOWN_BAD names components that do not exist: {sorted(unknown)}"


if __name__ == "__main__":
    if "--regenerate" in sys.argv:
        argument_names = [arg for arg
                          in sys.argv[sys.argv.index("--regenerate") + 1:]
                          if not arg.startswith("-")]
        written, stale = regenerate(argument_names)

        if argument_names:
            print(f"rewrote {len(written)} of {len(COMPONENT_SPECS)} entries "
                  f"in {GOLDEN_PATH}:")
            for name in written:
                print(f"    {name}")
        else:
            print(f"wrote {GOLDEN_PATH}, all {len(written)} entries")

        if stale:
            print(f"\nleft alone, and still disagreeing with their model:")
            for name in stale:
                print(f"    {name}")
            print("Each of those is a numerical change to review on its own "
                  "terms.\nRegenerate them by name once you have.")
    else:
        print(__doc__)
