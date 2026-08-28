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
seven core modules; and the page's script block passes `node --check` (skipped
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
[`examples/analog_chain_walkthrough.ipynb`](../examples/analog_chain_walkthrough.ipynb).

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
| remove an endpoint | its `×`, or its select back to *— none —* |
| name the chain, or annotate it | click the chain name in the top bar |
| see what any of that saves as | the **Chain file** tab, right-hand column |

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
  found by asking it. A filter declares that range outright, because it answers
  with a number everywhere — past the last tabulated point it extends the
  endpoint slope, clamped so it can neither show gain nor claim rejection deeper
  than anything measured. A model that instead returns NaN outside its tabulated
  range is making the same statement the other way, and gets bisected for its
  edge. Either way the span is the datasheet's: `VLF-6700+` is drawn over
  50 MHz – 19.89 GHz and `VHF-1320+` over 1 MHz – 3.7 GHz, without either being
  written down here or any interpolator's knots being read by name. A model that
  answers everywhere and declares no band — a flat attenuator, a cable built to
  extrapolate — has none of its own, so the gain plot's span is used instead and
  the axis says `plot span`, because "0.1–3 GHz" means something different in the
  two cases.
* **the unit for its noise.** A noise temperature only means anything for a
  source that is white near the carrier, so the model is evaluated across the
  spectral axis: an amplifier or a warm attenuator gets one temperature in K,
  the AD9082's phase-noise skirt gets a density at the offset the budget is set
  to, and a filter — lossy, but not a source — reads `none`.

The carrier and the spectral offset are the budget's, so a spec is read at the
operating point being worked at. The figures are for the registry defaults,
which is what a double-click installs; the `at defaults` row says which values
those were, for the models where it makes a difference.

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
