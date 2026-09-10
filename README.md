# RF Analog Chain Calculator

Build an RF signal chain, inspect its gain across a frequency band, and identify which components dominate its noise budget. The project combines a browser editor with a Python analysis core for room-temperature and cryogenic systems, including chains between a DAC and an ADC.

The browser runs the same Python models as scripts and notebooks through Pyodide. Chains are saved as JSON so a design can move between the interactive editor, a Jupyter notebook, and measurement analysis.

![RF Analog Chain Calculator showing the component library, an RF chain, an LNA-referred noise budget, and gain and noise plots](docs/images/analog-chain-calculator.png)

*Example browser session with Nyquist filters, cryogenic attenuation, amplifiers, and converters. The lower panels show gain versus carrier frequency and noise versus spectral offset.*

## What it does

- **Edit chains visually:** inspect component specifications, add and reorder stages, change parameters, and assign labels to reference points.
- **Analyze gain:** sweep carrier frequency between selected input/output planes, with optional per-stage curves.
- **Build noise budgets:** refer every source to a selected plane, rank contributions, and display density in dBm/Hz or W/Hz, or equivalent noise temperature in K.
- **Inspect noise spectra:** sweep offset from the carrier and optionally show each source separately.
- **Save the design and its context:** JSON files carry component parameters, labels, notes, metadata, and an optional saved operating point.
- **Continue in Jupyter:** export a notebook containing the current chain, plots, budget and CSV export, plus a parameter comparison when an editable component is available.
- **Generate diagrams from Python:** use the matplotlib diagram generator for annotated chain drawings.

## Quick start

From a checkout, use Python 3.9 or newer with `pip` available:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python open_web_gui.py
```

On Windows, activate the environment with `.venv\Scripts\activate` instead.

The launcher builds the core wheel and assembles `dist/analog_chain_calculator.html` when needed, then opens it in your browser. The page needs no application server. It downloads Pyodide and its Python dependencies from a CDN; **network access is required on first load**. Subsequent loads may use the browser cache. A fully offline bundle is not implemented.

Other launcher options:

```bash
python open_web_gui.py --no-open   # Build and print the HTML path
python open_web_gui.py --force     # Rebuild the wheel and page
python open_web_gui.py --desktop   # Install a Linux applications-menu entry
```

See [the browser guide](web/README.md) for manual build commands and UI details.

## Using the browser

1. Start with the initial preset, choose **new chain**, or use **open chain…** to load a JSON file from [examples](examples/).
2. Click a library component to inspect its model; double-click to add it. Edit stage parameters and labels, and reorder stages to match the signal path. DAC and ADC models occupy the endpoints.
3. Set the noise budget's reference plane, carrier frequency, and spectral offset. Select units and inspect each source's share of the total.
4. Adjust the gain plot's planes and frequency span, and the noise plot's reference plane and offset span. Enable component/source breakdowns as needed.
5. Click the chain name to edit its name and notes. **save the current view** records the operating point for reopening the chain; changing plot controls alone does not save it.
6. Use **download chain.json** to save the chain or **notebook.ipynb** to continue the analysis in Jupyter. The **Chain file** tab previews the serialized record.

The generated notebook embeds the chain that was on screen. Running it requires a local checkout or installation of the core, plus matplotlib for plotting.

## Python and notebooks

Install the core from this checkout; its declared dependencies are NumPy and SciPy:

```bash
python -m pip install -e .
python -m pip install matplotlib jupyterlab
```

The distribution is named `analog-chain-core`; its imports are top-level modules such as `signal_chain` and `hardware_models`. Matplotlib and Jupyter are optional for the core, but needed for the plotting and notebook workflows below.

### Build and analyze a chain

Run this example from the repository root:

```python
from hardware_models import ASU_3GHz_LNA, Attenuator, SMA_SS086_cryo
from signal_chain import SignalChain

chain = SignalChain(
    name="Cryogenic readout",
    description="Example feedline with a cold cable and LNA",
    metadata={"cooldown": "CD-17"},
)
chain.add_component(Attenuator(-10.0, 300.0), label="InputAtten")
chain.add_component(SMA_SS086_cryo(0.5, temperature=4.0), label="CryoCable")
chain.add_component(ASU_3GHz_LNA(), label="LNA")

carrier_hz = 1.5e9
spectral_hz = 1.0e3
print(f"Total gain: {chain.total_gain(carrier_hz):.2f} dB")
print(f"Output noise: {chain.output_noise(carrier_hz, spectral_hz):.3e} W/Hz")

budget = chain.noise_budget("LNA", carrier_hz, spectral_hz, at="input")
print(budget.table())

chain.save("cryogenic_readout.json")
restored = SignalChain.load("cryogenic_readout.json")
for warning in restored.load_warnings:
    print(f"Load warning: {warning}")
```

For converter noise, attach models with `chain.set_digitizer(dac, adc)`. The library includes AD9082 models and configurable `GenericDAC` / `GenericADC` models; the generic models also support `noiseless=True` for evaluating the analog components alone.

To generate a diagram from a checkout:

```python
from diagram_generator import DiagramGenerator

DiagramGenerator(chain).generate(
    "cryogenic_readout.pdf", frequency=carrier_hz, show_gain=True
)
```

`diagram_generator.py` is a repository utility and is excluded from the core wheel.

### Start from an existing chain

- [Notebook walkthrough](examples/analog_chain_walkthrough.ipynb): loading JSON, gain/noise sweeps, reference-plane budgets, and editing components.
- [Simple cryogenic chain](examples/simple_cryogenic_system.json): a saved chain for the walkthrough or browser.
- [PNNL 5 GHz example](examples/example_pnnl_5ghz.json): another saved RF chain.
- [Python example](examples/simple_example.py): analysis and PDF diagram generation.

```bash
jupyter lab examples/analog_chain_walkthrough.ipynb
python examples/simple_example.py
```

For a JSON-friendly scripting interface, `chain_api.py` exposes the same operations used by the browser:

```python
import chain_api

chain_api.load_preset("cryo_example")
result = chain_api.budget("LNA", at="input", carrier_hz=1.5e9, spectral_hz=1e3)
if not result["ok"]:
    raise RuntimeError(result["error"])
print(result)
```

This API operates on one active chain and returns JSON-safe dictionaries, including `{"ok": false, "error": ...}` on failure. Use separate `SignalChain` instances when working with multiple chains at once.

## Interpreting results

| Quantity | Meaning |
|---|---|
| Carrier frequency | RF frequency of the signal; determines component gain and RF-dependent noise levels. Python inputs use Hz. |
| Spectral frequency | Offset from the carrier where noise is evaluated; also in Hz. This captures structure such as a DAC's phase-noise skirt. |
| Gain | Power gain in dB; attenuation is negative. |
| Noise density | Power spectral density in W/Hz or dBm/Hz. Equivalent K is PSD divided by Boltzmann's constant, not necessarily a physical temperature. |
| Reference plane | Input or output of a named stage. The side is explicit because a stage's gain changes the referred value. |

A plane-referred budget includes **all sources**, including downstream sources referred backward through intervening gain. It describes the noise limiting the system at that reference plane; it is not simply the noise a meter would measure there.

The models describe a linear cascade. They do not solve impedance mismatch, reflections, compression, or a multiport network. The splitter represents loss through one arm; the circulator represents insertion loss only. Cables and filters currently contribute loss without added thermal noise; the attenuator explicitly supplies a `k_B T` noise term. These are model choices to account for when comparing a budget with hardware.

Datasheet-based gain models can extrapolate beyond their tabulated span with a ceiling on gain. The plots flag extrapolation for models that opt into it; cables intentionally do not show these flags. Amplifier noise curves are not extrapolated, so out-of-range analysis can produce unavailable values. Consult the component specifications and [model references](component_references/README.md) before relying on a result outside its supported band.

The AD9082 ADC uses an SNR-derived noise floor; `GenericADC` defaults to a stated −140 dBm/Hz density. They are different assumptions. Browser and local results also depend on their NumPy/SciPy versions, particularly the fitted AD9082 DAC model; the browser exposes build/runtime provenance.

## Chain files and reproducibility

The current JSON format is version 2. It stores stable registry type IDs, constructor parameters, labels, converter endpoints, name, description, free-form `metadata`, and a save timestamp. Earlier supported formats and class-name aliases can still load.

Always inspect `chain.load_warnings`: loading may substitute defaults or skip entries that cannot be reconstructed. A successful load alone does not guarantee every saved component was restored. JSON files describe models and parameters, not a frozen numerical environment; retain the code and dependency versions when exact reproducibility matters.

The reserved `metadata.analysis` key stores the preferred carrier, spectral offset, plot spans and reference planes. It affects the starting view and notebook export, not the physics. Use `chain_api.set_analysis(...)` to validate and save it, and `chain_api.analysis()` to inspect resolved or ignored fields. `set_metadata(...)` replaces the entire metadata mapping, including this key.

## Codebase map

| Path | Responsibility |
|---|---|
| `component.py` | Base component classes, gain/noise contract, and noise reference conventions. |
| `hardware_models.py` | Amplifiers, cables, attenuators, filters, converters, splitter, and circulator models. |
| `registry.py` | Stable model IDs, parameter schemas and validation, aliases, and retired parameters. |
| `signal_chain.py` | Ordered stages, reference planes, cascade calculations, and JSON persistence. |
| `noise_budget.py`, `utils.py` | Budget records, tables, unit conversions, and numerical helpers. |
| `chain_api.py` | Stateful JSON-facing API for editing, analysis, presets, and provenance. |
| `notebook_export.py` | Generates executable notebooks for the active chain and view. |
| `web/`, `tools/assemble_web.py`, `open_web_gui.py` | Browser UI, single-file assembly, and launcher. |
| `diagram_generator.py` | Matplotlib chain diagrams. |
| `component_references/` | Source datasheets and notes on model scope. |
| `tests/` | Physics, characterization, serialization, API, diagram, and notebook tests. |
| `analog_chain.py`, `analog_chains/`, `gui_components/`, `transferfunctions/` | Earlier application and deployment-specific code; outside the packaged core. Some legacy modules require `hidfmux`. |

## Development

To add a model, subclass the appropriate class in `component.py`, implement `gain(carrier_frequency)` and any nonzero `noise(carrier_frequency, spectral_frequency)`, and register it with `@register(...)` and `ParamSpec` definitions. Record constructor parameters through the base class so serialization can reconstruct them. The registry drives browser forms as well as validation; rebuild the browser wheel and page after changing a model.

Run the existing test suite from the checkout:

```bash
python -m pip install -e .
python -m pip install pytest matplotlib
python -m pytest tests/ -q
```

Characterization tests compare model output with [golden component data](tests/data/golden_components.json). After an intentional numerical change, regenerate the baseline and review its diff:

```bash
python tests/test_characterization.py --regenerate
```

## License

[MIT](LICENSE).
