"""
A runnable analysis notebook, generated for one chain.

The browser build already hands back the chain file. This hands back something
that knows what to do with it: a notebook that loads that file, prints what is
in it, reproduces the page's two plots and its budget table with matplotlib -
plus the noise spectrum referred to the plane the budget is taken at, which the
page draws one plane at a time - exports the budget, then changes one component
and compares. The operations someone would otherwise retype from the
walkthrough with their own labels substituted in.

It is generated *for* a chain rather than being a fixed template with a
filename dropped into it. The labels in the code are this chain's labels, the
plane the budget is taken at and the spans the sweeps run over are the ones on
screen when the notebook was asked for, and the component the compare section
rebuilds is one that is actually in the chain, given a value that component's
own ``ParamSpec`` accepts. A generic template would hand someone
``chain.get_index("LNA")`` for a chain with no LNA in it, which fails on the
cell that is supposed to be teaching them the call.

Two things it deliberately does *not* do:

* **No analysis happens here.** Every number in the notebook is computed when
  the notebook runs, by the same modules the page runs - this writes the calls,
  not their results. So a notebook cannot report a figure the chain does not
  produce, and there is no second implementation of anything.
* **No new file format.** The chain is embedded verbatim as the chain file
  ``to_dict`` writes, so the notebook *is* the chain the GUI had open - it
  reads nothing off disk to find out what it is about, and needs no download
  to have happened. Pointing it at a saved file instead is one assignment.

``tests/test_notebook_export.py`` executes every generated code cell, because
the only useful guarantee about a generated notebook is that it runs.
"""

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

import registry

#: What to tell someone whose kernel cannot import the core modules, once every
#: route the notebook can try itself has failed. It does not offer
#: ``pip install analog-chain-core``: the distribution is not published to any
#: index, and a suggestion that cannot work is worse than none.
INSTALL_HINT = (
    "the analog chain modules are not importable, and no checkout was found.\n"
    "This package is not on PyPI - it is installed from a checkout of the "
    "repository:\n"
    "    python -m pip install /path/to/analog_chain_interface\n"
    "Or skip installing and set REPO_ROOT at the top of this cell to that "
    "directory; the modules are imported from there."
)


# --------------------------------------------------------------------------
# emitting python
# --------------------------------------------------------------------------
def _number(value: float) -> str:
    """
    A float as a literal someone would have typed: ``1.5e9``, not
    ``1500000000.0`` and not ``1.5e+09``. Generated code is read, so it is
    formatted like the rest of the repo's.
    """
    text = f"{float(value):g}".replace("e+0", "e").replace("e+", "e") \
                              .replace("e-0", "e-")
    return text if ("." in text or "e" in text or "inf" in text) else text + ".0"


def _literal(value) -> str:
    """
    A value as a Python literal, quoted the way the rest of the notebook is.

    ``repr`` would be enough except that it single-quotes strings while every
    hand-written line around it uses double quotes, and ``json.dumps`` cannot be
    used for the whole thing because a boolean parameter would come out as
    ``true``. So: JSON for the strings, ``repr`` for everything else.
    """
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, dict):
        return "{" + ", ".join(f"{_literal(k)}: {_literal(v)}"
                               for k, v in value.items()) + "}"
    return repr(value)


def _text_literal(text: str) -> str:
    """
    ``text`` as a Python string literal for a generated cell.

    A raw triple-quoted string keeps the embedded chain file readable as itself
    in the notebook, and keeps its escapes intact: a description with a newline
    in it is ``\\n`` in the file, and a cooked literal would turn that into a
    real newline, which is not legal inside a JSON string. ``json.dumps``
    cannot emit ``\"\"\"`` or a trailing backslash, so those delimiters are
    always safe - the check is here anyway, because a literal that closed early
    would be a syntax error in someone else's notebook rather than an error
    here.
    """
    if '"""' not in text and not text.endswith("\\"):
        return f'r"""\n{text}\n"""'
    return json.dumps(text)


def _aligned_constants(carrier_hz: float, spectral_hz: float,
                       reference, at: str) -> str:
    """
    The operating point as a block of assignments with the comments lined up.

    The two frequencies are the one place in the notebook where the
    *distinction* is the point, so they are worth reading as a pair rather than
    as lines whose comments happen to start at different columns. The plane is
    named here too, rather than repeated as a literal in each section that
    refers to it: three sections take it, and changing where the chain is
    judged from should be one edit.
    """
    pairs = [(f"CARRIER = {_number(carrier_hz)}", "Hz - the RF tone"),
             (f"SPECTRAL = {_number(spectral_hz)}", "Hz - offset from that tone")]
    if reference is not None:
        pairs += [(f"PLANE = {_literal(reference)}", "the plane noise is referred to,"),
                  (f"PLANE_AT = {_literal(at)}", "and which side of it")]
    width = max(len(code) for code, _ in pairs)
    return "\n".join(f"{code:<{width}}   # {note}" for code, note in pairs)


def _md(text: str) -> Dict[str, Any]:
    return {"cell_type": "markdown", "metadata": {}, "source": _lines(text)}


def _code(text: str) -> Dict[str, Any]:
    return {"cell_type": "code", "execution_count": None, "metadata": {},
            "outputs": [], "source": _lines(text)}


def _lines(text: str) -> List[str]:
    """
    Cell source as the list of lines nbformat stores.

    A single string is also valid, but every tool that diffs notebooks diffs
    this form, and a generated notebook that someone edits should not first
    reformat itself.
    """
    return text.strip("\n").splitlines(keepends=True)


# --------------------------------------------------------------------------
# choosing what the notebook talks about
# --------------------------------------------------------------------------
def _default_plane(chain) -> Tuple[Optional[Any], str]:
    """
    The plane to refer the budget to when the caller names none.

    Same choice the browser makes on a fresh chain - an LNA input if there is
    one, since that is the plane a cryogenic chain is usually judged at, and
    otherwise the first stage.
    """
    stages = chain.stages()
    if not stages:
        return None, "input"
    for label, _component, _kind in stages:
        if "lna" in label.lower():
            return label, "input"
    return stages[0][0], "input"


def _labels_by_index(chain) -> Dict[int, str]:
    """``chain.labels`` the other way round: component index -> its label."""
    return {index: label for label, index in chain.labels.items()}


def _nudged(spec, current) -> Optional[float]:
    """
    A different, still-valid value for ``spec``.

    Halving first, because that is the change that reads as deliberate on the
    quantities these components carry - an attenuator at -20 dB becomes -10 dB,
    a 0.5 m cable becomes 0.25 m - and the rest are fallbacks for a parameter
    where halving lands out of range or does not move.
    """
    try:
        current = float(current)
    except (TypeError, ValueError):
        return None
    step = float(spec.step) if spec.step else 1.0
    for candidate in (current * 0.5, current * 2.0, current + step,
                      current - step, spec.maximum, spec.minimum, spec.default):
        if candidate is None:
            continue
        try:
            value = spec.validate(round(float(candidate), 6))
        except (TypeError, ValueError):
            continue
        if abs(float(value) - current) > 1e-12:
            return value
    return None


def _variant_target(chain) -> Optional[Dict[str, Any]]:
    """
    A component in this chain to rebuild with one parameter changed.

    Requires a registry ``type_id`` and a numeric parameter that can be moved
    without leaving its declared range, because the point of the section is
    that the notebook and the browser both validate against the same spec.
    Returns None for a chain where no such component exists - the section
    is then left out rather than emitted with a value that would be rejected.
    """
    labels = _labels_by_index(chain)
    for index, component in enumerate(chain.components):
        type_id = getattr(component, "type_id", None)
        if not type_id:
            continue
        try:
            entry = registry.resolve(type_id)
        except KeyError:
            continue
        for spec in entry.params:
            if spec.kind not in ("float", "int") or spec.choices is not None:
                continue
            if spec.name not in component.params:
                continue
            value = _nudged(spec, component.params[spec.name])
            if value is None:
                continue
            if index not in labels:
                continue
            return {"label": labels[index],
                    "type_id": type_id, "params": dict(component.params),
                    "param": spec, "value": value}
    return None


# --------------------------------------------------------------------------
# the notebook
# --------------------------------------------------------------------------
def build(chain, *, chain_json: str, chain_filename: str,
          carrier_hz: float = 1.5e9, spectral_hz: float = 1.0e3,
          reference: Optional[Any] = None, at: str = "input",
          gain_span_hz: Sequence[float] = (1.0e8, 3.0e9),
          spectral_span_hz: Sequence[float] = (1.0e-2, 1.0e3),
          generated_by: str = "", source_root: str = "") -> Dict[str, Any]:
    """
    An ``.ipynb`` document (as a dict) that analyses ``chain``.

    Parameters
    ----------
    chain : SignalChain
        Read for its labels and its components. Nothing is computed from it -
        the notebook recomputes everything when it runs.
    chain_json : str
        The chain file, verbatim. It is embedded as the notebook's subject -
        the chain on screen travels inside the document rather than being
        looked up beside it.
    chain_filename : str
        What that file is called when saved. Used to name what the notebook
        writes - the budget CSV, the variant chain - and quoted as the name
        ``chain.save`` would give it.
    reference, at
        The plane to refer the budget to. Defaults to the browser's choice.
    source_root : str
        A checkout of this repository, written into the notebook as its
        ``REPO_ROOT``. The core is not on PyPI, so a notebook that named no
        path would have to be edited before its first cell ran; the build
        stamps in the checkout it was assembled from. Empty is fine - the
        notebook then looks for one around itself.
    """
    stages = chain.stages()
    if reference is None:
        reference, at = _default_plane(chain)

    cells: List[Dict[str, Any]] = []
    stem = chain_filename[:-5] if chain_filename.endswith(".json") else chain_filename

    # ---- title ----------------------------------------------------------
    # A blank line either side when there is a description, and no stray one
    # when there is not - the title cell is the first thing anyone reads.
    described = f"\n{chain.description.strip()}\n" if chain.description.strip() else ""
    stamp = f"\nGenerated by {generated_by}.\n" if generated_by else ""
    cells.append(_md(f"""
# {chain.name} — analysis
{described}
The chain itself is in the first code cell — this notebook analyses what the
GUI had open, with no file to fetch and nothing to point it at. It computes
nothing itself: every number below comes from the same modules the GUI runs, at
the version installed in *this* kernel.
{stamp}
**Two frequencies appear throughout and are not interchangeable.** The
*carrier* is the RF tone probing the system (MHz–GHz) and sets noise *levels*;
the *spectral* frequency is the offset from that carrier (Hz–MHz) and sets the
noise *shape*. Every noise call takes both. The values below are the ones the
GUI was set to.
"""))

    # ---- setup ----------------------------------------------------------
    cells.append(_code(f"""
import copy
import csv
import json
import os
import sys

# The core modules are top-level (`import signal_chain`), so they have to be
# importable. The distribution is not on PyPI, so this tries, in order: the
# kernel it is already installed in, the checkout below - the one the GUI was
# built from, filled in when this notebook was generated - and a walk up from
# wherever this notebook was saved, which covers a checkout somewhere else.
# Edit it if none of those is where your copy of the repo lives.
REPO_ROOT = {_literal(source_root)}


def find_repo_root(*starts):
    \"\"\"The nearest directory at or above any of `starts` holding the modules.\"\"\"
    for start in (s for s in starts if s):
        path = os.path.abspath(start)
        while True:
            if os.path.exists(os.path.join(path, "signal_chain.py")):
                return path
            parent = os.path.dirname(path)
            if parent == path:
                break
            path = parent
    return None


try:
    from signal_chain import SignalChain
except ModuleNotFoundError:
    root = find_repo_root(REPO_ROOT, os.path.abspath(""))
    if root is None:
        raise ModuleNotFoundError({json.dumps(INSTALL_HINT)})
    sys.path.insert(0, root)
    from signal_chain import SignalChain

try:
    import matplotlib.pyplot as plt
except ModuleNotFoundError:                     # the plots, and nothing else
    raise ModuleNotFoundError("the plots in this notebook need matplotlib:\\n"
                              "    python -m pip install matplotlib")

import numpy as np

import registry
from utils import to_dbm

plt.rcParams.update({{"figure.figsize": (7.5, 3.6), "figure.dpi": 110,
                     "axes.grid": True, "grid.alpha": 0.25,
                     "font.size": 9, "legend.fontsize": 8}})

{_aligned_constants(carrier_hz, spectral_hz, reference if stages else None, at)}

# Which copy of the core answered, and at which numpy. Three routes can
# satisfy the import above - an installed wheel among them, which may be older
# than the checkout - so a notebook kept as a record should say which one ran.
print(f"core  {{os.path.dirname(sys.modules['signal_chain'].__file__)}}")
print(f"numpy {{np.__version__}}")
"""))

    # ---- load -----------------------------------------------------------
    cells.append(_md(f"""
## 1. The chain

**This is the chain that was open in the GUI**, written into the cell below in
the same format **download chain.json** writes. It is the subject of the
notebook, not a default: nothing is looked up on disk, so no file lying around
can change what gets analysed, and no download has to have happened.

Everything after this is addressed by label, so setting `CHAIN_FILE` to a saved
chain analyses that one instead — a later cooldown of the same chain, or the
file this one is eventually saved as.
"""))
    cells.append(_code(f"""
# The chain the GUI had open, as its chain file. `SignalChain.from_dict` reads
# this; `chain.save(path)` writes it back out as {chain_filename} if you want
# the file itself.
CHAIN_JSON = {_text_literal(chain_json)}

# Analyse a saved chain file instead of the one above - a path, or None.
CHAIN_FILE = None
"""))
    cells.append(_code("""
if CHAIN_FILE is None:
    raw = json.loads(CHAIN_JSON)
    source = "the chain embedded in this notebook"
else:
    with open(CHAIN_FILE) as fh:
        raw = json.load(fh)
    source = CHAIN_FILE

chain = SignalChain.from_dict(raw)

# `from_dict` announces anything it had to substitute. A chain written before a
# parameter existed still loads, but the default it falls back to is reported,
# because a record quietly being a different chain than the one saved is the
# failure this format exists to prevent. The browser GUI drops these; a kernel
# can show them.
for warning in chain.load_warnings:
    print(f"load warning: {warning}")

print(f"analysing {source}")
print(f"file format:  v{raw.get('format_version')}   saved {raw.get('saved_utc')}")
print(f"metadata:     {chain.metadata or '(none)'}")
chain.summary()
"""))

    if not stages:
        cells.append(_md("""
---

## This chain is empty

It has no stages — no components and no converters — so there is no plane a
budget could be referred to and nothing to sweep. Build it up in the GUI (or
here, with `chain.add_component` / `chain.set_digitizer`) and generate the
notebook again; the analysis sections are written against the stages that exist.
"""))
        return _document(cells)

    # ---- what is in it --------------------------------------------------
    cells.append(_md("""
## 2. What is in it

`stages()` is the full signal path as `(label, component, kind)` — DAC first,
then the components in order, then the ADC. This is the list the GUI's middle
column renders.

`noise_reference` decides whether a component's own gain is applied to its
noise: an amplifier's noise temperature is quoted at its *input*, so it is
amplified along with the signal, while an attenuator's Johnson noise appears at
its *output* and is not attenuated by it.
"""))
    cells.append(_code("""
header = f"{'#':>2}  {'label':<14} {'kind':<8} {'ref':<7} {'class':<22} params"
print(header)
print("-" * len(header))
for i, (label, component, kind) in enumerate(chain.stages()):
    ref = getattr(component, "noise_reference", "-")
    params = ", ".join(f"{k}={v}" for k, v in component.params.items()) or "-"
    print(f"{i:>2}  {label:<14} {kind:<8} {ref:<7} {type(component).__name__:<22} {params}")
"""))

    # ---- gain -----------------------------------------------------------
    # gain_between needs two points, and naming a stage that is not in the
    # chain is exactly what a generic template would do - so the line is
    # emitted only for a chain that has two components to span. The far end is
    # the budget's own plane where that is a component, since the gain up to
    # the plane being read is the more useful of the two numbers; the whole
    # component span otherwise.
    span_pair = ""
    labels = _labels_by_index(chain)
    if len(chain.components) >= 2 and {0, len(chain.components) - 1} <= set(labels):
        first = labels[0]
        last = reference if reference in labels.values() else labels[len(chain.components) - 1]
        if last != first:
            span_pair = (f'\nprint(f"{first} -> {last}: '
                         f'{{chain.gain_between({_literal(first)}, {_literal(last)}, CARRIER):7.2f}} dB")')

    cells.append(_md("""
## 3. Gain

`total_gain` covers the whole path including the converters; `gain_between`
takes any two components, addressed by label or index; and `gain_between_planes`
takes the plane pair the GUI's **from plane** / **to plane** selects name,
summing only the stages that lie between them. Every model broadcasts over
numpy arrays, so the sweep is one call — this is the GUI's **total gain vs
carrier frequency** plot with both selects left alone, shaded lanes included.

A stage tabulated over a narrower band than the sweep answers outside it by
extending its measured curve, so the total has no gaps and nothing in the
numbers marks where the data stopped. Each stage says where through
`defined_span_hz`, and the lanes below are that: one per stage, over the
frequencies where its gain is an extension rather than a measurement. Treat
those as an indication — an amplifier's out-of-band response is set by its
matching networks, and no straight line predicts it.
"""))
    cells.append(_code(f"""
print(f"total gain @ {{CARRIER/1e9:.3f}} GHz: {{chain.total_gain(CARRIER):7.2f}} dB"){span_pair}

carrier_sweep = np.linspace({_number(gain_span_hz[0])}, {_number(gain_span_hz[1])}, 401)
gain_db = np.broadcast_to(np.asarray(chain.total_gain(carrier_sweep), dtype=float),
                          carrier_sweep.shape)

# The stages that are outside their datasheet somewhere in this sweep, with the
# part of it that is: the same two intervals per stage chain_api.sweep_gain
# reports to the GUI, computed here from the models themselves.
sweep_span = (carrier_sweep[0], carrier_sweep[-1])
extrapolated = []
for label, component, _kind in chain.stages():
    span = getattr(component, "defined_span_hz", None)
    if span is None:
        continue                     # answers everywhere; nothing to flag
    low, high = span()
    regions = ([(sweep_span[0], min(low, sweep_span[1]))] if sweep_span[0] < low else [])
    if sweep_span[1] > high:
        regions.append((max(high, sweep_span[0]), sweep_span[1]))
    if regions:
        extrapolated.append((label, (low, high), regions))

fig, ax = plt.subplots()
# One lane per flagged stage, stacked to fill the axes, in axes coordinates so
# they stay put whatever the gain range turns out to be.
for i, (label, (low, high), regions) in enumerate(extrapolated):
    lane = 1.0 / len(extrapolated)
    for j, (start, stop) in enumerate(regions):
        ax.axvspan(start / 1e9, stop / 1e9, ymin=i * lane, ymax=(i + 1) * lane,
                   color=f"C{{i}}", alpha=0.2, lw=0,
                   label=f"{{label}} extrapolated (datasheet "
                         f"{{low/1e9:g}}-{{high/1e9:g}} GHz)" if j == 0 else None)
ax.plot(carrier_sweep / 1e9, gain_db, color="#d9a441", lw=1.6, zorder=3)
ax.set_xlabel("carrier frequency (GHz)")
ax.set_ylabel("total gain (dB)")
ax.set_title(f"{{chain.name}} - total gain")
if extrapolated:
    ax.legend(fontsize="small", loc="lower left")
print(f"{{np.nanmin(gain_db):.2f}} dB at {{carrier_sweep[np.nanargmin(gain_db)]/1e9:.3f}} GHz"
      f"  ..  {{np.nanmax(gain_db):.2f}} dB at {{carrier_sweep[np.nanargmax(gain_db)]/1e9:.3f}} GHz")
for label, (low, high), regions in extrapolated:
    print(f"  extrapolated: {{label:<14}} datasheet {{low/1e9:g}}-{{high/1e9:g}} GHz")
plt.show()
"""))

    # ---- noise ----------------------------------------------------------
    cells.append(_md("""
## 4. Noise spectrum

`output_noise` returns the total PSD in W/Hz at the chain output; with
`contributions=True` it also returns the per-source breakdown, already referred
to the output. That is the GUI's right-hand plot with **per-source breakdown**
on. The sweep is over *spectral* frequency at a fixed carrier.
"""))
    cells.append(_code(f"""
spectral_sweep = np.logspace(np.log10({_number(spectral_span_hz[0])}), np.log10({_number(spectral_span_hz[1])}), 201)
total_w, contributions = chain.output_noise(CARRIER, spectral_sweep, contributions=True)

fig, ax = plt.subplots()
ax.semilogx(spectral_sweep, to_dbm(total_w), color="#d9a441", lw=2.0,
            label="total", zorder=3)
# contributions is {{label: W/Hz}}, ordered largest-first by peak, so the legend
# reads in the order the curves matter.
for label, watts in contributions.items():
    watts = np.broadcast_to(np.asarray(watts, dtype=float), spectral_sweep.shape)
    ax.semilogx(spectral_sweep, to_dbm(watts), lw=1.0, ls="--", label=label)
    print(f"  {{label:<14}} peak {{to_dbm(np.nanmax(watts)):8.2f}} dBm/Hz")

ax.set_xlabel("spectral offset from carrier (Hz)")
ax.set_ylabel("noise PSD (dBm/Hz)")
ax.set_title(f"output-referred noise @ {{CARRIER/1e9:.3f}} GHz carrier")
ax.legend(ncol=2, loc="upper right")
plt.show()
"""))
    cells.append(_md("""
A break in a trace is a non-finite value, not a zero: the DAC's phase-noise
model is a fit over datasheet points and goes non-finite just outside that
range (`hardware_models.py:137`), and `np.nan` plots as a gap rather than as a
wrong number. The GUI shows the same gap for the same reason.
"""))

    # ---- the same spectrum, at a plane ----------------------------------
    # `noise_budget` takes an array for the spectral frequency, so the plane's
    # spectrum is the budget of the next section swept rather than a different
    # calculation - which is the point of the section, and is asserted in it.
    cells.append(_md(f"""
## 5. The same spectrum at a reference plane

Section 4 is referred to the chain output — roughly what an analyser at the end
of the chain would see. This is the same sweep referred to
**{reference} ({at})** instead: every source referred to that plane, the ones
downstream of it divided by the gain between, which is what the budget in
section 6 does at a single offset. It is the GUI's right-hand plot with its
**reference plane** select moved off *chain output*.

`noise_budget` takes an array for the spectral frequency, so this is that same
call swept — not a second calculation that ought to agree with it. The dotted
line marks `SPECTRAL`, the offset the budget is read at, and the cell asserts
that the curve's value there is that budget's total.

Because sources behind the plane are referred *backward*, this is not a power
you could measure at the plane; see the note in section 6.
"""))
    cells.append(_code("""
# SPECTRAL goes on the axis so the marker sits on a point that was computed
# rather than one interpolated between its neighbours.
plane_sweep = np.unique(np.append(spectral_sweep, SPECTRAL))
plane_noise = chain.noise_budget(PLANE, CARRIER, plane_sweep, at=PLANE_AT)
plane_total_w = np.broadcast_to(np.asarray(plane_noise.total_w, dtype=float),
                                plane_sweep.shape)
marker = int(np.searchsorted(plane_sweep, SPECTRAL))

fig, ax = plt.subplots()
ax.semilogx(plane_sweep, to_dbm(plane_total_w), color="#d9a441", lw=2.0,
            label="total", zorder=3)
# Ranked by peak, so the legend reads in the order the curves matter - and in
# the same order as the rows of the budget table below.
for contribution in plane_noise.contributions:
    watts = np.broadcast_to(np.asarray(contribution.power_w, dtype=float),
                            plane_sweep.shape)
    ax.semilogx(plane_sweep, to_dbm(watts), lw=1.0, ls="--",
                label=contribution.label)

ax.axvline(SPECTRAL, color="#8a8a8a", lw=1.0, ls=":")
ax.plot(SPECTRAL, to_dbm(plane_total_w[marker]), "o", ms=5, color="#d9a441",
        zorder=4)
ax.set_xlabel("spectral offset from carrier (Hz)")
ax.set_ylabel(f"referred to {plane_noise.reference} (dBm/Hz)")
ax.set_title(f"noise referred to {plane_noise.reference} "
             f"@ {CARRIER/1e9:.3f} GHz carrier")
ax.legend(ncol=2, loc="upper right")
plt.show()

# The same call at a single offset, which is what the next section makes: this
# curve read at SPECTRAL *is* that budget's total, not an approximation of it.
assert plane_total_w[marker] == chain.noise_budget(
    PLANE, CARRIER, SPECTRAL, at=PLANE_AT).total_w

print(f"at {SPECTRAL:g} Hz offset: {to_dbm(plane_total_w[marker]):.2f} dBm/Hz "
      f"referred to {plane_noise.reference}")
print(f"over the sweep:  {to_dbm(np.nanmin(plane_total_w)):.2f}"
      f" .. {to_dbm(np.nanmax(plane_total_w)):.2f} dBm/Hz")
"""))

    # ---- budget ---------------------------------------------------------
    cells.append(_md(f"""
## 6. The noise budget

This is the GUI's table: section 5's curve read at one offset and decomposed
into what each source contributes there. Every noise source in the system is
referred to one plane, sources upstream referred forward and sources downstream
referred *backward* by dividing out the gain between them.

That backward referral is why the total is **not** a power you could measure at
the plane — an ADC behind an attenuator can dominate the budget at the input of
an LNA. It answers "what limits me here", not "what would a power meter read
here". `at=` picks which side of the named stage the plane sits on, and it is
required: input and output differ by that stage's gain.

Referred to **{reference} ({at})**, the plane the GUI was showing.
"""))
    cells.append(_code(f"""
budget = chain.noise_budget(PLANE, CARRIER, SPECTRAL, at=PLANE_AT)
print(budget.table("dBm/Hz"))
print(f"referred to:  {{budget.reference}}")
print(f"total:        {{budget.total_dbm_per_hz:.2f}} dBm/Hz "
      f"= {{budget.total_w:.4e}} W/Hz = {{budget.total_k:.1f}} K")
dominant = budget.dominant()
if dominant is not None:
    print(f"dominant:     {{dominant.label}} "
          f"({{budget.fraction(dominant)*100:.1f}}% of the total)")
"""))
    cells.append(_md("""
`to_rows()` is the export shape — every quantity in W/Hz, dBm/Hz *and* K, plus
each source's share, so changing units is picking a column rather than
converting anything. It drops straight into pandas, and into a spreadsheet:
"""))
    cells.append(_code(f"""
rows = budget.to_rows()
columns = ["source", "kind", "referred_from", "contribution_dBm_per_hz",
           "referral_gain_dB", "contribution_K", "fraction_of_total"]

try:
    import pandas as pd
    print(pd.DataFrame(rows)[columns].to_string(index=False))
except ImportError:
    for row in rows:
        print(f"  {{row['source']:<14}} {{row['contribution_dBm_per_hz']:9.2f}} dBm/Hz"
              f"  referral {{row['referral_gain_dB']:7.2f}} dB"
              f"  {{row['fraction_of_total']*100:5.1f}}%")

if rows:
    csv_path = {json.dumps(stem + "_budget.csv")}
    with open(csv_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\\nwrote {{csv_path}} - {{len(rows)}} sources, every unit in every column")
"""))
    cells.append(_md("""
Comparing planes shows where the budget's character changes. The GUI does one
plane at a time; a notebook can do all of them at once:
"""))
    cells.append(_code("""
print(f"{'plane':<24} {'total dBm/Hz':>13} {'K':>12}   dominant")
print("-" * 68)
for label, _component, _kind in chain.stages():
    for side in ("input", "output"):
        b = chain.noise_budget(label, CARRIER, SPECTRAL, at=side)
        dom = b.dominant()
        print(f"{label + ' (' + side + ')':<24} {b.total_dbm_per_hz:13.2f} "
              f"{b.total_k:12.1f}   {dom.label if dom is not None else '-'}")
"""))

    # ---- change one thing -----------------------------------------------
    target = _variant_target(chain)
    if target is not None:
        spec = target["param"]
        was = target["params"][spec.name]
        unit = f" {spec.unit}" if spec.unit else ""
        params = dict(target["params"])
        params[spec.name] = target["value"]
        title = f"{target['label']} {spec.name} = {target['value']}{unit}"
        cells.append(_md(f"""
## 7. Change one thing and compare

Rebuild the component rather than assigning to an attribute: several models
precompute interpolators from their parameters in `__init__`, so mutating an
attribute afterwards leaves those stale and the gain keeps coming from the old
value. `registry.create` also re-validates — the range it checks against is the
same `ParamSpec` the GUI's form checks against, so a value rejected here is
rejected there, with the same message.

Below: **{target['label']}**'s `{spec.name}` moved from {was}{unit} to
{target['value']}{unit}.
"""))
        cells.append(_code(f"""
variant = copy.deepcopy(chain)
variant.name = {_literal(title)}
index = variant.get_index({_literal(target['label'])})
variant.components[index] = registry.create(
    {_literal(target['type_id'])},
    {_literal(params)},
    name={_literal(target['label'])},
)

for candidate in (chain, variant):
    b = candidate.noise_budget(PLANE, CARRIER, SPECTRAL, at=PLANE_AT)
    print(f"{{candidate.name:<34}} gain {{candidate.total_gain(CARRIER):7.2f}} dB   "
          f"budget {{b.total_dbm_per_hz:8.2f}} dBm/Hz")

fig, ax = plt.subplots()
for candidate, style in ((chain, "-"), (variant, "--")):
    curve = np.broadcast_to(
        np.asarray(candidate.total_gain(carrier_sweep), dtype=float),
        carrier_sweep.shape)
    ax.plot(carrier_sweep / 1e9, curve, style, lw=1.5, label=candidate.name)
ax.set_xlabel("carrier frequency (GHz)")
ax.set_ylabel("total gain (dB)")
ax.legend()
plt.show()
"""))
        cells.append(_md("""
Validation is declared once, on the parameter spec, so this rejects what the
GUI rejects:
"""))
        cells.append(_code(f"""
spec = registry.resolve({_literal(target['type_id'])}).param({_literal(spec.name)})
print(f"{{spec.name}}: {{spec.minimum}} .. {{spec.maximum}} {{spec.unit}} "
      f"(default {{spec.default}})")
try:
    spec.validate(1e9)
except ValueError as exc:
    print(f"rejected: {{exc}}")
"""))
        cells.append(_md("""
Saving the variant writes the same format this notebook read, so it opens in
the GUI (**open chain…**) and reloads here — a what-if is a chain file like any
other, not a note in a notebook.
"""))
        cells.append(_code(f"""
variant_path = {json.dumps(stem + "_variant.json")}
variant.save(variant_path)

# Round-trip check: what comes back is the same chain, not an approximation.
reloaded = SignalChain.load(variant_path)
assert reloaded.to_dict()["components"] == variant.to_dict()["components"]
assert reloaded.total_gain(CARRIER) == variant.total_gain(CARRIER)
print(f"wrote and verified {{variant_path}} - drop it on the GUI's 'open chain...'")
"""))

    # ---- where next -----------------------------------------------------
    cells.append(_md("""
---

## Where to go next

- `chain.stages()` / `chain.resolve_plane()` — how planes are numbered, if you
  are writing your own referral
- `chain.add_component()` / `chain.set_digitizer()` / `chain.save()` — building
  a chain here instead of in the GUI; the file is the same either way
- `registry.entries()` — every component with its parameter specification, which
  is what the GUI's library column lists
- `chain_api` — the JSON-in / JSON-out facade the browser drives. It holds one
  module-level chain, which suits a GUI and is awkward here, but it returns the
  whole catalog as data and returns errors instead of raising
- `hardware_models.py` — the models themselves; each docstring records where its
  numbers come from
"""))
    return _document(cells)


def _document(cells: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Wrap cells as nbformat 4.4.

    No kernel *version* is pinned: the notebook is generated by whatever the
    GUI runs (Pyodide's Python, for the browser build) and opened by whatever
    the user has, and claiming the former would be a claim about the latter.
    """
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python",
                           "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 4,
    }
