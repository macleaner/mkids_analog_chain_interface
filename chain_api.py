"""
JSON-in / JSON-out facade over the signal-chain machinery.

This is the seam between the physics (which lives in Python, here and in the
modules this imports) and any view layer that cannot import Python directly -
in particular the browser GUI, which runs this same module under Pyodide and
drives it from JavaScript.

The rule the browser GUI depends on: **the chain lives here.** A view calls
``add_component`` / ``set_param`` / ``budget`` and renders what comes back; it
never holds its own copy of the chain or reimplements any part of the cascade.
That is what makes it impossible for the browser's numbers to drift from the
ones a notebook computes - there is only one implementation, and this is it.

Every function returns a plain dict that ``json.dumps`` accepts: numpy scalars
are coerced to float, arrays to lists, and non-finite values to None (JSON has
no NaN). Failures come back as ``{"ok": False, "error": msg}`` rather than
raising, so a caller across a language boundary gets a message it can display
instead of a stack trace it cannot inspect.

Nothing here is browser-specific, and it is a reasonable scripting API in its
own right::

    import chain_api
    chain_api.load_preset("cryo_example")
    chain_api.budget("LNA", at="input", carrier_hz=1.5e9, spectral_hz=1e3)
"""

import functools
import json
import math
from typing import Any, Dict, List, Optional

import numpy as np

import registry
from signal_chain import SignalChain
from utils import to_dbm

__all__ = [
    "catalog", "presets", "load_preset", "new_chain", "describe",
    "add_component", "remove_component", "set_param", "set_label",
    "budget", "sweep_gain", "sweep_noise", "to_json", "from_json", "provenance",
]

# The one chain every call operates on. A view layer holds no chain state.
_CHAIN: SignalChain = SignalChain(name="Empty Chain")


# --------------------------------------------------------------------------
# JSON coercion
# --------------------------------------------------------------------------
def _num(value) -> Optional[float]:
    """A numpy or python scalar as a JSON-safe float (non-finite -> None)."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _arr(values) -> List[Optional[float]]:
    """An array as a list of JSON-safe floats."""
    flat = np.asarray(values, dtype=float).ravel()
    finite = np.isfinite(flat)
    return [float(v) if ok else None for v, ok in zip(flat, finite)]


def _guard(fn):
    """Return errors as data. A view across a language boundary needs a message."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:                      # noqa: BLE001 - reported, not swallowed
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if isinstance(result, dict) and "ok" in result:
            return result
        return {"ok": True, **(result if isinstance(result, dict) else {"value": result})}
    return wrapper


# --------------------------------------------------------------------------
# catalog - the component library, straight from the registry
# --------------------------------------------------------------------------
@_guard
def catalog() -> Dict[str, Any]:
    """
    Every registered component and its parameter specification.

    This is the form schema for the view: ``kind`` selects the widget,
    ``minimum``/``maximum``/``step`` bound it, ``choices`` makes it a select,
    and ``unit``/``help`` label it. Submitted values should come back through
    :func:`add_component` or :func:`set_param`, which validate them with the
    same ``ParamSpec.validate`` the Qt panel uses - so the constraints and the
    error messages are declared exactly once, in ``registry.py``.
    """
    categories = []
    for category, entries in registry.by_category().items():
        items = []
        for entry in entries:
            items.append({
                "type_id": entry.type_id,
                "label": entry.label,
                "doc": entry.doc,
                "params": [{
                    "name": spec.name,
                    "label": spec.display_label,
                    "unit": spec.unit,
                    "kind": spec.kind,
                    "default": spec.default,
                    "minimum": spec.minimum,
                    "maximum": spec.maximum,
                    "step": spec.step,
                    "help": spec.help,
                    "choices": list(spec.choices) if spec.choices else None,
                } for spec in entry.params],
            })
        categories.append({"category": category, "components": items})
    return {"categories": categories}


# --------------------------------------------------------------------------
# presets
# --------------------------------------------------------------------------
# Built as (type_id, params, label) triples rather than by importing example
# scripts, so a preset is data the wheel carries and can be round-tripped.
_PRESETS: Dict[str, Dict[str, Any]] = {
    "cryo_example": {
        "label": "Simple cryogenic system",
        "description": "Room temp -> cryostat -> LNA -> warm amplification, "
                       "with an AD9082 at each end.",
        "chain_name": "Simple Cryogenic System",
        "dac": ("converter.ad9082_dac", {"carrier_power_dbm": -10.0}),
        "adc": ("converter.ad9082_adc", {}),
        "components": [
            ("attenuator", {"attenuation": -10.0, "temperature": 300.0}, "InputAtten"),
            ("cable.fm_f141", {"length_m": 2.0}, "WarmCable_In"),
            ("cable.sma_ss086_cryo", {"length_m": 0.5, "temperature": 4.0}, "CryoCable"),
            ("attenuator", {"attenuation": -20.0, "temperature": 4.0}, "ColdAtten"),
            ("amplifier.asu_3ghz_lna", {}, "LNA"),
            ("cable.sma_ss086_cryo", {"length_m": 0.5, "temperature": 50.0}, "ReturnCable"),
            ("amplifier.zx60_3018g_plus", {}, "WarmAmp1"),
            ("amplifier.zx60_3018g_plus", {}, "WarmAmp2"),
        ],
    },
}


@_guard
def presets() -> Dict[str, Any]:
    """The presets this build carries."""
    return {"presets": [{"key": k, "label": v["label"],
                         "description": v["description"]}
                        for k, v in _PRESETS.items()]}


@_guard
def load_preset(key: str) -> Dict[str, Any]:
    """Replace the current chain with a named preset."""
    global _CHAIN
    if key not in _PRESETS:
        raise KeyError(f"unknown preset {key!r}; known: {sorted(_PRESETS)}")
    spec = _PRESETS[key]
    chain = SignalChain(name=spec["chain_name"], description=spec["description"])
    for type_id, params, label in spec["components"]:
        chain.add_component(registry.create(type_id, params), label=label)
    dac_id, dac_params = spec["dac"]
    adc_id, adc_params = spec["adc"]
    chain.set_digitizer(registry.create(dac_id, dac_params),
                        registry.create(adc_id, adc_params))
    _CHAIN = chain
    return _describe()


@_guard
def new_chain(name: str = "New Chain") -> Dict[str, Any]:
    """Discard the current chain and start an empty one."""
    global _CHAIN
    _CHAIN = SignalChain(name=name)
    return _describe()


# --------------------------------------------------------------------------
# chain structure
# --------------------------------------------------------------------------
def _describe() -> Dict[str, Any]:
    """
    The chain as the view needs to draw it: stages in signal order, plus the
    planes a budget can be referred to.

    Stage indices here are ``SignalChain.stages()`` indices (DAC first), while
    ``component_index`` is the index into ``chain.components`` that
    :func:`set_param` and :func:`remove_component` take. They differ by the DAC
    offset, so both are reported rather than left for the caller to infer.
    """
    stages = _CHAIN.stages()
    offset = 1 if _CHAIN.dac is not None else 0
    out_stages = []
    for i, (label, component, kind) in enumerate(stages):
        component_index = i - offset
        if kind in ("dac", "adc"):
            component_index = None
        out_stages.append({
            "stage_index": i,
            "component_index": component_index,
            "label": label,
            "kind": kind,
            "type_id": getattr(component, "type_id", None),
            "class_name": type(component).__name__,
            "params": component.params,
        })

    planes = []
    for i, (label, _component, kind) in enumerate(stages):
        for at in ("input", "output"):
            planes.append({"reference": label, "at": at, "kind": kind,
                           "display": f"{label} ({at})", "stage_index": i})
    return {"name": _CHAIN.name, "description": _CHAIN.description,
            "stages": out_stages, "planes": planes,
            "n_components": len(_CHAIN.components),
            "has_digitizer": _CHAIN.dac is not None and _CHAIN.adc is not None}


@_guard
def describe() -> Dict[str, Any]:
    """The current chain's structure."""
    return _describe()


@_guard
def add_component(type_id: str, params: Optional[Dict[str, Any]] = None,
                  label: Optional[str] = None) -> Dict[str, Any]:
    """
    Append a component. Parameters are validated by the registry, so an
    out-of-range value fails here with the message ``ParamSpec`` declares
    rather than being silently accepted.
    """
    component = registry.create(type_id, params or {})
    _CHAIN.add_component(component, label=label)
    return _describe()


@_guard
def remove_component(component_index: int) -> Dict[str, Any]:
    """Remove ``chain.components[component_index]`` and its label."""
    if not 0 <= component_index < len(_CHAIN.components):
        raise IndexError(
            f"component index {component_index} out of range "
            f"(chain has {len(_CHAIN.components)})")
    _CHAIN.components.pop(component_index)
    # chain.labels maps label -> index, so removing a component drops the label
    # pointing at it and shifts every index above the hole down one.
    _CHAIN.labels = {label: (idx - 1 if idx > component_index else idx)
                     for label, idx in _CHAIN.labels.items()
                     if idx != component_index}
    return _describe()


@_guard
def set_param(component_index: int, name: str, value: Any) -> Dict[str, Any]:
    """
    Change one parameter by rebuilding the component from its recorded params.

    Rebuilding rather than assigning to an attribute is deliberate: several
    models precompute interpolators in ``__init__`` from the parameters they
    were given, so mutating an attribute afterwards would leave those stale.
    Going back through ``registry.create`` also re-runs validation.
    """
    if not 0 <= component_index < len(_CHAIN.components):
        raise IndexError(f"component index {component_index} out of range")
    existing = _CHAIN.components[component_index]
    type_id = getattr(existing, "type_id", None)
    if type_id is None:
        raise TypeError(f"{type(existing).__name__} is not registered")
    params = dict(existing.params)
    if name not in params and name not in {s.name for s in registry.resolve(type_id).params}:
        raise KeyError(f"{type_id} has no parameter {name!r}")
    params[name] = value
    _CHAIN.components[component_index] = registry.create(
        type_id, params, name=existing.name)
    return _describe()


@_guard
def set_label(component_index: int, label: str) -> Dict[str, Any]:
    """Rename a component's chain label."""
    if not 0 <= component_index < len(_CHAIN.components):
        raise IndexError(f"component index {component_index} out of range")
    if label in _CHAIN.labels and _CHAIN.labels[label] != component_index:
        raise ValueError(f"label {label!r} already refers to component "
                         f"{_CHAIN.labels[label]}")
    # Drop whatever label pointed here before, then point the new one at it.
    _CHAIN.labels = {existing: idx for existing, idx in _CHAIN.labels.items()
                     if idx != component_index}
    _CHAIN.labels[label] = component_index
    return _describe()


# --------------------------------------------------------------------------
# analysis
# --------------------------------------------------------------------------
@_guard
def budget(reference: Any, at: str, carrier_hz: float,
           spectral_hz: float) -> Dict[str, Any]:
    """
    The noise budget referred to one plane.

    ``rows`` is ``NoiseBudget.to_rows()`` verbatim - every quantity in W/Hz,
    dBm/Hz and K, plus the fraction of total - so the view picks a unit by
    choosing a column instead of converting anything itself.
    """
    result = _CHAIN.noise_budget(reference, float(carrier_hz),
                                 float(spectral_hz), at=at)
    rows = []
    for row in result.to_rows():
        rows.append({k: (_num(v) if isinstance(v, (int, float, np.generic)) else v)
                     for k, v in row.items()})
    dominant = result.dominant()
    return {
        "reference": result.reference,
        "carrier_hz": _num(carrier_hz),
        "spectral_hz": _num(spectral_hz),
        "total_w_per_hz": _num(result.total_w),
        "total_dbm_per_hz": _num(result.total_dbm_per_hz),
        "total_k": _num(result.total_k),
        "dominant": dominant.label if dominant is not None else None,
        "rows": rows,
    }


def _grid(start: float, stop: float, n: int, log: bool) -> np.ndarray:
    n = int(n)
    if n < 2:
        raise ValueError(f"need at least 2 points, got {n}")
    if stop <= start:
        raise ValueError(f"stop ({stop}) must exceed start ({start})")
    if log:
        if start <= 0:
            raise ValueError("logarithmic spacing needs a positive start")
        return np.logspace(np.log10(start), np.log10(stop), n)
    return np.linspace(start, stop, n)


@_guard
def sweep_gain(start_hz: float, stop_hz: float, n: int = 401,
               log: bool = False) -> Dict[str, Any]:
    """Total chain gain in dB over a carrier-frequency sweep."""
    freq = _grid(float(start_hz), float(stop_hz), n, bool(log))
    gain = np.asarray(_CHAIN.total_gain(freq), dtype=float)
    if gain.ndim == 0:
        gain = np.full_like(freq, float(gain))
    return {"freq_hz": _arr(freq), "gain_db": _arr(gain),
            "min_db": _num(np.nanmin(gain)), "max_db": _num(np.nanmax(gain))}


@_guard
def sweep_noise(carrier_hz: float, start_hz: float, stop_hz: float,
                n: int = 201, log: bool = True,
                contributions: bool = False,
                reference: Any = None, at: str = "output") -> Dict[str, Any]:
    """
    Noise PSD referred to one plane, over a spectral-frequency sweep.

    ``reference``/``at`` name the plane exactly as :func:`budget` does; with
    ``reference`` left as None the sweep is referred to the chain output, after
    the ADC. This is the same decomposition the budget table shows at a single
    spectral frequency, evaluated across a sweep instead - one
    ``SignalChain.noise_budget`` call over a spectral array, so a curve here and
    a row there at the same offset are the same number.

    With ``contributions`` the per-source breakdown comes back as well, each
    already referred to that plane.

    Both W/Hz and dBm/Hz are returned. The conversion is trivial, but doing it
    here rather than in the view keeps every number the browser plots a number
    Python computed - a unit change is a column choice, not JS arithmetic.
    """
    spectral = _grid(float(start_hz), float(stop_hz), n, bool(log))
    carrier = float(carrier_hz)
    # One budget for the whole sweep: every model broadcasts over the spectral
    # axis, so the total and the contributions come back already shaped like it.
    if reference is None:
        result = _CHAIN.output_budget(carrier, spectral)
    else:
        result = _CHAIN.noise_budget(reference, carrier, spectral, at=at)
    # An empty budget totals a scalar 0.0; broadcast so the axis stays paired.
    total = np.broadcast_to(
        np.asarray(result.total_w, dtype=float), spectral.shape)

    series = []
    if contributions:
        # NoiseBudget ranks them by peak, which is the order the budget table
        # shows, so the plot legend and the table agree without sorting here.
        for contribution in result.contributions:
            # A source that is flat in spectral frequency may still come back
            # scalar; broadcast so every series is the length of the axis.
            watts = np.broadcast_to(
                np.asarray(contribution.power_w, dtype=float), spectral.shape)
            series.append({"label": contribution.label,
                           "w_per_hz": _arr(watts),
                           "dbm_per_hz": _arr(to_dbm(watts))})

    return {"carrier_hz": _num(carrier), "reference": result.reference,
            "spectral_hz": _arr(spectral),
            "total_w_per_hz": _arr(total),
            "total_dbm_per_hz": _arr(to_dbm(total)),
            "series": series}


# --------------------------------------------------------------------------
# round trip
# --------------------------------------------------------------------------
@_guard
def to_json(indent: int = 2) -> Dict[str, Any]:
    """
    The chain as the JSON a notebook reloads with ``SignalChain.load``.

    This is what makes the browser build a record and not just a view: what it
    hands back is the same file format, produced by the same ``to_dict``.
    """
    return {"json": json.dumps(_CHAIN.to_dict(), indent=int(indent)),
            "suggested_filename": f"{_CHAIN.name.replace(' ', '_').lower()}.json"}


@_guard
def from_json(text: str) -> Dict[str, Any]:
    """Replace the current chain with one parsed from a chain file."""
    global _CHAIN
    _CHAIN = SignalChain.from_dict(json.loads(text))
    return _describe()


@_guard
def provenance() -> Dict[str, Any]:
    """
    What is actually running, for the page to display.

    A built artifact that cannot say which version produced it is not a record;
    stamping this is the cheapest guard against trusting a stale build.
    """
    import platform
    import sys
    try:
        import scipy
        scipy_version = scipy.__version__
    except ImportError:
        scipy_version = None
    try:
        from importlib.metadata import version
        core_version = version("analog-chain-core")
    except Exception:                                 # noqa: BLE001 - not installed as a wheel
        core_version = None
    return {"python": sys.version.split()[0], "platform": platform.platform(),
            "numpy": np.__version__, "scipy": scipy_version,
            "analog_chain_core": core_version,
            "n_registered": len(registry.entries())}
