"""
Base component classes for RF signal chain elements.

Every concrete component inherits from one of these and records the parameters
it was constructed with by passing them to ``super().__init__(params=...)``.

That explicit hand-off is the point. The previous design inferred parameters at
save time by matching ``inspect.signature(__init__)`` names against instance
attributes, which silently dropped any parameter whose attribute had a different
name or a non-JSON value - reloading then substituted the constructor default
with no warning. Declaring them here means a saved chain records exactly what
was used to build it.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from registry import JSON_SCALARS


class Component(ABC):
    """
    Abstract base class for signal chain components.

    Subclasses implement ``gain(frequency)`` and, if they contribute noise,
    ``noise(frequency)``.
    """

    #: Stable serialization id, set by the ``registry.register`` decorator.
    type_id: Optional[str] = None

    def __init__(self, name: Optional[str] = None,
                 component_type: Optional[str] = None,
                 params: Optional[Dict[str, Any]] = None):
        """
        Parameters
        ----------
        name : str, optional
            Human-readable label. Defaults to the class name.
        component_type : str, optional
            Broad kind ('passive', 'active', 'dac', 'adc').
        params : dict, optional
            The constructor arguments that define this component, recorded
            verbatim for serialization. Values must be JSON scalars.
        """
        self.name = name if name is not None else self.__class__.__name__
        self.component_type = component_type if component_type is not None else "generic"
        self._params = self._check_params(params or {})

    def _check_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Reject non-serializable parameters at construction, not at save."""
        for key, value in params.items():
            if not isinstance(value, JSON_SCALARS):
                raise TypeError(
                    f"{type(self).__name__} parameter {key!r} has type "
                    f"{type(value).__name__}, which cannot be serialized. "
                    f"Component parameters must be one of "
                    f"{', '.join(t.__name__ for t in JSON_SCALARS)}."
                )
        return dict(params)

    @property
    def params(self) -> Dict[str, Any]:
        """The constructor arguments that define this component."""
        return dict(self._params)

    @abstractmethod
    def gain(self, frequency):
        """
        Return the gain/loss of this component in dB.

        Parameters
        ----------
        frequency : float or np.ndarray
            Frequency in Hz

        Returns
        -------
        float or np.ndarray
            Gain in dB (negative values indicate loss)
        """

    def noise(self, frequency):
        """
        Return the noise power spectral density of this component in W/Hz.

        Not all components contribute noise; the default returns 0.
        """
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict suitable for JSON."""
        if self.type_id is None:
            raise TypeError(
                f"{type(self).__name__} is not registered, so it cannot be "
                f"serialized. Apply the @registry.register decorator to it."
            )
        return {"type": self.type_id, "name": self.name, "params": self.params}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Component":
        """Rebuild a component from ``to_dict`` output."""
        import registry

        return registry.create(data["type"], data.get("params"), data.get("name"))

    def __repr__(self):
        args = ", ".join(f"{k}={v!r}" for k, v in self._params.items())
        return f"{self.__class__.__name__}({args})"

    def __str__(self):
        return self.name


class PassiveComponent(Component):
    """Base class for passive components (cables, attenuators, filters)."""

    def __init__(self, name=None, params=None):
        super().__init__(name=name, component_type="passive", params=params)


class ActiveComponent(Component):
    """Base class for active components (amplifiers)."""

    def __init__(self, name=None, params=None):
        super().__init__(name=name, component_type="active", params=params)


class DACComponent(Component):
    """Base class for Digital-to-Analog Converter components."""

    def __init__(self, name=None, params=None):
        super().__init__(name=name, component_type="dac", params=params)


class ADCComponent(Component):
    """Base class for Analog-to-Digital Converter components."""

    def __init__(self, name=None, params=None):
        super().__init__(name=name, component_type="adc", params=params)
