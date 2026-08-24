# GUI Structure Documentation

## Overview

The Analog Chain Builder GUI has been refactored into a modular structure for better maintainability and organization. The previously monolithic `chain_builder_gui.py` file has been broken up into separate component files.

## File Structure

```
analog_chain_interface/
├── chain_builder_gui.py              # Main entry point (~30 lines)
└── gui_components/                   # GUI components package
    ├── __init__.py                   # Package initialization with exports
    ├── component_library.py          # ComponentLibrary widget
    ├── chain_view.py                 # ChainView widget
    ├── parameter_panel.py            # ParameterPanel widget
    ├── diagram_panel.py              # DiagramPanel widget 🆕
    ├── results_panel.py              # ResultsPanel widget 🆕
    ├── digitizer_panel.py            # DigitizerPanel widget 🆕
    └── main_window.py                # MainWindow class
```

## Component Descriptions

### Main Entry Point

**`chain_builder_gui.py`**
- Simple entry point that initializes the Qt application and launches the main window
- Just ~30 lines of code (previously ~1000+ lines)
- Minimal boilerplate: create QApplication, instantiate MainWindow, exec event loop

### Panel Components

All panels are integrated into the main window layout and communicate via Qt signals.

**`gui_components/component_library.py`**
- `ComponentLibrary` class: Tree widget displaying available hardware components organized by category
- Automatically discovers components from `hardware_models.py`
- Categorizes by naming patterns (amplifiers, cables, attenuators, filters, converters)
- Emits `component_selected` signal when user clicks a component

**`gui_components/parameter_panel.py`**
- `ParameterPanel` class: Dynamic parameter input panel
- Uses Python introspection to discover component __init__ parameters
- Creates appropriate input widgets based on parameter names
- Smart widget factory (temperature → spinbox, length → double spinbox, etc.)
- Emits `add_component` signal with instantiated component

**`gui_components/chain_view.py`**
- `ChainView` class: Displays and manages the current signal chain
- List widget showing components in order with reordering controls
- Maintains the internal `SignalChain` object synchronized with UI
- Up/Down buttons for reordering, Remove and Clear buttons
- Emits `chain_changed` signal when chain is modified

**`gui_components/diagram_panel.py`** 🆕
- `DiagramPanel` class: Diagram generation control panel
- Configure diagram parameters (reference frequency, show gain/noise)
- Select output format (PDF, PNG, SVG)
- Generate button triggers `DiagramGenerator`
- File dialog integration for save location

**`gui_components/results_panel.py`** 🆕
- `ResultsPanel` class: Real-time analysis and plotting panel
- Embedded matplotlib canvas with navigation toolbar
- Frequency sweep configuration (start, stop, points, spacing)
- Multiple plot modes (gain vs frequency, noise spectrum)
- Component contribution breakdown option
- Export results to CSV, save plots to PNG/PDF/SVG
- Automatically updates when chain changes

**`gui_components/digitizer_panel.py`** 🆕
- `DigitizerPanel` class: Digitizer/DAC configuration panel
- Specialized controls for digitizer components (AD9082, etc.)
- Configure carrier frequency, sample rate, resolution
- Phase noise profile visualization
- Integration with digitizer models in `hardware_models.py`

**`gui_components/main_window.py`**
- `MainWindow` class: Main application window and orchestrator
- Multi-panel layout using QSplitter for resizable regions
- Menu bar (File, Tools, View, Help) and toolbar
- Coordinates signal connections between all panels
- Handles file operations (New/Save/Load chains as JSON)
- Status bar for quick feedback
- Manages panel visibility and layout

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

# Import individual panels
from gui_components import (
    ComponentLibrary,
    ChainView,
    ParameterPanel,
    DiagramPanel,
    ResultsPanel,
    DigitizerPanel
)

# For standalone use of individual panels
from gui_components.component_library import ComponentLibrary
from gui_components.results_panel import ResultsPanel
# etc.
```

## Benefits of Panel-Based Structure

1. **Maintainability**: Each panel is in its own file with focused responsibility
2. **Reusability**: Panels can be imported and used independently in other projects
3. **Testability**: Isolated panels are easier to unit test
4. **Readability**: Smaller, focused files (~200-400 lines each) are easier to understand
5. **Scalability**: New panels can be added without modifying existing code
6. **Collaboration**: Multiple developers can work on different panels without conflicts
7. **User Experience**: All functionality visible at once, no dialog switching
8. **Workflow**: Real-time feedback as chains are built and modified

## Architecture Evolution

### Phase 1: Monolithic (Jan 19, 2026)
- Single `chain_builder_gui.py` file with ~1200 lines
- All GUI logic in one place

### Phase 2: Dialog-Based (Jan 20, 2026)
- Split into main window + separate analysis dialogs
- Analysis performed in popup dialogs
- Improved modularity but workflow disruption

### Phase 3: Panel-Based (Jan 23, 2026) - **Current**
- All functionality in integrated panels
- No popup dialogs for core features
- Unified interface with real-time updates
- Superior user experience and workflow

## Migration Notes

- The API remains clean - external code imports `MainWindow` from `gui_components`
- All core functionality has been preserved and enhanced
- Original monolithic file replaced with ~30 line launcher + 7 panel modules
- No changes to underlying signal chain engine or hardware models
- Panel-based design is the current standard for the project
