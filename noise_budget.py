"""
Noise budget results.

A noise budget is every noise source in the system referred to one reference
plane. Sources upstream of the plane are referred forward (their gain to the
plane is added); sources downstream are referred backward (the gain between the
plane and the source is subtracted). Both follow from one expression:

    contribution_dBm = intrinsic_dBm + C(reference_plane) - C(source_plane)

where C is the cumulative gain from the chain input to a plane.

The referred total is not a power that could be measured at that plane - a
downstream source divided back through a lossy stage can dominate it. It is the
equivalent noise at that plane, which is what an SNR or system noise temperature
at that plane is built from.
"""

from dataclasses import dataclass
from typing import Any, Dict, List

import numpy as np

from utils import kb, to_dbm


def as_temperature(power_w_per_hz):
    """Convert a noise PSD in W/Hz to an equivalent noise temperature in K."""
    return np.asarray(power_w_per_hz, dtype=float) / kb


def _magnitude(value):
    """Scalar magnitude of a possibly-array value, for ranking."""
    arr = np.asarray(value, dtype=float)
    if arr.size == 0:
        return 0.0
    finite = arr[np.isfinite(arr)]
    return float(np.max(finite)) if finite.size else 0.0


@dataclass(frozen=True)
class NoiseContribution:
    """One noise source, referred to the budget's reference plane."""

    label: str
    #: 'dac', 'adc', 'active', 'passive' or 'generic'.
    kind: str
    #: Where this source's noise is defined - 'input' or 'output'.
    noise_reference: str
    #: The source's own noise at its own defining plane, W/Hz.
    intrinsic_w: Any
    #: Gain applied to refer it to the reference plane, dB. Negative means the
    #: source is downstream and was referred backward.
    referral_gain_db: Any
    #: The referred contribution at the reference plane, W/Hz.
    power_w: Any

    @property
    def intrinsic_k(self):
        """The source's own noise as a temperature, K."""
        return as_temperature(self.intrinsic_w)

    @property
    def temperature_k(self):
        """The referred contribution as a temperature, K."""
        return as_temperature(self.power_w)

    @property
    def power_dbm_per_hz(self):
        return to_dbm(self.power_w)

    @property
    def is_downstream(self):
        """True if this source sits after the reference plane."""
        return _magnitude(self.referral_gain_db) < 0 or bool(
            np.all(np.asarray(self.referral_gain_db, dtype=float) < 0))


@dataclass
class NoiseBudget:
    """
    Every noise source in a chain, referred to one reference plane.

    ``contributions`` is ordered largest first, so the dominant source is the
    first entry.
    """

    #: Human-readable reference plane, e.g. "LNA (input)".
    reference: str
    carrier_hz: Any
    spectral_hz: Any
    contributions: List[NoiseContribution]

    @property
    def total_w(self):
        """Total referred noise PSD at the reference plane, W/Hz."""
        if not self.contributions:
            return 0.0
        total = self.contributions[0].power_w
        for contribution in self.contributions[1:]:
            total = total + contribution.power_w
        return total

    @property
    def total_k(self):
        """Total referred noise as an equivalent temperature, K."""
        return as_temperature(self.total_w)

    @property
    def total_dbm_per_hz(self):
        return to_dbm(self.total_w)

    def fraction(self, contribution):
        """This source's share of the total, 0-1."""
        total = np.asarray(self.total_w, dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.asarray(contribution.power_w, dtype=float) / total

    def dominant(self):
        """The largest contributor, or None for an empty budget."""
        return self.contributions[0] if self.contributions else None

    def as_dict(self) -> Dict[str, Any]:
        """Label -> referred power in W/Hz, matching the older return shape."""
        return {c.label: c.power_w for c in self.contributions}

    def to_rows(self) -> List[Dict[str, Any]]:
        """Flat rows for CSV export or a GUI table."""
        rows = []
        for c in self.contributions:
            rows.append({
                "source": c.label,
                "kind": c.kind,
                "referred_from": c.noise_reference,
                "intrinsic_w_per_hz": c.intrinsic_w,
                "intrinsic_K": c.intrinsic_k,
                "referral_gain_dB": c.referral_gain_db,
                "contribution_w_per_hz": c.power_w,
                "contribution_dBm_per_hz": c.power_dbm_per_hz,
                "contribution_K": c.temperature_k,
                "fraction_of_total": self.fraction(c),
            })
        return rows

    def table(self) -> str:
        """
        Aligned text table of the budget.

        Requires scalar frequencies; for a sweep, build a budget per frequency.
        """
        for value in (self.carrier_hz, self.spectral_hz):
            if np.asarray(value).ndim != 0:
                raise ValueError(
                    "table() needs scalar frequencies; build one budget per "
                    "frequency for a sweep, or use to_rows()."
                )

        header = (f"Noise referred to {self.reference}   "
                  f"carrier {float(self.carrier_hz)/1e9:g} GHz, "
                  f"offset {float(self.spectral_hz):g} Hz")
        columns = (f"{'source':<16}{'own noise':>12}{'own T':>11}"
                   f"{'referral':>10}{'referred':>12}{'T_eq':>12}{'share':>8}")
        units = (f"{'':<16}{'[W/Hz]':>12}{'[K]':>11}"
                 f"{'[dB]':>10}{'[W/Hz]':>12}{'[K]':>12}{'[%]':>8}")
        lines = [header, "=" * len(columns), columns, units, "-" * len(columns)]

        for c in self.contributions:
            lines.append(
                f"{c.label[:15]:<16}"
                f"{float(c.intrinsic_w):>12.3e}"
                f"{float(c.intrinsic_k):>11.2f}"
                f"{float(c.referral_gain_db):>+10.2f}"
                f"{float(c.power_w):>12.3e}"
                f"{float(c.temperature_k):>12.2f}"
                f"{100 * float(self.fraction(c)):>8.2f}"
            )

        lines.append("-" * len(columns))
        lines.append(
            f"{'TOTAL':<16}{'':>12}{'':>11}{'':>10}"
            f"{float(self.total_w):>12.3e}"
            f"{float(self.total_k):>12.2f}"
            f"{100.0:>8.2f}"
        )
        return "\n".join(lines)

    def __str__(self):
        return self.table()
