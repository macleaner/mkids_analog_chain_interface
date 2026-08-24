"""
Component registry.

Maps a stable string type id (e.g. ``"cable.sma_ss086_cryo"``) to the class that
implements it, together with the metadata the GUI needs to present it and the
serializer needs to rebuild it.

Why a registry rather than ``getattr(hardware_models, class_name)``:

* Saved chain files reference a stable id, so a class can be renamed or moved to
  another module without invalidating files on disk. Old names keep working as
  aliases.
* Only deliberately registered classes are offered to the user. Scanning a
  module with ``inspect.getmembers`` also picks up imported base classes, which
  are abstract and crash when instantiated.
* Each component declares its own parameters - name, unit, range, default - so
  the GUI builds inputs from a real specification instead of guessing from
  parameter-name substrings, and the serializer records exactly those values.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

# JSON types a parameter value is allowed to take. Anything else is rejected at
# construction time rather than being silently dropped at save time.
JSON_SCALARS = (int, float, str, bool)


@dataclass(frozen=True)
class ParamSpec:
    """Declares one constructor parameter of a component."""

    name: str
    default: Any = None
    label: Optional[str] = None
    unit: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    step: Optional[float] = None
    kind: str = "float"  # one of: float, int, str, bool
    help: str = ""
    #: If set, the only accepted values. Lets the GUI offer a choice widget
    #: instead of a free input that would fail validation in the constructor.
    choices: Optional[Tuple[Any, ...]] = None

    @property
    def display_label(self) -> str:
        return self.label or self.name.replace("_", " ").title()

    def coerce(self, value: Any) -> Any:
        """Convert a value to this parameter's declared type."""
        if self.kind == "float":
            return float(value)
        if self.kind == "int":
            return int(value)
        if self.kind == "bool":
            return bool(value)
        return str(value)

    def validate(self, value: Any) -> Any:
        """Coerce and range-check, raising ValueError with a usable message."""
        try:
            coerced = self.coerce(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"parameter {self.name!r} expects {self.kind}, got {value!r}"
            ) from exc
        if self.choices is not None:
            allowed = [self.coerce(c) for c in self.choices]
            if coerced not in allowed:
                raise ValueError(
                    f"parameter {self.name!r} = {coerced} is not one of the "
                    f"permitted values {allowed}"
                )
            return coerced
        if self.kind in ("float", "int"):
            if self.minimum is not None and coerced < self.minimum:
                raise ValueError(
                    f"parameter {self.name!r} = {coerced} is below the minimum "
                    f"{self.minimum}{(' ' + self.unit) if self.unit else ''}"
                )
            if self.maximum is not None and coerced > self.maximum:
                raise ValueError(
                    f"parameter {self.name!r} = {coerced} is above the maximum "
                    f"{self.maximum}{(' ' + self.unit) if self.unit else ''}"
                )
        return coerced


@dataclass(frozen=True)
class RegistryEntry:
    """A registered component class plus its presentation metadata."""

    type_id: str
    cls: type
    category: str
    label: str
    params: Tuple[ParamSpec, ...] = ()
    aliases: Tuple[str, ...] = ()
    doc: str = ""

    def param(self, name: str) -> ParamSpec:
        for spec in self.params:
            if spec.name == name:
                return spec
        raise KeyError(f"{self.type_id} has no parameter {name!r}")


_ENTRIES: Dict[str, RegistryEntry] = {}
_BY_ALIAS: Dict[str, str] = {}

# Modules whose import side effect is registering components. Imported lazily so
# that registry.py itself stays importable from those same modules.
_COMPONENT_MODULES = ("hardware_models",)
_loaded = False


def ensure_loaded() -> None:
    """
    Import the modules that register components, if not already done.

    Registration is an import side effect, so any lookup has to guarantee the
    defining modules have been imported. Without this, loading a chain in a
    script that never imported hardware_models would fail with a misleading
    "unknown component type" for every entry in the file.
    """
    global _loaded
    if _loaded:
        return
    # Set first: the imports below re-enter this module via @register, and a
    # component module importing another would otherwise recurse.
    _loaded = True
    import importlib

    for module_name in _COMPONENT_MODULES:
        importlib.import_module(module_name)


def register(type_id: str, *, category: str, label: Optional[str] = None,
             params: Tuple[ParamSpec, ...] = (),
             aliases: Tuple[str, ...] = ()) -> Callable[[type], type]:
    """
    Class decorator registering a component under a stable ``type_id``.

    ``aliases`` should include any previously-used identifier - in particular the
    original Python class name - so chain files written before the registry
    existed still load.
    """

    def decorator(cls: type) -> type:
        if type_id in _ENTRIES:
            raise ValueError(f"duplicate component type_id {type_id!r}")

        # Always accept the Python class name, so pre-registry files still load.
        all_aliases = tuple(dict.fromkeys((cls.__name__,) + tuple(aliases)))

        entry = RegistryEntry(
            type_id=type_id,
            cls=cls,
            category=category,
            label=label or cls.__name__,
            params=tuple(params),
            aliases=all_aliases,
            doc=(cls.__doc__ or "").strip(),
        )
        _ENTRIES[type_id] = entry
        for alias in all_aliases:
            existing = _BY_ALIAS.get(alias)
            if existing is not None and existing != type_id:
                raise ValueError(
                    f"alias {alias!r} already maps to {existing!r}, "
                    f"cannot also map to {type_id!r}"
                )
            _BY_ALIAS[alias] = type_id

        # Let instances report their own id, which is what to_dict() records.
        cls.type_id = type_id
        cls.registry_params = tuple(params)
        return cls

    return decorator


def resolve(type_id: str) -> RegistryEntry:
    """Look up an entry by type id or by any registered alias."""
    ensure_loaded()
    if type_id in _ENTRIES:
        return _ENTRIES[type_id]
    canonical = _BY_ALIAS.get(type_id)
    if canonical is None:
        raise KeyError(
            f"unknown component type {type_id!r}. "
            f"Known types: {', '.join(sorted(_ENTRIES))}"
        )
    return _ENTRIES[canonical]


def create(type_id: str, params: Optional[Dict[str, Any]] = None,
           name: Optional[str] = None,
           warnings: Optional[List[str]] = None):
    """
    Instantiate a registered component, validating its parameters.

    Unknown parameter names raise rather than being silently ignored, so a
    stale or hand-edited chain file fails loudly instead of quietly loading a
    component that differs from the one that was saved.

    A *declared* parameter that is absent from ``params`` falls back to its
    default - which is what lets a file written before a parameter was added
    still load - but the substitution is appended to ``warnings`` so a caller
    can surface it. Silent default substitution was the original format's worst
    failure mode; it must never happen without a trace.
    """
    entry = resolve(type_id)
    supplied = dict(params or {})

    declared = {spec.name for spec in entry.params}
    unexpected = set(supplied) - declared
    if unexpected:
        raise ValueError(
            f"{entry.type_id} got unexpected parameter(s) "
            f"{sorted(unexpected)}; declared parameters are {sorted(declared)}"
        )

    kwargs = {}
    for spec in entry.params:
        if spec.name in supplied:
            kwargs[spec.name] = spec.validate(supplied[spec.name])
        elif spec.default is not None:
            kwargs[spec.name] = spec.default
            if warnings is not None:
                warnings.append(
                    f"{entry.label}: parameter {spec.name!r} was missing from "
                    f"the file; using default {spec.default!r}"
                    f"{(' ' + spec.unit) if spec.unit else ''}"
                )
        else:
            raise ValueError(
                f"{entry.type_id} requires parameter {spec.name!r}"
            )
    if name is not None:
        kwargs["name"] = name
    return entry.cls(**kwargs)


def entries() -> List[RegistryEntry]:
    """All registered entries, sorted by category then label."""
    ensure_loaded()
    return sorted(_ENTRIES.values(), key=lambda e: (e.category, e.label))


def by_category() -> Dict[str, List[RegistryEntry]]:
    """Registered entries grouped by category, preserving CATEGORY_ORDER."""
    grouped: Dict[str, List[RegistryEntry]] = {}
    for entry in entries():
        grouped.setdefault(entry.category, []).append(entry)
    ordered = {c: grouped[c] for c in CATEGORY_ORDER if c in grouped}
    for category in sorted(grouped):
        ordered.setdefault(category, grouped[category])
    return ordered


# Presentation order for the component library tree.
CATEGORY_ORDER = ("Amplifiers", "Cables", "Attenuators", "Filters", "Converters")
