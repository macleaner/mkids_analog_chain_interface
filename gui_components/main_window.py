"""
Main Window

Main application window for the Analog Chain Builder.
"""

import sys
import json
import inspect
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QSplitter,
    QMessageBox, QFileDialog, QToolBar
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction

import hardware_models

from .component_library import ComponentLibrary
from .chain_view import ChainView
from .parameter_panel import ParameterPanel
from .dialogs import (
    DiagramDisplayDialog,
    SummaryDisplayDialog,
    GainAnalysisDialog,
    NoiseAnalysisDialog
)


class MainWindow(QMainWindow):
    """
    Main application window for the chain builder.
    """
    
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("Analog Chain Builder")
        self.setGeometry(100, 100, 1200, 700)
        
        self._setup_ui()
        self._create_menu_bar()
        self._create_toolbar()
        
    def _setup_ui(self):
        """Set up the main UI layout."""
        
        # Central widget with splitter
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        
        splitter = QSplitter(Qt.Horizontal)
        
        # Left: Component library
        self.library = ComponentLibrary()
        self.library.component_selected.connect(self._on_component_selected)
        splitter.addWidget(self.library)
        
        # Middle: Chain view
        self.chain_view = ChainView()
        splitter.addWidget(self.chain_view)
        
        # Right: Parameter panel
        self.param_panel = ParameterPanel()
        self.param_panel.add_component.connect(self._on_add_component)
        splitter.addWidget(self.param_panel)
        
        # Set splitter proportions
        splitter.setSizes([300, 400, 300])
        
        main_layout.addWidget(splitter)
        
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
        
        summary_action = QAction("Show Chain &Summary", self)
        summary_action.triggered.connect(self._show_summary)
        tools_menu.addAction(summary_action)
        
        tools_menu.addSeparator()
        
        gain_analysis_action = QAction("Analyze &Gain vs Frequency...", self)
        gain_analysis_action.triggered.connect(self._show_gain_analysis)
        tools_menu.addAction(gain_analysis_action)
        
        noise_analysis_action = QAction("Analyze &Noise Spectrum...", self)
        noise_analysis_action.triggered.connect(self._show_noise_analysis)
        tools_menu.addAction(noise_analysis_action)
        
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
        
        summary_action = QAction("Show Chain Summary", self)
        summary_action.triggered.connect(self._show_summary)
        toolbar.addAction(summary_action)
        
        toolbar.addSeparator()
        
        gain_analysis_action = QAction("Analyze Gain vs Frequency", self)
        gain_analysis_action.triggered.connect(self._show_gain_analysis)
        toolbar.addAction(gain_analysis_action)
        
        noise_analysis_action = QAction("Analyze Noise Spectrum", self)
        noise_analysis_action.triggered.connect(self._show_noise_analysis)
        toolbar.addAction(noise_analysis_action)
        
    def _on_component_selected(self, category, comp_class):
        """Handle component selection from library."""
        self.param_panel.set_component(comp_class)
        
    def _on_add_component(self, comp_class, params):
        """Handle adding a component to the chain."""
        try:
            # Instantiate component with parameters
            component = comp_class(**params)
            
            # Create description string
            param_str = ", ".join(f"{k}={v}" for k, v in params.items())
            if param_str:
                description = f"{comp_class.__name__} ({param_str})"
            else:
                description = comp_class.__name__
            
            # Add to chain view
            self.chain_view.add_component(component, description)
            
        except Exception as e:
            QMessageBox.critical(
                self, "Error",
                f"Failed to create component:\n{str(e)}"
            )
    
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
        
        # Build chain data
        chain_data = []
        for i in range(self.chain_view.list_widget.count()):
            item = self.chain_view.list_widget.item(i)
            component = item.data(Qt.UserRole)
            
            # Extract component info
            comp_info = {
                'class': component.__class__.__name__,
                'description': item.text(),
                'parameters': {}
            }
            
            # Try to extract parameters from component attributes
            sig = inspect.signature(component.__class__.__init__)
            for param_name in list(sig.parameters.keys())[1:]:
                if hasattr(component, param_name):
                    value = getattr(component, param_name)
                    # Only save serializable types
                    if isinstance(value, (int, float, str, bool)):
                        comp_info['parameters'][param_name] = value
            
            chain_data.append(comp_info)
        
        # Save to file
        try:
            with open(file_path, 'w') as f:
                json.dump(chain_data, f, indent=2)
            QMessageBox.information(self, "Success", "Chain saved successfully!")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save chain:\n{str(e)}")
            
    def _load_chain(self):
        """Load a chain from a JSON file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Chain", "", "JSON Files (*.json)"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'r') as f:
                chain_data = json.load(f)
            
            # Clear current chain
            self.chain_view.list_widget.clear()
            
            # Rebuild chain
            for comp_info in chain_data:
                class_name = comp_info['class']
                params = comp_info['parameters']
                
                # Get class from hardware_models
                if hasattr(hardware_models, class_name):
                    comp_class = getattr(hardware_models, class_name)
                    component = comp_class(**params)
                    self.chain_view.add_component(component, comp_info['description'])
                else:
                    QMessageBox.warning(
                        self, "Warning",
                        f"Unknown component class: {class_name}"
                    )
            
            QMessageBox.information(self, "Success", "Chain loaded successfully!")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load chain:\n{str(e)}")
            
    def _generate_diagram(self):
        """Generate a visual diagram of the chain."""
        chain = self.chain_view.get_chain()
        
        if len(chain) == 0:
            QMessageBox.information(
                self, "Empty Chain",
                "Please add components to the chain first."
            )
            return
        
        # Show diagram in a dialog with save functionality
        dialog = DiagramDisplayDialog(chain, self)
        dialog.exec()
            
    def _show_summary(self):
        """Display chain summary information."""
        chain = self.chain_view.get_chain()
        
        if len(chain) == 0:
            QMessageBox.information(
                self, "Empty Chain",
                "Please add components to the chain first."
            )
            return
        
        # Show summary in a dialog with save functionality
        dialog = SummaryDisplayDialog(chain, self)
        dialog.exec()
        
    def _show_gain_analysis(self):
        """Show gain analysis dialog."""
        chain = self.chain_view.get_chain()
        
        if len(chain) == 0:
            QMessageBox.information(
                self, "Empty Chain",
                "Please add components to the chain first."
            )
            return
        
        dialog = GainAnalysisDialog(chain, self)
        dialog.exec()
    
    def _show_noise_analysis(self):
        """Show noise analysis dialog."""
        chain = self.chain_view.get_chain()
        
        if len(chain) == 0:
            QMessageBox.information(
                self, "Empty Chain",
                "Please add components to the chain first."
            )
            return
        
        dialog = NoiseAnalysisDialog(chain, self)
        dialog.exec()
    
    def _show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self, "About Analog Chain Builder",
            "Analog Chain Builder v1.0\n\n"
            "A graphical interface for building and analyzing\n"
            "RF signal chains.\n\n"
            "Built with PySide6 (Qt for Python)"
        )
