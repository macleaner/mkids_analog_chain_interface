"""
Main Window

Main application window for the Analog Chain Builder.
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QMessageBox, QFileDialog, QToolBar, QTabWidget
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction

import registry
from signal_chain import SignalChain

from .component_library import ComponentLibrary
from .chain_view import ChainView, describe_component
from .parameter_panel import ParameterPanel
from .diagram_panel import DiagramPanel
from .results_panel import ResultsPanel
from .digitizer_panel import DigitizerPanel


class MainWindow(QMainWindow):
    """
    Main application window for the chain builder.
    """
    
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("Analog Chain Builder")
        self.setGeometry(100, 100, 1200, 900)
        
        self._setup_ui()
        self._create_menu_bar()
        self._create_toolbar()
        
    def _setup_ui(self):
        """Set up the main UI layout."""
        
        # Central widget with vertical splitter
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        
        # Main vertical splitter (top: controls, bottom: results)
        main_splitter = QSplitter(Qt.Vertical)
        
        # Top section: horizontal 4-panel layout
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        
        top_splitter = QSplitter(Qt.Horizontal)
        
        # 1. Digitizer Panel (extreme left)
        self.digitizer_panel = DigitizerPanel()
        self.digitizer_panel.digitizer_applied.connect(self._on_digitizer_applied)
        top_splitter.addWidget(self.digitizer_panel)
        
        # 2. Component library
        self.library = ComponentLibrary()
        self.library.component_selected.connect(self._on_component_selected)
        top_splitter.addWidget(self.library)
        
        # 3. Parameter panel
        self.param_panel = ParameterPanel()
        self.param_panel.add_component.connect(self._on_add_component)
        top_splitter.addWidget(self.param_panel)
        
        # 4. Chain view
        self.chain_view = ChainView()
        top_splitter.addWidget(self.chain_view)
        
        # Set top splitter proportions (4 columns)
        top_splitter.setSizes([200, 300, 300, 400])
        
        top_layout.addWidget(top_splitter)
        main_splitter.addWidget(top_widget)
        
        # Bottom section: tabbed results area
        self.results_tabs = QTabWidget()
        
        # Diagram tab
        self.diagram_panel = DiagramPanel()
        self.results_tabs.addTab(self.diagram_panel, "Diagram")
        
        # Results tab (gain + noise)
        self.results_panel = ResultsPanel()
        self.results_tabs.addTab(self.results_panel, "Analysis Results")
        
        main_splitter.addWidget(self.results_tabs)
        
        # Set main splitter proportions (40% top, 60% bottom)
        main_splitter.setSizes([400, 600])
        
        main_layout.addWidget(main_splitter)
        
    def _create_menu_bar(self):
        """Create the menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        
        new_action = QAction("&New Chain", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self._new_chain)
        file_menu.addAction(new_action)
        
        file_menu.addSeparator()
        
        save_action = QAction("&Save Chain", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self._save_chain)
        file_menu.addAction(save_action)
        
        load_action = QAction("&Load Chain", self)
        load_action.setShortcut("Ctrl+O")
        load_action.triggered.connect(self._load_chain)
        file_menu.addAction(load_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Tools menu
        tools_menu = menubar.addMenu("&Tools")
        
        diagram_action = QAction("Generate &Diagram", self)
        diagram_action.triggered.connect(self._generate_diagram)
        tools_menu.addAction(diagram_action)
        
        tools_menu.addSeparator()
        
        analyze_action = QAction("&Analyze Chain (Gain + Noise)...", self)
        analyze_action.triggered.connect(self._analyze_chain)
        tools_menu.addAction(analyze_action)
        
        # Help menu
        help_menu = menubar.addMenu("&Help")
        
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
        
    def _create_toolbar(self):
        """Create the toolbar."""
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(toolbar)
        
        save_action = QAction("Save", self)
        save_action.triggered.connect(self._save_chain)
        toolbar.addAction(save_action)
        
        load_action = QAction("Load", self)
        load_action.triggered.connect(self._load_chain)
        toolbar.addAction(load_action)
        
        toolbar.addSeparator()
        
        diagram_action = QAction("Generate Diagram", self)
        diagram_action.triggered.connect(self._generate_diagram)
        toolbar.addAction(diagram_action)
        
        analyze_action = QAction("Analyze Chain", self)
        analyze_action.triggered.connect(self._analyze_chain)
        toolbar.addAction(analyze_action)
        
    def _on_digitizer_applied(self, config):
        """Handle digitizer settings being applied."""
        self.chain_view.set_digitizer(config)
        
    def _on_component_selected(self, category, entry):
        """Handle component selection from library."""
        self.param_panel.set_component(entry)

    def _on_add_component(self, entry, params):
        """Handle adding a component to the chain."""
        try:
            # registry.create validates ranges and rejects unknown parameters,
            # so a bad value is reported here rather than deep in a model.
            component = registry.create(entry.type_id, params)
        except (KeyError, ValueError, TypeError) as exc:
            QMessageBox.critical(
                self, "Invalid Parameters",
                f"Could not create {entry.label}:\n\n{exc}"
            )
            return

        self.chain_view.add_component(component, describe_component(component))


    def _new_chain(self):
        """Create a new chain."""
        reply = QMessageBox.question(
            self, "New Chain",
            "Clear current chain and start new?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.chain_view._clear_all()
            
    def _save_chain(self):
        """Save the current chain to a JSON file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Chain", "", "JSON Files (*.json)"
        )

        if not file_path:
            return

        if not file_path.lower().endswith(".json"):
            file_path += ".json"

        chain = self.chain_view.get_chain(
            self.digitizer_panel.get_digitizer_config())
        try:
            chain.save(file_path)
        except OSError as exc:
            QMessageBox.critical(self, "Error", f"Failed to save chain:\n{exc}")
            return

        self.statusBar().showMessage(f"Saved {file_path}", 5000)

    def _load_chain(self):
        """Load a chain from a JSON file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Chain", "", "JSON Files (*.json)"
        )

        if not file_path:
            return

        try:
            chain = SignalChain.load(file_path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Error", f"Failed to load chain:\n{exc}")
            return

        self.chain_view.set_chain(chain)
        if chain.dac is not None or chain.adc is not None:
            self.digitizer_panel.set_digitizer_config(
                self.chain_view.digitizer_config)

        # A file that did not fully describe the chain must say so - a default
        # silently standing in for a saved value is how a bookkeeping record
        # stops matching the hardware it documents.
        if chain.load_warnings:
            QMessageBox.warning(
                self, "Loaded with warnings",
                "The chain loaded, but not everything in the file was used "
                "as-is:\n\n" + "\n".join(f"• {w}" for w in chain.load_warnings)
            )
        else:
            self.statusBar().showMessage(f"Loaded {file_path}", 5000)


    def _generate_diagram(self):
        """Generate a visual diagram of the chain."""
        digitizer_config = self.digitizer_panel.get_digitizer_config()
        chain = self.chain_view.get_chain(digitizer_config)
        
        if len(chain) == 0:
            QMessageBox.information(
                self, "Empty Chain",
                "Please add components to the chain first."
            )
            return
        
        # Update diagram panel and switch to diagram tab
        self.diagram_panel.set_chain(chain)
        self.diagram_panel.generate_diagram()
        self.results_tabs.setCurrentIndex(0)  # Switch to diagram tab
            
    def _analyze_chain(self):
        """Analyze the chain (gain and noise)."""
        digitizer_config = self.digitizer_panel.get_digitizer_config()
        chain = self.chain_view.get_chain(digitizer_config)
        
        if len(chain) == 0:
            QMessageBox.information(
                self, "Empty Chain",
                "Please add components to the chain first."
            )
            return
        
        # Update results panel and switch to results tab
        self.results_panel.set_chain(chain)
        self.results_panel.calculate_and_plot()
        self.results_tabs.setCurrentIndex(1)  # Switch to results tab
    
    def _show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self, "About Analog Chain Builder",
            "Analog Chain Builder v1.0\n\n"
            "A graphical interface for building and analyzing\n"
            "RF signal chains.\n\n"
            "Built with PySide6 (Qt for Python)"
        )
