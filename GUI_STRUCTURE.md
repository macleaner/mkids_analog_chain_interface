# GUI Structure Documentation

## Overview

The Analog Chain Builder GUI has been refactored into a modular structure for better maintainability and organization. The previously monolithic `chain_builder_gui.py` file has been broken up into separate component files.

## File Structure

```
analog_chain_interface/
├── chain_builder_gui.py              # Main entry point (simplified)
└── gui_components/                   # GUI components package
    ├── __init__.py                   # Package initialization
    ├── component_library.py          # ComponentLibrary widget
    ├── chain_view.py                 # ChainView widget
    ├── parameter_panel.py            # ParameterPanel widget
    ├── main_window.py                # MainWindow class
    └── dialogs/                      # Dialog components
        ├── __init__.py               # Dialogs package initialization
        ├── diagram_dialog.py         # DiagramDisplayDialog
        ├── summary_dialog.py         # SummaryDisplayDialog
        ├── gain_analysis_dialog.py   # GainAnalysisDialog
        └── noise_analysis_dialog.py  # NoiseAnalysisDialog
```

## Component Descriptions

### Main Entry Point

**`chain_builder_gui.py`**
- Simple entry point that initializes the Qt application and launches the main window
- Just ~30 lines of code (previously ~1000+ lines)

### Core GUI Components

**`gui_components/component_library.py`**
- `ComponentLibrary` class: Tree widget displaying available hardware components organized by category
- Emits signals when components are selected

**`gui_components/chain_view.py`**
- `ChainView` class: Displays and manages the current signal chain
- Provides controls for reordering, removing, and clearing components
- Maintains the internal `SignalChain` object

**`gui_components/parameter_panel.py`**
- `ParameterPanel` class: Dynamic parameter input panel
- Creates appropriate input widgets based on component parameters
- Emits signals when components are ready to be added

**`gui_components/main_window.py`**
- `MainWindow` class: Main application window
- Manages the overall UI layout with splitter
- Handles menu bar, toolbar, and action routing
- Coordinates communication between components
- Manages file operations (save/load chains)

### Dialog Components

**`gui_components/dialogs/diagram_dialog.py`**
- `DiagramDisplayDialog`: Interactive diagram generation
- Options for frequency, gain display, and noise display
- Save diagram to PDF/PNG/SVG

**`gui_components/dialogs/summary_dialog.py`**
- `SummaryDisplayDialog`: Text-based chain summary
- Lists all components with parameters
- Calculates total gain and noise at reference frequency
- Export summary to text file

**`gui_components/dialogs/gain_analysis_dialog.py`**
- `GainAnalysisDialog`: Frequency-dependent gain analysis
- Configurable frequency range and spacing (linear/log)
- Interactive plotting with matplotlib
- Export data to CSV

**`gui_components/dialogs/noise_analysis_dialog.py`**
- `NoiseAnalysisDialog`: Noise spectrum analysis
- Carrier frequency and offset frequency range configuration
- Optional display of individual component contributions
- Export capabilities

## Usage

### Running the GUI

```bash
python chain_builder_gui.py
```

Or from within Python:

```python
from gui_components import MainWindow
from PySide6.QtWidgets import QApplication
import sys

app = QApplication(sys.argv)
app.setStyle("Fusion")
window = MainWindow()
window.show()
sys.exit(app.exec())
```

### Importing Components

```python
# Import main window
from gui_components import MainWindow

# Import individual widgets
from gui_components import ComponentLibrary, ChainView, ParameterPanel

# Import dialogs
from gui_components.dialogs import (
    DiagramDisplayDialog,
    SummaryDisplayDialog,
    GainAnalysisDialog,
    NoiseAnalysisDialog
)
```

## Benefits of New Structure

1. **Maintainability**: Each component is in its own file, making it easier to locate and modify specific functionality
2. **Reusability**: Components can be imported and used independently in other projects
3. **Testability**: Isolated components are easier to unit test
4. **Readability**: Smaller, focused files are easier to understand
5. **Scalability**: New components can be added without cluttering existing files
6. **Collaboration**: Multiple developers can work on different components simultaneously without conflicts

## Migration Notes

- The API remains unchanged - existing code that imports `chain_builder_gui` will continue to work
- All functionality has been preserved
- The original large file has been replaced with a simple launcher script
- No changes to the underlying signal chain logic or hardware models
