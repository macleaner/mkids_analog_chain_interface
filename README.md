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

## Key Concepts

### Noise Propagation

The tool uses **direct noise power propagation** (not noise figure):

1. Each component has an intrinsic noise power spectral density (W/Hz)
2. Noise from each component is propagated downstream through gain/loss
3. All noise contributions are summed at the reference point

For thermal components (attenuators): `N = k_B × T` (W/Hz)

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
