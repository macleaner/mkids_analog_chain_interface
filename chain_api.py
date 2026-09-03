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

import notebook_export
import registry
from component import ADCComponent, DACComponent
from signal_chain import SignalChain
from utils import kb, to_dbm

__all__ = [
    "catalog", "component_specs", "presets", "load_preset", "new_chain", "describe",
    "add_component", "remove_component", "move_component",
    "set_param", "set_label",
    "set_digitizer", "set_digitizer_param",
    "set_name", "set_description", "set_metadata",
    "budget", "sweep_gain", "sweep_noise",
    "to_json", "from_json", "notebook", "provenance",
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
def _role_of(cls) -> str:
    """
    Where a registered component belongs in a chain: ``dac``, ``adc`` or
    ``component``.

    Converters are endpoints - they are installed with
    :func:`set_digitizer`, not appended - so a view has to be able to tell them
    apart. Taking that from the class hierarchy rather than from the category
    name or a list of type ids means a newly registered converter is classified
    correctly without anything here being updated.
    """
    if issubclass(cls, DACComponent):
        return "dac"
    if issubclass(cls, ADCComponent):
        return "adc"
    return "component"


@_guard
def catalog() -> Dict[str, Any]:
    """
    Every registered component and its parameter specification.

    This is the form schema for the view: ``kind`` selects the widget,
    ``minimum``/``maximum``/``step`` bound it, ``choices`` makes it a select,
    ``unit``/``help`` label it, and ``group`` - where set - is the heading of a
    sub-box the parameter belongs in, shared with the neighbours around it in
    this list. Submitted values should come back through :func:`add_component`
    or :func:`set_param`, which validate them with the same
    ``ParamSpec.validate`` the Qt panel uses - so the constraints and the error
    messages are declared exactly once, in ``registry.py``.

    Parameter order is the registry's, and a group is guaranteed contiguous in
    it, so a view can render straight down the list and open a box when the
    group changes.

    ``role`` says which call installs the entry: ``component`` ones are
    appended with :func:`add_component`, while ``dac``/``adc`` ones are chain
    endpoints and go in through :func:`set_digitizer`.
    """
    categories = []
    for category, entries in registry.by_category().items():
        items = []
        for entry in entries:
            items.append({
                "type_id": entry.type_id,
                "label": entry.label,
                "doc": entry.doc,
                "role": _role_of(entry.cls),
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
                    "group": spec.group,
                } for spec in entry.params],
            })
        categories.append({"category": category, "components": items})
    return {"categories": categories}


# --------------------------------------------------------------------------
# component specs - what one model says about itself, outside any chain
# --------------------------------------------------------------------------
# Carrier frequencies used to ask a model where it is defined. Log spaced,
# because the library spans DC to tens of GHz, with 0 Hz prepended so a model
# tabulated from DC reports DC rather than whatever the lowest probe happened
# to be.
_PROBE_HZ = np.concatenate(([0.0], np.logspace(4, np.log10(4e10), 481)))

# Spectral offsets used to tell a source that is white near the carrier from one
# with a skirt. Wide enough to catch DAC phase noise, which falls ~10 dB/decade.
_NOISE_OFFSETS_HZ = np.logspace(-2, 6, 9)


def _gain_curve(component, freq: np.ndarray) -> np.ndarray:
    """One component's gain over an array, broadcast for the constant models."""
    gain = np.asarray(component.gain(freq), dtype=float)
    if gain.ndim == 0:
        return np.full(freq.shape, float(gain))
    return gain


def _defined_edge(component, inside: float, outside: float) -> float:
    """
    Bisect for the frequency at which a model stops answering.

    ``inside`` is a probe point that returned a number and ``outside`` is its
    neighbour that returned NaN, so the boundary lies between them; 40 halvings
    put it far inside display precision.
    """
    for _ in range(40):
        middle = 0.5 * (inside + outside)
        if np.isfinite(_gain_curve(component, np.array([middle]))[0]):
            inside = middle
        else:
            outside = middle
    return inside


def _defined_span(component) -> Optional[tuple]:
    """
    The carrier band a model is valid over, found by asking it.

    A model that extrapolates past its datasheet answers with a number
    everywhere, so it cannot state its band through NaN and instead declares it
    outright with ``defined_span_hz`` - every model with a tabulated curve does
    this. Otherwise the model is built with ``bounds_error=False`` and no fill
    value, so outside its tabulated range it returns NaN, and that NaN *is* the
    same statement made the other way; bisecting for it is why this reads no
    interpolator's knots.

    Either way the model is the one answering, and no attribute of its datasheet
    storage is touched, so a model that changes how it holds its curve keeps
    working here.

    Returns None for a model that answers everywhere and declares no band - a
    flat attenuator, or a converter - which has none to show.
    """
    declared = getattr(component, "defined_span_hz", None)
    if declared is not None:
        low, high = declared()
        return float(low), float(high)

    finite = np.isfinite(_gain_curve(component, _PROBE_HZ))
    if not finite.any() or finite.all():
        return None
    first = int(np.argmax(finite))
    last = int(len(finite) - 1 - np.argmax(finite[::-1]))
    low = (_PROBE_HZ[first] if first == 0
           else _defined_edge(component, _PROBE_HZ[first], _PROBE_HZ[first - 1]))
    high = (_PROBE_HZ[last] if last == len(finite) - 1
            else _defined_edge(component, _PROBE_HZ[last], _PROBE_HZ[last + 1]))
    return float(low), float(high)


def _noise_summary(component, carrier_hz: float,
                   spectral_hz: float) -> Dict[str, Any]:
    """
    What one component contributes on its own, and in which unit to say it.

    A source that is white near the carrier has a single noise temperature,
    which is how the datasheets quote an amplifier and how ``k_B*T`` reads for a
    warm attenuator. One with spectral structure - DAC phase noise - has no
    temperature at all, so ``kind`` is ``"spectral"`` and the caller should
    quote the density at the offset it asked about instead.

    ``referred_to`` is the component's own ``noise_reference``: whether this
    figure stands at its input, and so is acted on by its own gain, or at its
    output, and so is not.
    """
    across = np.asarray(component.noise(carrier_hz, _NOISE_OFFSETS_HZ),
                        dtype=float)
    if across.ndim == 0:
        across = np.full(_NOISE_OFFSETS_HZ.shape, float(across))
    finite = across[np.isfinite(across)]

    if not finite.size:
        kind = "unknown"            # not defined at this carrier
    elif np.all(finite == 0.0):
        kind = "none"               # a filter, say: lossy but not a source
    # atol=0: these are powers in W/Hz, around 1e-20 for a cold amplifier, so
    # np.allclose's default absolute tolerance of 1e-8 would call every source
    # in the library flat - including the DAC's phase-noise skirt, which spans
    # seven decades over this axis. Only a relative comparison means anything.
    elif np.allclose(finite, finite[0], rtol=1e-6, atol=0.0):
        kind = "flat"
    else:
        kind = "spectral"

    at = float(np.asarray(component.noise(carrier_hz, spectral_hz),
                          dtype=float).ravel()[0])
    positive = math.isfinite(at) and at > 0.0
    return {"kind": kind, "referred_to": component.noise_reference,
            "w_per_hz": _num(at),
            "dbm_per_hz": _num(to_dbm(at)) if positive else None,
            "temperature_k": _num(at / kb) if positive else None}


@_guard
def component_specs(type_id: str, params: Optional[Dict[str, Any]] = None,
                    carrier_hz: float = 1.5e9, spectral_hz: float = 1.0e3,
                    start_hz: float = 1.0e8, stop_hz: float = 3.0e9,
                    n: int = 161) -> Dict[str, Any]:
    """
    One model's specification, evaluated on its own rather than in a chain.

    This is what a library entry can say about itself before it is added: the
    registry's label and docstring, plus what the model actually computes - its
    gain across the band it is defined over, and what it contributes at the
    operating point the caller names. Same source as everything else here, so a
    spec cannot disagree with the budget the component then lands in.

    Nothing is stored: the component is built, asked and dropped, so the current
    chain is untouched and the answer is the same whether or not that model is
    in it. ``params`` defaults each declared parameter, so calling with none
    describes the entry as the library would install it.

    The sweep runs over the band the model answers for (see
    :func:`_defined_span`). ``start_hz``/``stop_hz`` are the fallback for a
    model that answers everywhere and so has no band of its own to show;
    ``span_source`` says which of the two was used.
    """
    entry = registry.resolve(type_id)
    component = registry.create(type_id, params)
    carrier = float(carrier_hz)

    span = _defined_span(component)
    span_source = "model" if span is not None else "requested"
    if span is None:
        if float(stop_hz) <= float(start_hz):
            raise ValueError(f"stop ({stop_hz}) must exceed start ({start_hz})")
        span = (float(start_hz), float(stop_hz))

    freq = np.linspace(span[0], span[1], max(2, int(n)))
    gain = _gain_curve(component, freq)
    finite = gain[np.isfinite(gain)]

    return {
        "type_id": entry.type_id,
        "label": entry.label,
        "category": entry.category,
        "role": _role_of(entry.cls),
        "doc": entry.doc,
        # What the figures below were computed with, so a spec panel can say so
        # rather than leaving the reader to assume they are parameter-free.
        "params_used": component.params,
        "carrier_hz": _num(carrier),
        "spectral_hz": _num(spectral_hz),
        "span_source": span_source,
        "span_from_hz": _num(span[0]),
        "span_to_hz": _num(span[1]),
        "freq_hz": _arr(freq),
        "gain_db": _arr(gain),
        "gain_at_carrier_db": _num(_gain_curve(component,
                                               np.array([carrier]))[0]),
        "gain_min_db": _num(finite.min()) if finite.size else None,
        "gain_max_db": _num(finite.max()) if finite.size else None,
        # Decided here, not by comparing the two figures above in the view: a
        # flat model is quoted as one number and a sloped one as a range.
        "gain_flat": bool(finite.size and (finite.max() - finite.min()) < 0.005),
        "noise": _noise_summary(component, carrier, float(spectral_hz)),
    }


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
    """
    Discard the current chain and start an empty one.

    Empty means no components *and* no converters: build it up with
    :func:`add_component` and :func:`set_digitizer`. Until there is at least
    one stage the chain has no planes, so :func:`budget` has nothing to refer
    to and says so.
    """
    global _CHAIN
    _CHAIN = SignalChain(name=name)
    return _describe()


# --------------------------------------------------------------------------
# chain structure
# --------------------------------------------------------------------------
def _type_label(component) -> str:
    """
    A component's model name as the registry lists it, e.g. ``Attenuator`` or
    ``SMA generic (room temp)``.

    Anything unregistered - a component a script built directly, or one whose
    type id a later build dropped - falls back to its class name, so a stage
    always says what it is rather than showing a blank where its model goes.
    """
    type_id = getattr(component, "type_id", None)
    if type_id is not None:
        try:
            return registry.resolve(type_id).label
        except KeyError:
            pass
    return type(component).__name__


def _label_stem(type_id: str) -> str:
    """
    The family a type id belongs to, capitalized: ``cable.fm_f141`` -> Cable,
    ``attenuator`` -> Attenuator.

    Taken from the type id rather than the registry's category, because the
    category is presentation ("Cables") while the id's first segment is what
    the codebase already uses to group models - so a newly registered cable
    gets the same stem as every other one without a list here being updated.
    """
    family = type_id.split(".")[0]
    return "".join(word.capitalize() for word in family.split("_")) or "Stage"


def _default_label(type_id: str) -> str:
    """
    A generic label for a newly added component: Cable1, Attenuator2, and so on
    - the lowest number that is free for that family.

    A label is how a budget names a stage and how the saved file records it, so
    every component needs one from the moment it is added. Naming it after its
    family means the default already says something true about the stage, and
    the user overwrites it with what the hardware actually is.
    """
    stem = _label_stem(type_id)
    number = 1
    while f"{stem}{number}" in _CHAIN.labels:
        number += 1
    return f"{stem}{number}"


def _describe() -> Dict[str, Any]:
    """
    The chain as the view needs to draw it: stages in signal order, plus the
    planes a budget can be referred to.

    Stage indices here are ``SignalChain.stages()`` indices (DAC first), while
    ``component_index`` is the index into ``chain.components`` that
    :func:`set_param` and :func:`remove_component` take. They differ by the DAC
    offset, so both are reported rather than left for the caller to infer.

    ``component_index`` is None only for the installed converters, which have
    no index because they are set as the digitizer rather than appended - those
    are edited through :func:`set_digitizer_param`. The test is identity with
    ``chain.dac``/``chain.adc``, not the stage's kind: a converter that was
    appended to ``components`` instead *does* have an index, and reporting it
    as None would leave it in the chain with no way to edit or remove it.

    ``type_label`` is the model's name as the library lists it, so a view can
    show what a stage *is* ("SMA Stainless 0.86mm (cryo)") next to what it is
    called ("CryoCable"). A label is free text a user chose; the type label is
    the one thing about a stage that cannot be renamed.
    """
    stages = _CHAIN.stages()
    offset = 1 if _CHAIN.dac is not None else 0
    out_stages = []
    for i, (label, component, kind) in enumerate(stages):
        component_index = i - offset
        if component is _CHAIN.dac or component is _CHAIN.adc:
            component_index = None
        out_stages.append({
            "stage_index": i,
            "component_index": component_index,
            "label": label,
            "kind": kind,
            "type_id": getattr(component, "type_id", None),
            "type_label": _type_label(component),
            "class_name": type(component).__name__,
            "params": component.params,
        })

    planes = []
    for i, (label, _component, kind) in enumerate(stages):
        for at in ("input", "output"):
            planes.append({"reference": label, "at": at, "kind": kind,
                           "display": f"{label} ({at})", "stage_index": i})

    # Reported separately as well as in `stages`, so a view can render the
    # digitizer control from state rather than by inferring it from stage kinds.
    digitizer = {
        role: None if component is None else {
            "label": component.name,
            "type_id": getattr(component, "type_id", None),
            "params": component.params,
        }
        for role, component in (("dac", _CHAIN.dac), ("adc", _CHAIN.adc))
    }
    return {"name": _CHAIN.name, "description": _CHAIN.description,
            "metadata": dict(_CHAIN.metadata),
            "stages": out_stages, "planes": planes,
            "n_components": len(_CHAIN.components),
            "digitizer": digitizer,
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

    Without a label the component gets a generic one for its family - Cable1,
    Attenuator2 - rather than ``SignalChain``'s class-and-position default.
    Position is exactly what a label must not encode: reordering the chain
    moves the component and its label together, and ``Attenuator_3`` sitting
    fifth is then a lie about the chain, while ``Attenuator3`` is only a name.
    """
    component = registry.create(type_id, params or {})
    _CHAIN.add_component(component, label=label or _default_label(type_id))
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
def move_component(component_index: int, to_index: int) -> Dict[str, Any]:
    """
    Move ``chain.components[component_index]`` to position ``to_index``.

    ``to_index`` is the position the component ends up at *after* it has been
    lifted out, which is what "drop it here" means in a list: moving 0 to 3 in
    a four-component chain leaves it last, and no index is ever out of range
    for a chain that has one.

    A move renumbers components without changing which component any label
    names, so ``chain.labels`` is rewritten through the same permutation. A
    budget taken by label therefore refers to the same hardware before and
    after - only its position in the cascade changed, which is the whole point.
    """
    count = len(_CHAIN.components)
    for name, index in (("component_index", component_index), ("to_index", to_index)):
        if not 0 <= index < count:
            raise IndexError(f"{name} {index} out of range "
                             f"(chain has {count} components)")
    order = list(range(count))
    order.insert(to_index, order.pop(component_index))
    _CHAIN.components = [_CHAIN.components[old] for old in order]
    # order[new] == old, and labels are stored the other way round.
    moved_to = {old: new for new, old in enumerate(order)}
    _CHAIN.labels = {label: moved_to.get(index, index)
                     for label, index in _CHAIN.labels.items()}
    return _describe()


def _with_param(existing, name: str, value: Any):
    """
    A copy of ``existing`` with one parameter changed.

    Rebuilding rather than assigning to an attribute is deliberate: several
    models precompute interpolators in ``__init__`` from the parameters they
    were given, so mutating an attribute afterwards would leave those stale.
    Going back through ``registry.create`` also re-runs validation.
    """
    type_id = getattr(existing, "type_id", None)
    if type_id is None:
        raise TypeError(f"{type(existing).__name__} is not registered")
    params = dict(existing.params)
    if name not in params and name not in {s.name for s in registry.resolve(type_id).params}:
        raise KeyError(f"{type_id} has no parameter {name!r}")
    params[name] = value
    return registry.create(type_id, params, name=existing.name)


@_guard
def set_param(component_index: int, name: str, value: Any) -> Dict[str, Any]:
    """Change one parameter of an appended component."""
    if not 0 <= component_index < len(_CHAIN.components):
        raise IndexError(f"component index {component_index} out of range")
    _CHAIN.components[component_index] = _with_param(
        _CHAIN.components[component_index], name, value)
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
# the record - what a saved chain says about itself
# --------------------------------------------------------------------------
# name, description and metadata are persisted by the file format and are not
# derivable from the components, so a chain built anywhere but here would carry
# them and one built in a view without them would not. They are as much of the
# record as the hardware is: what cooldown, whose sample, which dataset.
@_guard
def set_name(name: str) -> Dict[str, Any]:
    """
    Rename the chain. This is the title a saved file carries and what
    :func:`to_json` builds its suggested filename from, so an empty name is
    refused rather than silently producing ``.json``.
    """
    if not isinstance(name, str) or not name.strip():
        raise ValueError("a chain needs a name")
    _CHAIN.name = name.strip()
    return _describe()


@_guard
def set_description(description: str) -> Dict[str, Any]:
    """
    Set the chain's free-text notes - what this chain corresponds to, in
    whatever words are useful. Empty is allowed; it means no notes.
    """
    if not isinstance(description, str):
        raise TypeError(f"description must be a string, got "
                        f"{type(description).__name__}")
    _CHAIN.description = description
    return _describe()


@_guard
def set_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Replace the chain's bookkeeping fields (cooldown id, sample, dataset path,
    operator...). The whole mapping is replaced, not merged, so removing a
    field is possible.

    It is persisted verbatim, which means it has to survive ``json.dumps`` -
    checked here rather than at save time, because a chain that cannot be
    written is a record that has already been lost.
    """
    if not isinstance(metadata, dict):
        raise TypeError(f"metadata must be an object, got "
                        f"{type(metadata).__name__}")
    bad_keys = [key for key in metadata if not isinstance(key, str)]
    if bad_keys:
        raise TypeError(f"metadata keys must be strings; got {bad_keys!r}")
    json.dumps(metadata)                     # raises on anything unwritable
    _CHAIN.metadata = dict(metadata)
    return _describe()


# --------------------------------------------------------------------------
# digitizer - the chain's converter endpoints
# --------------------------------------------------------------------------
def _converter(role: str, type_id: Optional[str],
               params: Optional[Dict[str, Any]]):
    """Build one converter for ``role``, or None to leave that end open."""
    if type_id is None:
        return None
    entry = registry.resolve(type_id)
    actual = _role_of(entry.cls)
    if actual != role:
        raise TypeError(f"{type_id} registers as {actual!r}, so it cannot be "
                        f"the chain's {role.upper()}")
    return registry.create(type_id, params or {})


@_guard
def set_digitizer(dac_type_id: Optional[str] = None,
                  adc_type_id: Optional[str] = None,
                  dac_params: Optional[Dict[str, Any]] = None,
                  adc_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Install the chain's converters, replacing whatever was there.

    Both ends are set together, because that is what ``SignalChain`` stores:
    the DAC goes before every component and the ADC after all of them, so
    neither has a component index. Passing None for a type id leaves that end
    open, and ``set_digitizer()`` with no arguments removes both.

    Omitted params fall back to the registry defaults - nothing is carried over
    from the converter being replaced. A caller changing one end therefore
    passes the other end's current params (``describe()["digitizer"]`` reports
    them) rather than relying on a guess here about what survives a swap.
    """
    _CHAIN.set_digitizer(_converter("dac", dac_type_id, dac_params),
                         _converter("adc", adc_type_id, adc_params))
    return _describe()


@_guard
def set_digitizer_param(role: str, name: str, value: Any) -> Dict[str, Any]:
    """
    Change one parameter of an installed converter, e.g. the DAC's carrier
    power. This is :func:`set_param` for the two stages that have no component
    index.
    """
    if role not in ("dac", "adc"):
        raise ValueError(f"role must be 'dac' or 'adc', got {role!r}")
    existing = _CHAIN.dac if role == "dac" else _CHAIN.adc
    if existing is None:
        raise ValueError(f"this chain has no {role.upper()}")
    rebuilt = _with_param(existing, name, value)
    if role == "dac":
        _CHAIN.set_digitizer(rebuilt, _CHAIN.adc)
    else:
        _CHAIN.set_digitizer(_CHAIN.dac, rebuilt)
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


def _outside_span(span: tuple, start: float, stop: float) -> List[tuple]:
    """
    The parts of the sweep ``start..stop`` that fall outside ``span``.

    A band is one interval, so a sweep can leave it at either end and the answer
    is at most two intervals. They are cut at the band edge itself rather than at
    the nearest sampled frequency: the edge is a datasheet figure, while the grid
    is only where this sweep happened to look.
    """
    low, high = span
    regions = []
    if start < low:
        regions.append((start, min(low, stop)))
    if stop > high:
        regions.append((max(high, start), stop))
    return regions


def _extrapolated_stages(start: float, stop: float) -> List[Dict[str, Any]]:
    """
    The stages whose datasheet does not cover all of a sweep, and where.

    Each entry carries the band the stage is tabulated over and the parts of the
    sweep outside it, so a view can mark them per stage - one shaded region per
    stage rather than one for the chain, because which part ran out of data is
    the thing worth knowing, and two stages ending at different frequencies say
    different things about the same curve.

    The band comes from the model (see :func:`_defined_span`), so a stage
    appears here for the same reason its gain is an estimate there and cannot
    disagree with it.
    """
    out = []
    for index, (label, component, kind) in enumerate(_CHAIN.stages()):
        span = _defined_span(component)
        if span is None:
            continue                        # answers everywhere; nothing to flag
        regions = _outside_span(span, start, stop)
        if not regions:
            continue
        out.append({
            "stage_index": index,
            "label": label,
            "kind": kind,
            "type_label": _type_label(component),
            "span_from_hz": _num(span[0]),
            "span_to_hz": _num(span[1]),
            "regions_hz": [[_num(low), _num(high)] for low, high in regions],
        })
    return out


@_guard
def sweep_gain(start_hz: float, stop_hz: float, n: int = 401,
               log: bool = False) -> Dict[str, Any]:
    """
    Total chain gain in dB over a carrier-frequency sweep.

    ``extrapolated`` lists the stages that are outside their datasheet somewhere
    in this sweep. They answer there rather than returning NaN - a NaN in a dB
    sum would take the whole curve with it - so the gain is continuous and
    nothing in it shows where the measurements stopped. This is that, said
    separately: the numbers over those regions are indications, not
    specifications. An empty list is a positive statement that every stage
    covers the whole sweep.
    """
    start, stop = float(start_hz), float(stop_hz)
    freq = _grid(start, stop, n, bool(log))
    gain = np.asarray(_CHAIN.total_gain(freq), dtype=float)
    if gain.ndim == 0:
        gain = np.full_like(freq, float(gain))
    return {"freq_hz": _arr(freq), "gain_db": _arr(gain),
            "min_db": _num(np.nanmin(gain)), "max_db": _num(np.nanmax(gain)),
            "extrapolated": _extrapolated_stages(start, stop)}


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
def _suggested_filename(name: str) -> str:
    """
    A chain's name as a filename. Spaces become underscores, and so does
    anything else that is not a letter, digit, dash or dot - a name is free
    text a user typed, and ``Cooldown 12/A`` must not turn into a path.
    """
    safe = "".join(char if (char.isalnum() or char in "-_.") else "_"
                   for char in name.strip())
    return f"{safe.lower() or 'chain'}.json"


@_guard
def to_json(indent: int = 2) -> Dict[str, Any]:
    """
    The chain as the JSON a notebook reloads with ``SignalChain.load``.

    This is what makes the browser build a record and not just a view: what it
    hands back is the same file format, produced by the same ``to_dict`` - so
    the name, description and metadata set here are in it too.
    """
    return {"json": json.dumps(_CHAIN.to_dict(), indent=int(indent)),
            "suggested_filename": _suggested_filename(_CHAIN.name)}


@_guard
def notebook(carrier_hz: float = 1.5e9, spectral_hz: float = 1.0e3,
             reference: Optional[Any] = None, at: str = "input",
             gain_start_hz: float = 1.0e8, gain_stop_hz: float = 3.0e9,
             spectral_start_hz: float = 1.0e-2,
             spectral_stop_hz: float = 1.0e3,
             source_root: str = "") -> Dict[str, Any]:
    """
    A notebook that analyses the current chain, as ``.ipynb`` text.

    The chain travels inside it as the same file :func:`to_json` writes, so the
    notebook runs beside a download or on its own. The arguments are the view's
    operating point - the plane a budget is being read at, the spans the plots
    are showing - so the notebook opens on the values that were on screen when
    it was asked for rather than on a set of defaults nobody chose.

    Only the document is generated here; every number in it is computed when it
    runs, by these same modules. That is the same rule the browser follows, for
    the same reason: one implementation of the physics, and a view (or a
    generated notebook) that can only ask it questions.

    ``source_root`` is a checkout for the notebook to import from. The core is
    not published to an index, so a notebook that named no path would fail on
    its first cell in any kernel that has not installed it; the browser build
    passes the directory it was assembled from, and a script can pass its own.
    """
    document = notebook_export.build(
        _CHAIN,
        chain_json=json.dumps(_CHAIN.to_dict(), indent=2),
        chain_filename=_suggested_filename(_CHAIN.name),
        carrier_hz=float(carrier_hz), spectral_hz=float(spectral_hz),
        reference=reference, at=at,
        gain_span_hz=(float(gain_start_hz), float(gain_stop_hz)),
        spectral_span_hz=(float(spectral_start_hz), float(spectral_stop_hz)),
        generated_by=_generated_by(), source_root=str(source_root or ""),
    )
    stem = _suggested_filename(_CHAIN.name)[:-len(".json")]
    return {"ipynb": json.dumps(document, indent=1),
            "suggested_filename": f"{stem}_analysis.ipynb",
            "chain_filename": _suggested_filename(_CHAIN.name)}


def _generated_by() -> str:
    """
    What produced a notebook, for the notebook to say so.

    A generated document that cannot name what generated it is the same problem
    the build stamp in the page's top bar solves: version-dependent output with
    no version on it.
    """
    import sys
    core = provenance().get("analog_chain_core")
    return (f"analog-chain-core {core or 'from source'} on Python "
            f"{sys.version.split()[0]}")


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
