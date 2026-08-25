# RF Analog Signal Chain Analysis Tool

A Python tool for modeling and analyzing RF analog signal chains, with support for calculating signal gain, noise propagation, and generating system diagrams.

## Features

- **Component-Based Modeling**: Build signal chains from individual RF components (amplifiers, cables, attenuators, filters, etc.)
- **Gain Analysis**: Calculate signal gain/loss between any two points in the chain
- **Noise Analysis**: Compute noise power contributions from each component, referred to any point in the system
- **Visualization**: Generate block diagrams with gain and noise information
- **Frequency-Dependent Analysis**: All calculations support frequency-dependent component characteristics

## Architecture

### Core Modules

- **`component.py`**: Base classes for all RF components
- **`hardware_models.py`**: Library of real RF components with datasheet-based models
  - Amplifiers (LNAs, warm amplifiers)
  - Cables (cryogenic, room temperature, various types)
  - Attenuators (temperature-aware)
  - Filters (high-pass)
  - DAC/ADC models
- **`signal_chain.py`**: Main signal chain orchestrator
- **`utils.py`**: Utility functions (power conversions, thermal noise calculations)
- **`diagram_generator.py`**: Visual diagram generation using matplotlib

### Hardware Components Available

#### Amplifiers
- `ASU_3GHz_LNA`: Cryogenic LNA (~6K noise temp)
- `CryoElec_LNA`: Cryogenic LNA (~4K noise temp)
- `ZX60_3018Gplus`: Room temperature amplifier (~20 dB gain)

#### Cables (Cryogenic)
- `SMA_CuNi086_cryo`: 0.86mm CuNi coax
- `SMA_SS086_cryo`: 0.86mm stainless steel coax
- `SMA_SS219_cryo`: 2.19mm stainless steel coax
- `SMA_NbTi086_cryo`: 0.86mm NbTi superconducting coax
- `BCB029_SS034_cryo`: 0.034" stainless steel (CryoCoax)
- `BCB014_SS085_cryo`: 0.085" stainless steel (CryoCoax)
- `BCB024_SP034_cryo`: 0.034" CuNi coax (CryoCoax)
- `BCB012_NbTi034_cryo`: 0.034" NbTi coax (CryoCoax)

#### Cables (Room Temperature)
- `SMA_FM_F141_cables`: Fairview Microwave F141 coax
- `SMA_RG58C_cables`: RG58 coax
- `SMA_RG174A_cables`: RG174 coax
- `SMA_cables`: Generic SMA coax

#### Other Components
- `Attenuator`: Temperature-aware attenuator (contributes thermal noise)
- `FilterHP_VHF1320p`, `FilterHP_VHF1760p`, `FilterHP_VHF1910p`: High-pass filters
- `AD9082`: DAC/ADC with phase noise characteristics

## Installation

### Requirements
```bash
pip install numpy scipy matplotlib
```

### Setup
No installation required - the tool is self-contained in the `/home/maclean/code/analog_chain_interface/` directory.

## Usage

### Basic Example

```python
from signal_chain import SignalChain
from hardware_models import Attenuator, ASU_3GHz_LNA, SMA_SS086_cryo
from diagram_generator import DiagramGenerator
import numpy as np

# Create a signal chain
chain = SignalChain(name="My RF System")

# Add components
chain.add_component(Attenuator(-10, 300), label="InputAtten")
chain.add_component(SMA_SS086_cryo(0.5, temperature=4), label="CryoCable")
chain.add_component(ASU_3GHz_LNA(), label="LNA")

# Analyze at 1.5 GHz
freq = 1.5e9

# Calculate gain
total_gain = chain.total_gain(freq)
print(f"Total gain: {total_gain:.2f} dB")

# Calculate noise at output
noise = chain.output_noise(freq)
print(f"Output noise: {noise:.2e} W/Hz")

# Calculate gain between specific points
gain_to_lna = chain.gain_between("InputAtten", "LNA", freq)
print(f"Gain to LNA: {gain_to_lna:.2f} dB")

# Generate diagram
diagram_gen = DiagramGenerator(chain)
diagram_gen.generate("my_system.pdf", frequency=freq, show_gain=True)
```

### Running Examples

```bash
cd /home/maclean/code/analog_chain_interface/examples
python simple_example.py
```

This will:
1. Build a sample signal chain
2. Perform gain and noise analysis
3. Generate PDF diagrams showing the system

## Saving and Loading Chains

A chain is a durable artifact: save it next to the measurement data it
describes, and reload it months later to get the same numbers.

```python
from signal_chain import SignalChain

chain.description = "Cooldown CD-17, feedline A"
chain.metadata = {"cooldown": "CD-17", "dataset": "/data/cd17/noise.h5"}
chain.save("cd17_feedline_a.json")

# Later, in a notebook next to the measured spectrum:
chain = SignalChain.load("cd17_feedline_a.json")
predicted = chain.output_noise(carrier_hz, offset_hz_array)
if chain.load_warnings:
    print("\n".join(chain.load_warnings))   # always check this
```

### File format

```json
{
  "format_version": 2,
  "name": "cd17_feedline_a",
  "description": "Cooldown CD-17, feedline A",
  "metadata": {"cooldown": "CD-17"},
  "saved_utc": "2026-08-24T14:02:11+00:00",
  "digitizer": {
    "dac": {"type": "converter.ad9082_dac", "name": "AD9082_DAC",
            "params": {"carrier_power_dbm": -20.0, "gain_db": 0.0}},
    "adc": {"type": "converter.ad9082_adc", "name": "AD9082_ADC",
            "params": {"gain_db": 0.0}}
  },
  "components": [
    {"type": "attenuator", "name": "Attenuator", "label": "InputAtten",
     "params": {"attenuation": -10.0, "temperature": 300.0}}
  ]
}
```

Properties that matter for bookkeeping:

- **`type` is a stable registry id**, not a Python class name, so classes can be
  renamed or moved without invalidating files. Former class names remain valid
  as aliases, and files written by earlier versions still load.
- **`params` is what the component was actually built with**, recorded by the
  component itself rather than inferred from its constructor signature. A
  parameter can no longer be silently dropped and replaced by a default.
- **`label` is a stable handle** for a point in the chain, so an analysis result
  can refer to "noise at the LNA" and still resolve after a reorder.
- **Anything the file failed to fully specify appears in `chain.load_warnings`**
  rather than being applied silently. The GUI shows these in a dialog.
- `format_version` allows migration; `saved_utc` and `metadata` carry provenance.

## Adding a Component

Components declare their own parameters and register themselves:

```python
from component import PassiveComponent, flat_in_spectral
from registry import ParamSpec, register
from utils import kb

@register("cable.my_coax", category="Cables", label="My Coax",
          params=(ParamSpec("length_m", default=1.0, label="Length", unit="m",
                            minimum=0.0, maximum=100.0, step=0.1),))
class MyCoax(PassiveComponent):
    def __init__(self, length_m, name=None):
        super().__init__(name=name, params={"length_m": length_m})
        self.length = length_m

    def gain(self, carrier_frequency):
        return -0.5 * self.length

    # Optional. Omit it and the component is treated as noiseless.
    def noise(self, carrier_frequency, spectral_frequency):
        return flat_in_spectral(kb * 300, spectral_frequency)
```

That is all that is needed - the component then appears in the GUI library with
correct units and ranges, serializes, and is picked up automatically by the
round-trip and characterization tests.

## Tests

```bash
python -m pytest tests/ -q
```

`tests/test_characterization.py` pins the numerical output of every component
against `tests/data/golden_components.json`, so a refactor cannot silently
change results. If you change a model deliberately, regenerate it with
`python tests/test_characterization.py --regenerate` and review the diff.

## Key Concepts

### The two frequencies

Every analysis method takes two frequencies, and they mean different things:

| Name | What it is | Typical scale | Used for |
|---|---|---|---|
| **carrier frequency** | The real-world frequency of the tone probing the system | MHz - GHz | All gain evaluation; noise quantities that vary across the RF band |
| **spectral frequency** (audio frequency) | The offset *from the carrier* at which a noise quantity is evaluated | Hz - MHz | Noise that has structure near the carrier, e.g. DAC phase noise |

`gain(carrier_frequency)` is always a function of the carrier frequency alone.

**Every component takes both frequencies for noise**, so noise is computed the
same way for all of them:

```python
component.noise(carrier_frequency, spectral_frequency)   # -> W/Hz
```

The carrier sets the **level**; the spectral frequency sets the **shape**:

| Source | Level from | Shape in spectral |
|---|---|---|
| Amplifiers | carrier frequency (noise temperature vs RF) | white |
| DAC | carrier power (+ any carrier-frequency dependence) | 1/f skirt |
| Attenuator | temperature, `k_B·T` | white |
| ADC | carrier frequency (datasheet SNR vs input frequency) | white |

A source that is white near the carrier computes its level from the carrier and
returns it flat across the spectral axis - `component.flat_in_spectral(level,
spectral_frequency)` does that. A source with spectral structure returns that
shape, shifted by whatever level the carrier implies. `AD9082_DAC` shows the
pattern: its `carrier_level_db()` hook is the documented place for a measured
carrier dependence, currently 0 dB because the fitted model has none.

`AD9082_ADC` derives its floor from the datasheet SNR versus input frequency,
converting SNR (dB below full scale) to a PSD using the full-scale level and
Nyquist bandwidth the SNR was quoted under. Those two live as class attributes
rather than parameters, because an SNR spec only converts to a PSD given the
conditions it was measured under.

> **Datasheet discrepancy worth checking:** the AD9082 also quotes a flat
> -140 dBm/Hz noise spectral density, which this model used previously. The
> SNR-derived figure is 3.4x (at 3 GHz) to 9.5x (at 100 MHz) *lower*. The two
> specs are not reconcilable by unit conversion, so if your ADC noise matters,
> confirm which applies to your configuration.

Because every source shares the signature, sweeping either axis returns a result
shaped like that axis, and the chain never has to know which kind of source it
is holding.

### Noise Propagation

The tool uses **direct noise power propagation** (not noise figure):

1. Each component has an intrinsic noise power spectral density (W/Hz)
2. Noise from each component is propagated downstream through gain/loss
3. All noise contributions are summed at the reference point

For thermal components (attenuators): `N = k_B × T` (W/Hz)

#### Input- vs output-referred noise

Whether a component's *own* gain is applied to its noise depends on where that
noise is referred to. Each component declares this via `noise_reference`:

| `noise_reference` | Meaning | Applies to |
|---|---|---|
| `"input"` (default) | Noise is quoted at the input, so the component's own gain acts on it | Amplifiers - a noise temperature is an input-referred quantity |
| `"output"` | Noise is generated at the output, so the component does not act on it | Attenuators, cables, filters, DAC/ADC |

The attenuator is the clearest case: its Johnson noise is `k_B × T` **at its
output**, whatever the attenuation. A 30 dB attenuator at 300 K does not
attenuate its own thermal noise, so a lone attenuator contributes exactly
`k_B × T` at the chain output.

#### Referring noise to a plane

"Noise at a point" means **every noise source in the system referred to that
plane**, not just what physically arrives there. Sources upstream are referred
forward, sources downstream referred backward, both via

```
contribution_dBm = intrinsic_dBm + C(reference_plane) − C(source_plane)
```

where `C` is the cumulative gain from the chain input to a plane. The DAC and
ADC take part like any other stage.

A reference plane is a component **plus which side of it** - `at` is required,
because input and output differ by that component's gain, which for an
amplifier is tens of dB:

```python
budget = chain.noise_budget("LNA", carrier_hz, offset_hz, at="input")
print(budget.table())
print(budget.total_w, budget.total_k)      # W/Hz and equivalent K
for c in budget.contributions:             # ranked, largest first
    print(c.label, c.intrinsic_k, c.referral_gain_db, c.temperature_k)

chain.output_budget(carrier_hz, offset_hz) # referred to the chain output
chain.noise_at_point("LNA", carrier_hz, offset_hz, at="input")  # total only
```

Which produces, for a chain with too little gain ahead of the digitizer:

```
Noise referred to LNA (input)   carrier 1.5 GHz, offset 1000 Hz
source             own noise      own T  referral    referred        T_eq   share
                      [W/Hz]        [K]      [dB]      [W/Hz]         [K]     [%]
---------------------------------------------------------------------------------
AD9082_ADC         1.000e-17  724637.68     -9.09   1.233e-18    89355.42   99.34
Attenuator_0       4.140e-21     300.00     +0.00   4.140e-21      300.00    0.33
AD9082_DAC         3.159e-19   22891.85    -20.00   3.159e-21      228.92    0.25
```

The `referral` column is the diagnostic: with only 9 dB of net gain before the
ADC, ADC noise referred back to the LNA input is ~89,000 K and swamps
everything. The same budget at the chain output shows the ADC as merely one term
among several - which is why the reference plane has to be explicit.

The referred total is **not** a power you could measure at that plane; it is the
equivalent noise there, which is what an SNR or system noise temperature at that
plane is built from.

The GUI exposes this as the **Noise Budget** tab, with CSV export that carries
the reference plane, frequencies and referral gains in the header.

> **Known issue:** every source's `noise()` is evaluated at the *offset*
> frequency. That is right for DAC phase noise but wrong for an amplifier, whose
> noise temperature is a function of RF frequency - the ASU LNA reports 30 K
> (its value near DC) instead of 6 K at a 1.5 GHz carrier. Amplifier
> contributions are therefore overstated. Fixing it needs a per-component
> declaration of which frequency its noise depends on.

### Gain Calculation

Gains are calculated in dB and summed along the chain:
```
Total_Gain = G1 + G2 + G3 + ... (in dB)
```

Negative values indicate loss (e.g., cables, attenuators).

### Temperature-Aware Components

Cryogenic cables and attenuators adjust their characteristics based on temperature:
- Cables: Different attenuation at 4K vs 300K
- Attenuators: Thermal noise scales with physical temperature

## API Reference

### SignalChain Class

**Methods:**
- `add_component(component, label=None)`: Add component to chain
- `gain_between(start, end, frequency)`: Calculate gain from start to end
- `noise_at_point(reference, frequency, contributions=False)`: Calculate noise at a point
- `total_gain(frequency)`: Total chain gain
- `output_noise(frequency)`: Noise at output
- `summary()`: Print chain summary

### DiagramGenerator Class

**Methods:**
- `generate(filename, frequency, show_gain=True, show_noise=False)`: Generate simple block diagram
- `generate_detailed(filename, frequency_range)`: Generate detailed diagram with frequency plots

## Project Structure

```
analog_chain_interface/
├── README.md                   # This file
├── component.py                # Base component classes
├── signal_chain.py            # Main signal chain engine
├── hardware_models.py         # RF component library
├── utils.py                   # Utility functions
├── diagram_generator.py       # Visualization
├── examples/
│   └── simple_example.py      # Example script
├── analog_chains/             # Legacy implementations
│   ├── default.py
│   ├── mcgill_full.py
│   ├── slim_deployment_2024.py
│   └── ...
└── transferfunctions/         # Measured transfer functions
    └── *.pkl
```

## Future Enhancements

- [ ] GUI interface for interactive chain building
- [ ] Import/export chain configurations (JSON/YAML)
- [ ] More component models (mixers, switches, circulators)
- [ ] S-parameter import support
- [ ] Batch analysis and optimization tools
- [ ] Web-based interface

## Contributing

When adding new hardware components:

1. Inherit from `Component`, `ActiveComponent`, or `PassiveComponent`
2. Implement `gain(frequency)` method returning dB
3. Implement `noise(frequency)` method returning W/Hz (if applicable)
4. Use interpolation of datasheet values for frequency-dependent characteristics

## License

Internal research tool - no external license currently.

## Contact

For questions or issues, contact the project maintainer.
