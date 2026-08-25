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
- Converters are shown in the chain but not editable — they are set via
  `set_digitizer`, not appended, so they have no component index.
