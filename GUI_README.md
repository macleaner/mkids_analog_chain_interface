# Analog Chain Builder GUI

A graphical user interface for building and analyzing RF signal chains interactively.

## Overview

The Chain Builder GUI provides an intuitive interface for constructing analog signal chains by selecting hardware components from a library and specifying their parameters. The tool integrates seamlessly with the existing `SignalChain` framework and diagram generation capabilities.

## Features

- **Component Library Browser**: Browse available hardware components organized by type
  - Amplifiers (LNAs, ZX60, ASU, etc.)
  - Cables (SMA, cryo cables, RG cables, etc.)
  - Attenuators
  - Filters (high-pass, band-pass)
  - Converters (AD9082, DAC/ADC)

- **Dynamic Parameter Input**: Automatically generated input fields based on component requirements
  - Smart defaults for common parameters (temperature, length, attenuation)
  - Type-appropriate widgets (spin boxes for numeric values, text fields for strings)
  - Unit display (K for temperature, m for length, dB for attenuation)

- **Chain Management**: 
  - Add/remove components
  - Reorder components with up/down buttons
  - Clear entire chain
  - Visual list showing current chain order

- **Save/Load Chains**: Persist chains as JSON files for reuse

- **Diagram Generation**: Generate visual diagrams directly from the GUI

- **Chain Summary**: View detailed information about the current chain

## Installation

### Requirements

```bash
pip install PySide6
```

All other dependencies (numpy, scipy, matplotlib) should already be installed for the base analog chain interface.

## Running the GUI

From the command line in the project directory:

```bash
python chain_builder_gui.py
```

Or make it executable:

```bash
chmod +x chain_builder_gui.py
./chain_builder_gui.py
```

## Usage Guide

### Building a Chain

1. **Select a Component**: Click on a component in the Component Library (left panel)
   - Components are organized into categories (Amplifiers, Cables, etc.)
   - Click on any component to select it

2. **Set Parameters**: The Parameter Panel (right panel) will show relevant parameter inputs
   - For cables: specify length in meters
   - For attenuators: specify attenuation (dB) and temperature (K)
   - For cryo cables: specify length and temperature
   - Some components have no parameters

3. **Add to Chain**: Click "Add to Chain" button
   - Component appears in the Current Chain list (middle panel)
   - Components are shown with their parameters

4. **Reorder Components**: Use the Up/Down buttons or drag components

5. **Remove Components**: Select a component and click "Remove" or "Clear All"

### Saving and Loading Chains

**Save a Chain:**
- File → Save Chain (or Ctrl+S)
- Choose a location and filename
- Chain is saved as JSON with component types and parameters

**Load a Chain:**
- File → Load Chain (or Ctrl+O)
- Select a previously saved JSON file
- Chain is reconstructed with all components and parameters

### Generating Diagrams

1. Build your chain
2. Tools → Generate Diagram
3. Choose output filename and location
4. PDF diagram is generated using the existing `diagram_generator` module

### Viewing Chain Summary

- Tools → Show Chain Summary
- Displays component list and chain information

## Keyboard Shortcuts

- `Ctrl+N`: New chain (clear current)
- `Ctrl+S`: Save chain
- `Ctrl+O`: Load chain
- `Ctrl+Q`: Exit application

## Architecture

The GUI consists of four main components:

### ComponentLibrary (QTreeWidget)
- Scans `hardware_models.py` for available component classes
- Automatically categorizes components by naming conventions
- Emits signals when components are selected

### ParameterPanel (QWidget)
- Uses Python introspection to determine component parameters
- Dynamically creates appropriate input widgets
- Handles parameter validation and type conversion

### ChainView (QWidget)
- Manages the current `SignalChain` object
- Provides reordering and removal capabilities
- Maintains synchronization between UI and chain object

### MainWindow (QMainWindow)
- Orchestrates all components
- Handles file operations (save/load)
- Integrates with diagram generation

## Extending the GUI

### Adding New Component Types

Components are automatically discovered from `hardware_models.py`. To add a new component:

1. Define the component class in `hardware_models.py`
2. The GUI will automatically categorize it based on naming:
   - Contains "LNA" or "Amp" → Amplifiers
   - Contains "cable", "SMA", "BCB", or "RG" → Cables
   - Contains "Attenuator" → Attenuators
   - Contains "Filter" → Filters
   - Contains "AD9082", "DAC", or "ADC" → Converters
   - Otherwise → Other

3. Parameter widgets are automatically created based on parameter names:
   - "temperature" → Spin box with range 0-400 K
   - "length" → Spin box with range 0-100 m
   - "attenuation" → Spin box with range -100 to 0 dB
   - Other → Text field

### Customizing Parameter Widgets

Edit the `ParameterPanel._create_widget_for_parameter()` method to add custom widget types for specific parameter names.

## Example Workflow

```python
# Conceptual example of what the GUI does programmatically:

from signal_chain import SignalChain
import hardware_models

# Create chain
chain = SignalChain("My Custom Chain")

# Add components (as done through GUI)
chain.add_component(hardware_models.Attenuator(attenuation=-3.0, temperature=300))
chain.add_component(hardware_models.SMA_cables(length_m=1.5))
chain.add_component(hardware_models.CryoElec_LNA())

# Generate diagram (via Tools menu)
from diagram_generator import generate_diagram
generate_diagram(chain, "my_chain_diagram.pdf")

# Calculate properties
gain = chain.total_gain(frequency=1e9)  # 1 GHz
noise = chain.output_noise(carrier_frequency=1e9, spectral_frequency=1e3)
```

## Troubleshooting

**GUI doesn't start:**
- Ensure PySide6 is installed: `pip install PySide6`
- Check Python version (requires Python 3.9+)

**Component not appearing in library:**
- Check that the class is defined in `hardware_models.py`
- Verify the class is importable

**Parameter fields not showing:**
- Component's `__init__` method should have properly named parameters
- Parameters should have type hints or defaults when possible

**Diagram generation fails:**
- Ensure matplotlib is installed
- Check that `diagram_generator.py` is in the same directory

## Future Enhancements

Potential improvements:
- Gain/noise calculation and display within GUI
- Plot generation (frequency response, noise vs. frequency)
- Import from existing analog chain definitions
- Export to Python code
- Component search/filter functionality
- Undo/redo support
- Drag-and-drop from library to chain

## License

Same license as the main analog_chain_interface project.
