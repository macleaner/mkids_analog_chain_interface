# Browser build

A single HTML file that runs the analog chain calculator in a browser with no
install. It boots CPython in the page (Pyodide/WASM), installs the
`analog-chain-core` wheel embedded in it, and drives that from a JavaScript
view.

**The physics is not ported.** Everything — component models, cascade algebra,
the noise budget — runs from the same wheel a notebook installs with
`pip install`. The JavaScript holds no chain state and does no arithmetic on
results; a unit change picks a different column that Python already computed.
So there is no second implementation to keep in sync.

## Open it

```bash
./open_web_gui.py
```

Builds whichever stages are out of date, then opens the page in your browser.
This is the one to use if you just want the calculator; the two stages below are
for when you care which of them ran.

`./open_web_gui.py --desktop` writes `~/.local/share/applications/analog-chain-calculator.desktop`,
after which the calculator is double-clickable and appears in the applications
menu. That file holds absolute paths, so it is generated rather than committed.

## Build

```bash
python -m pip wheel . --no-deps -w dist/ && python tools/assemble_web.py
```

Writes `dist/analog_chain_calculator.html` (~130 KB). Open it directly — no
server. `dist/` is gitignored; the artifact is reproducible from these sources.

Rebuild only what you touched:

| Changed | Rerun |
|---|---|
| `web/template.html` (UI) | `assemble_web.py` alone |
| any core module or `chain_api.py` | wheel, then `assemble_web.py` |
| `web/vendor/*` | `assemble_web.py` alone |

`open_web_gui.py` decides that from mtimes, and takes the wheel's own contents
as the list of sources for it — so adding a module to `py-modules` in
`pyproject.toml` does not also have to be recorded in the launcher.

## How assembly works

`web/template.html` carries five markers, each replaced with an inlined
payload. They are written as HTML/JS comments so the template stays valid and
greppable.

| Marker | Payload |
|---|---|
| `<!--__PYODIDE_TAG__-->` | the Pyodide loader `<script>` tag |
| `/*__UPLOT_CSS__*/` | `web/vendor/uPlot.min.css` |
| `/*__UPLOT_JS__*/` | `web/vendor/uPlot.iife.min.js` |
| `/*__CONFIG__*/` | build config as a JSON literal |
| `/*__WHEEL_B64__*/` | the wheel, base64, in a JS string literal |

The assembler writes nothing unless: the markers are present *and in source
order*; no payload contains a sequence that would close its enclosing element
early (`</script`, `</style`, `-->`, or a quote/backslash/newline in the
base64); the config parses as JSON; the wheel is a valid zip containing all
eight core modules; and the page's script block passes `node --check` (skipped
if node is absent).

## The seam

[`chain_api.py`](../chain_api.py) is the whole interface — JSON in, JSON out,
errors returned as `{"ok": false, "error": ...}` rather than raised, because a
view across a language boundary can display a message but cannot read a
traceback. It ships **in the wheel**, so it is equally a scripting API:

```python
import chain_api
chain_api.load_preset("cryo_example")
chain_api.budget("LNA", at="input", carrier_hz=1.5e9, spectral_hz=1e3)
```

Guarded by [`tests/test_chain_api.py`](../tests/test_chain_api.py), which
checks that every response really is JSON-serializable and that the facade
reports `SignalChain`'s numbers rather than any of its own.

For working with chains outside the GUI — including loading a chain this page
downloaded, and reproducing both of its plots — see
[`examples/analog_chain_walkthrough.ipynb`](../examples/analog_chain_walkthrough.ipynb),
which is the hand-written version of what **notebook.ipynb** generates.

Component forms are generated from `registry.ParamSpec`, and submitted values
go back through `ParamSpec.validate`. The browser panel and the Qt panel
therefore share one declaration of every parameter's range, unit and error
message.

## Building a chain in the page

**new chain** asks for a name and empties the chain — no components and no
converters. From there:

| To | Use |
|---|---|
| see what a component is before adding it | click it once in the library — its specs appear in **Model specs**, at the foot of that column |
| add a stage | double-click it in the component library, left column |
| edit a stage | click it — the card opens with its parameters |
| name a stage | the `label` field in that card — this is what a budget refers to and what the file records |
| tell two stages apart | each row reads *label · model · values* — `ColdAtten` `Attenuator` `-20 dB · 4 K` |
| reorder a stage | drag it by the `⋮⋮` handle, or use the `▲▼` that appear on the stage you are pointing at |
| set the endpoints | the **Converters** selects at the top of the signal chain |
| set the DAC carrier power | click the **DAC stage** (stage 0) — `Carrier Power` and `Gain` are in its card, like any other stage's parameters |
| model a digitizer that is not in the library | pick **Generic DAC** / **Generic ADC**, then state the carrier power, the phase-noise skirt and the ADC's input noise density in their cards |
| judge the chain without its converters | tick `Noiseless` on either card — that end drops out of the budget rather than contributing a small line to discount |
| remove an endpoint | its `×`, or its select back to *— none —* |
| name the chain, or annotate it | click the chain name in the top bar |
| see what any of that saves as | the **Chain file** tab, right-hand column |
| carry on in Jupyter | **notebook.ipynb**, top bar |
| give a pane more room | drag the gutter beside it — double-click the gutter to put it back |

A stage row says what the stage is called, what model it is, and the values
that separate it from another stage of the same model — the three things you
would otherwise have to open every card to see. The model name comes from
`describe()`'s `type_label`, the same string the library lists, and it is
dropped where the label already is that name: the converters are named after
their model, so stage 0 reads `AD9082_DAC`, not `AD9082_DAC [AD9082 DAC]`.

A component added without a label gets a generic one for its family — `Cable1`,
`Attenuator2`, the lowest number free for that family — because a label is what
a budget refers to and what the file records, so a stage cannot go without one.
The number is not a position: reordering moves a component and its label
together, so `Attenuator3` sitting fifth is a name, not a claim about where it
is. Rename it in the card to whatever the hardware actually is.

Only appended components can be reordered. The converters are the chain's
endpoints — `SignalChain` keeps them outside `components` and puts them at the
ends of every stage list — so dropping a stage on the DAC card means "first" and
on the ADC card means "last", rather than moving the converter. A reorder
renumbers components, so `move_component` rewrites `chain.labels` through the
same permutation: a label names a component, not a position, and a budget taken
by label refers to the same hardware before and after the move.

Which catalog entries are endpoints is not a list kept here: `catalog()`
reports a `role` of `dac`, `adc` or `component` per entry, derived from
`DACComponent`/`ADCComponent`, so a converter registered later is offered by
the Converters control rather than as an appendable component.

**Generic DAC** and **Generic ADC** are for a digitizer the library does not
model: a carrier at a chosen power with a power-law phase-noise skirt, and a
white input noise density. Their `Noiseless` boxes take that end out of the
budget altogether — zero, not a small number, so a stage with no noise is
skipped and the chain is judged on its components. That is a different question
from how the chain does with a given digitizer, and turning the levels down to
their minimum would not ask it.

A parameter's widget comes from its declared `kind`, so `Noiseless` is a
checkbox and not a text field. That matters more than it looks: typing into a
text field would submit the string `"false"`, and Python's `bool("false")` is
True, so the flag would read as set while the box said otherwise. The registry
now refuses that string outright, but the widget is where it stops being
possible to type.

A card's layout comes from the same place. A `ParamSpec` may declare a `group`,
which is the heading of a sub-box the parameter is collected into — the Generic
DAC's card puts its four skirt knobs under **Noise parameters**, leaving
`Carrier Power` and `Gain` outside it, because what the DAC puts out is not part
of its skirt. Six knobs in a flat list say nothing about which four describe one
thing. The view opens a box whenever the group changes as it renders down the
declared order, so it neither reorders anything nor knows any parameter by name;
`register` requires a group to be one unbroken run, since a split one would
render as two boxes under a single heading.

An empty chain has no stages, and therefore no plane a budget can be referred
to — the table says so instead of erroring, and the sweeps return zero gain and
zero noise. Nothing is autosaved: **new chain** discards what is on screen, so
download first.

### Model specs

Clicking a library entry describes it in the panel at the foot of that column,
without touching the chain: the registry's docstring, the gain curve, the gain
range and the value at the carrier, and what the model contributes as noise.

`component_specs` builds the component, asks it and drops it, so the figures are
the ones the chain will use — a component cannot read one way in the panel and
behave another way once added. Two things it decides rather than leaving to the
view:

* **the band.** The sweep runs over the carrier range the model is valid over,
  found by asking it. Every model with a tabulated curve declares that range
  outright, because it answers with a number everywhere — past the last
  tabulated point it extends the endpoint slope, clamped so it can neither show
  gain nor claim rejection deeper than anything measured (see
  [the shaded lanes](#where-the-datasheets-run-out)). A model that instead
  returns NaN outside its tabulated range is making the same statement the other
  way, and gets bisected for its edge. Either way the span is the datasheet's:
  `VLF-6700+` is drawn over 50 MHz – 19.89 GHz and `VHF-1320+` over
  1 MHz – 3.7 GHz, without either being written down here or any interpolator's
  knots being read by name. A model that answers everywhere and declares no band
  — a flat attenuator, a converter — has none of its own, so the gain plot's span
  is used instead and the axis says `plot span`, because "0.1–3 GHz" means
  something different in the two cases.
* **the unit for its noise.** A noise temperature only means anything for a
  source that is white near the carrier, so the model is evaluated across the
  spectral axis: an amplifier or a warm attenuator gets one temperature in K, a
  DAC's phase-noise skirt gets a density at the offset the budget is set to, and
  a filter — lossy, but not a source — reads `none`. So does a `noiseless`
  converter, which is the same statement about a stage that contributes nothing.

The carrier and the spectral offset are the budget's, so a spec is read at the
operating point being worked at. The figures are for the registry defaults,
which is what a double-click installs; the `at defaults` row says which values
those were, for the models where it makes a difference.

### Where the datasheets run out

Sweep the gain plot past the narrowest part in the chain and the curve keeps
going, with a shaded lane over the frequencies where it is an estimate.

Every model with a tabulated curve answers at any carrier frequency: past the
last measured point it extends the endpoint slope, capped so it can never report
more gain — or less loss — than the datasheet actually measured. Before, an
amplifier returned NaN outside its band, and since a chain's total gain is a dB
sum, one such stage blanked the whole curve from its band edge up. Asking for
0.1–12 GHz on a chain of 3 GHz amplifiers drew nothing above 3 GHz and gave no
reason for it.

An estimate that looks identical to a measurement is worse than a gap, so each
model also states the band it is quoting measured data over
(`defined_span_hz`), `sweep_gain` reports every stage whose band does not cover
the sweep, and the plot shades what that leaves:

* **one lane per stage**, stacked to fill the plot, each shaded only across its
  own out-of-band frequencies. Three lanes are three parts short of data — the
  question is which stages, not whether — and two stages whose bands end at
  different frequencies mark different regions of the same curve.
* **named in the legend**, so the lane says which unit is responsible:
  `LNA extrapolated · DC–3.00 GHz` is the band it *does* cover. Hovering the row
  gives the model and the wording; clicking it hides that lane and hands its
  height to the rest.
* **nothing shaded is a statement too.** Inside every stage's band the list is
  empty and the plot shades nothing, so an unmarked curve is measured data
  rather than an unimplemented check.

The regions are cut at the band edge, not at the nearest swept point, so they do
not move when the point count does. Which stages and which frequencies are
Python's answer — `chain_api.sweep_gain(...)["extrapolated"]`, guarded by
`tests/test_chain_api.py` — and the view only maps them to pixels. The
[notebook](#taking-it-to-jupyter) draws the same lanes in matplotlib from the
same `defined_span_hz`, so a figure taken to Jupyter carries the flag with it.

**Treat a shaded region as an indication, not a specification.** An amplifier's
out-of-band response is set by its matching networks, a real filter's far
stopband is re-entrant, and coax loss climbs as sqrt(f) — no straight line
predicts any of them. The cap keeps the estimate from ever flattering a budget,
which is the most that can honestly be claimed for it. **Noise does not
extrapolate at all**: a HEMT's noise rises steeply at both band edges and a
linear extension would understate it, so a carrier outside an amplifier's band
gets a flagged gain estimate and no noise figure — the budget says `—` rather
than quoting an invented one. `tests/test_extrapolation.py` holds these rules.

### The record

Clicking the chain name opens `name`, `description` and `metadata`. None of
these can be recovered from the components, and all three are in the saved
file, so a chain built in the page carries the same bookkeeping as one built in
a notebook — which cooldown, whose sample, which dataset. The panel opens
itself after **new chain**, since nothing else asks for any of it.

`metadata` is edited as a JSON object rather than as key/value rows, because it
is persisted verbatim: a row editor would store every value as a string, and a
cooldown id quietly becoming `"12"` is exactly how a record stops matching what
it documents. Text that does not parse is left alone for you to fix, and
`set_metadata` refuses anything `json.dumps` cannot write — the failure lands
on the edit that caused it rather than on a download months later.

The name is also what the download is called, so it is sanitized into a
filename: `Cooldown 12/A` gives `cooldown_12_a.json`, never a path.

### Seeing the file

The right-hand column tabs between **Noise budget** and **Chain file**. The
second is the chain as it would be saved — read-only, rewritten after every
edit, with the filename it would download as and its size on disk above it.
Adding a stage, reordering one, renaming it, editing a parameter, or filling in
the record all show up there as they happen, so what a chain object *is* is
visible while it is being built rather than only after downloading one and
opening it in an editor.

It is a view of the file, not a description of it. The panel calls the same
`to_json` the download button calls, so it is `SignalChain.to_dict()` output
and cannot disagree with what gets written; the `describe()` payload the rest
of the page draws from is shaped for the view and is *not* the file, so
rendering the file from that would be a second serializer to keep in step with
the first. It is printed with `textContent` and `white-space: pre`, so what is
on screen is byte for byte what lands on disk — no highlighter deciding where a
token ends, and no wrapped line pretending to be an indent level.

Only the visible tab costs a round trip: edits made with the budget up are
picked up when you switch back, not recomputed into a hidden panel.

### Taking it to Jupyter

**notebook.ipynb** downloads a second file: a notebook that analyses *this*
chain. Open it in Jupyter and Run All — it lists the stages, draws both of this
page's plots in matplotlib, draws the noise spectrum referred to the plane the
budget is taken at, prints the budget table, writes the budget out as CSV, then
rebuilds one component with a different value and compares the two. It is the
point where the page stops being enough: a fit across several cooldowns, a
sweep the page does not offer, a figure for a paper.

The plane-referred spectrum is the one section with no single control behind it
on the page. `noise_budget` accepts an array for the spectral frequency, so it
is the budget table swept rather than a second calculation — the notebook
asserts that the curve read at the budget's own offset *is* that budget's
total, and marks the point on the plot. Referring backwards means it is not a
power a meter would read at the plane; it is what limits you there, across the
offset range.

It is generated for the chain rather than being a fixed template with a
filename dropped in, so nothing in it has to be edited before it runs:

* **the labels are this chain's labels.** The budget is referred to the plane
  the table is showing, the sweeps run over the spans in the two plot boxes,
  and the carrier and spectral offset are the ones in the controls — so the
  notebook opens where the work left off rather than on defaults nobody chose.
  A generic template would hand someone `chain.get_index("LNA")` for a chain
  with no LNA in it, and fail on the cell meant to be teaching them the call.
* **the component it changes is one that is in the chain**, given a value that
  component's own `ParamSpec` accepts — so the compare section runs, and the
  cell that demonstrates a *rejected* value is the same validation the form
  beside it uses. A chain with nothing to vary gets no compare section instead
  of a broken one.
* **an empty chain says so.** With no stages there is no plane to refer a
  budget to and nothing to sweep, so the analysis sections are left out rather
  than emitted as cells that cannot run.

**The chain it analyses is the one that was on screen**, embedded in the first
code cell as the chain file — byte for byte what **download chain.json**
writes. It is the notebook's subject, not a default it falls back to: nothing
is looked up on disk, so no file lying around can change what gets analysed
and no download has to have happened first. The prose in the notebook and the
chain it runs on cannot come apart.

Redirecting it is one assignment — `CHAIN_FILE = "…json"`, right under the
chain — which is how the same analysis runs over a later cooldown of the same
hardware, or over a variant it wrote itself. And since the embedded text *is* a
chain file, `chain.save(...)` in any cell hands back the `.json`; no new format
is introduced by any of this.

What it does not carry is results. Every number in it is a call, computed by
the reader's own kernel at the reader's own numpy and scipy — which is the same
reason this page has a build stamp, and it is where the one known difference
between local and browser numbers ([above](#same-code-not-the-same-dependency-versions))
would show up. The notebook stamps what generated it, for the same reason.

Generated by [`notebook_export.py`](../notebook_export.py), which is in the
wheel, so `chain_api.notebook()` is available to a script as well. Guarded by
[`tests/test_notebook_export.py`](../tests/test_notebook_export.py), which
executes every code cell of a generated notebook — the only useful guarantee
about a generated notebook being that it runs.

#### Finding the core

**`analog-chain-core` is not published to PyPI**, so `pip install
analog-chain-core` cannot work and the notebook never suggests it. The setup
cell tries three things in order, and normally none of them needs doing by
hand:

1. the modules are already importable — the kernel installed them, or was
   started inside the checkout;
2. `REPO_ROOT`, at the top of that cell, which the build fills in with the
   checkout **this page was assembled from** (`source_root` in the build
   config). The page is built on the machine it is used on, so this is the
   route that usually fires, and it prints the directory it imported from;
3. a walk up from wherever the notebook was saved, which covers a checkout at
   some other path — a notebook saved inside one needs no path at all.

Only if all three miss does it raise, and it then names the two routes that
work: installing from a checkout,

```bash
python -m pip install /path/to/analog_chain_interface
```

or editing `REPO_ROOT` to point at one, which needs no install. A copy of the
page moved to another machine keeps the first machine's path, so its notebooks
fall through to (3) — a hint, not a dependency.

The plots need `matplotlib`, which is not bundled either — the notebook is a
few kilobytes of text, not an environment — and says so with the install line
rather than a bare `ModuleNotFoundError`. `pandas` is used if it is there and
skipped if it is not.

### Sizing the panes

The three columns and the plots are separated by draggable gutters: drag one to
give the room to whichever pane the work needs it in — a wide library while
picking components, a wide budget while reading one, tall plots while looking at
a curve. A gutter also takes the keyboard (tab to it, arrows to nudge, shift for
a bigger step), and a double-click or `Home` puts it back where it started.

The plots are resized rather than revealed: a plot fills whatever its box has
left under the caption and the controls, so height dragged into the bottom row
goes to the curves. Sizes are kept in `localStorage` and restored on the next
open. They are a workspace preference and say nothing about the hardware, so
they never touch the chain file — a chain downloaded here is byte for byte what
it would have been at any other pane size.

What is remembered is the size asked for, and what is used is that size clamped
to what the window can show: no pane can be dragged smaller than the point where
it stops being readable, and no column can squeeze the signal chain below its
minimum. So narrowing the window squeezes a column without forgetting how wide
it was dragged to be, and widening it back gives that width straight back. Below
1100px the columns stack into one scrolling page and there is nothing left to
drag.

### The type scale

Every size on the page is a step off one custom property, `--fs` in
`web/template.html`. Raise it and the whole page follows — widgets, tables,
documentation lines, the build stamp, and the plots with them: the tick and axis
labels are drawn to a canvas, so they cannot inherit the page's type, and are
handed a size measured off the caption above the plot rather than one written
into the plot code. The five steps (`--fs` down to `--fs4`) are the levels the
page uses; they are not sizes to be set one at a time.

The plots then take what is left. A plot's height is its box less its caption,
its controls and its legend, all measured — which is also how far the plot row
can be dragged down, so a larger `--fs`, or a control added to a plot box,
raises the floor instead of quietly costing the curves their height.

## Same code, not the same dependency versions

The wheel asks for `numpy>=1.22` / `scipy>=1.8`; Pyodide supplies whatever it
ships. Pyodide 0.27.7 gives Python 3.12.7, numpy 2.0.2, scipy 1.14.1, and the
page stamps all of it in the top bar.

Measured against a local numpy 2.3.5 / scipy 1.16.3 on the `cryo_example`
preset at 1.5 GHz / 1 kHz, referred to the LNA input:

| | local | browser |
|---|---|---|
| LNA contribution | 8.280000000000013e-23 | 8.280000000000013e-23 |
| AD9082 DAC contribution | 1.0649025920e-19 | 1.0642581733e-19 |
| total | −159.72037 dBm/Hz | −159.72300 dBm/Hz |

Analytic models agree bit for bit. The DAC is 0.06% apart because its phase
noise comes from a `scipy.optimize.curve_fit` that converges slightly
differently between versions. Physically negligible — far below any noise
measurement — but real, and worth removing: the fit is over hardcoded
datasheet arrays, so its coefficients are a constant and could be computed
once instead of at every construction. That would make the DAC model
version-independent and drop `scipy.optimize` from the runtime path.

## Known gaps

- `assemble_web.py --offline` exits deliberately. The thin build needs the
  network on first open (then the browser caches it). A genuinely offline build
  must inline the Pyodide runtime, stdlib and numpy/scipy wheels — tens of MB —
  and shim `fetch` so the loader reads them from the page. Its own change.
- The chain diagram is not drawn yet. `diagram_generator.py` is matplotlib and
  is deliberately excluded from the wheel; the diagram is presentation, so the
  browser should draw its own SVG from `describe()`.
- The DAC phase-noise fit returns a non-finite value just outside its datasheet
  range ([`hardware_models.py:137`](../hardware_models.py#L137)), pre-existing
  and unrelated to this build. `chain_api` maps non-finite to `null` and uPlot
  renders it as a gap.
- A chain file that loads with warnings loads silently here. `SignalChain.load`
  records them on `chain.load_warnings` and the Qt GUI shows them in a dialog;
  the browser drops them, so a file that had a parameter defaulted in looks
  identical to one that did not.
