# Analysis Features in Analog Chain Builder GUI

## Overview
Two new analysis dialogs have been added to the GUI to provide comprehensive signal chain analysis capabilities.

## Features

### 1. Gain vs Frequency Analysis
**Access:** Tools → Analyze Gain vs Frequency...

**Parameters:**
- **Start Frequency** (GHz): Beginning of frequency sweep
- **Stop Frequency** (GHz): End of frequency sweep
- **Number of Points**: Resolution of the frequency sweep (10-10,000)
- **Frequency Spacing**: Logarithmic or Linear

**Capabilities:**
- Interactive plot with zoom/pan controls
- Shows min/max gain values and frequencies
- Export data to CSV format
- Save plots as PNG, PDF, or SVG

### 2. Noise Spectrum Analysis
**Access:** Tools → Analyze Noise Spectrum...

**Parameters:**
- **Carrier Frequency** (GHz): The RF carrier frequency for the analysis
- **Start Offset Freq** (kHz): Beginning of spectral offset frequency range
- **Stop Offset Freq** (kHz): End of spectral offset frequency range
- **Number of Points**: Resolution of the frequency sweep (10-10,000)
- **Frequency Spacing**: Logarithmic or Linear
- **Show Individual Component Contributions**: Optional checkbox to display breakdown by component

**Capabilities:**
- Interactive plot with zoom/pan controls
- Shows min/max/average noise PSD values
- Optional component-by-component noise contribution overlay
- Export data to CSV format (including individual contributions if enabled)
- Save plots as PNG, PDF, or SVG

## Usage Workflow

1. **Build your signal chain** using the component library and parameter panel
2. **Select analysis type** from the Tools menu
3. **Adjust parameters** in the analysis dialog
4. **Click "Calculate & Plot"** to generate the analysis
5. **Use toolbar** to zoom, pan, or inspect the plot
6. **Export data or save plot** as needed

## Technical Details

- Both dialogs use embedded matplotlib figures with Qt5Agg backend
- Calculations leverage the existing `SignalChain` class methods:
  - `total_gain(frequency)` for gain analysis
  - `output_noise(carrier_frequency, spectral_frequency)` for noise analysis
  - `noise_at_point(..., contributions=True)` for component breakdown
- All frequency values are properly converted between display units (GHz, kHz) and internal units (Hz)

## Example Use Cases

**Gain Analysis:**
- Characterize frequency response of amplifier chains
- Verify passband flatness
- Identify resonances or rolloff frequencies

**Noise Analysis:**
- Calculate output noise power spectral density
- Identify dominant noise sources
- Analyze 1/f noise behavior at low offset frequencies
- Optimize component ordering for minimum noise

## Future Enhancements

The modular design allows for easy addition of:
- Phase analysis
- Group delay calculations
- Intermodulation distortion analysis
- Power handling analysis
- Multi-frequency noise analysis (noise vs carrier frequency)
