#!/usr/bin/env python3
"""
Analog Chain Builder GUI

A graphical interface for building and analyzing RF signal chains.
Allows users to select components, specify parameters, and construct
signal chains interactively.
"""

import sys
import json
import inspect
from pathlib import Path
import numpy as np

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTreeWidget, QTreeWidgetItem, QListWidget, QListWidgetItem,
    QFormLayout, QLabel, QLineEdit, QPushButton, QDoubleSpinBox,
    QSpinBox, QMessageBox, QFileDialog, QGroupBox, QToolBar, QDialog,
    QComboBox, QCheckBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QIcon

import matplotlib
matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

import hardware_models
from signal_chain import SignalChain
from diagram_generator import DiagramGenerator


class ComponentLibrary(QTreeWidget):
    """
    Tree widget displaying available hardware components organized by type.
    """
    
    component_selected = Signal(str, object)  # Signal emitting (category, class)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setHeaderLabel("Component Library")
        self.setColumnCount(1)
        
        # Component categories
        self.categories = {
            "Amplifiers": [],
            "Cables": [],
            "Attenuators": [],
            "Filters": [],
            "Converters": [],
            "Other": []
        }
        
        self._populate_library()
        self.itemClicked.connect(self._on_item_clicked)
        
    def _populate_library(self):
        """Scan hardware_models module and categorize components."""
        
        # Get all classes from hardware_models
        for name, obj in inspect.getmembers(hardware_models, inspect.isclass):
            if name.startswith('_'):
                continue
                
            # Categorize based on naming conventions
            if 'LNA' in name or 'Amp' in name.upper() or name.startswith('ZX') or name.startswith('ASU'):
                self.categories["Amplifiers"].append((name, obj))
            elif 'cable' in name.lower() or 'SMA' in name or 'BCB' in name or 'RG' in name:
                self.categories["Cables"].append((name, obj))
            elif 'Attenuator' in name:
                self.categories["Attenuators"].append((name, obj))
            elif 'Filter' in name:
                self.categories["Filters"].append((name, obj))
            elif 'AD9082' in name or 'DAC' in name or 'ADC' in name:
                self.categories["Converters"].append((name, obj))
            else:
                self.categories["Other"].append((name, obj))
        
        # Build tree structure
        for category, components in self.categories.items():
            if not components:
                continue
                
            category_item = QTreeWidgetItem(self, [category])
            category_item.setExpanded(True)
            
            for comp_name, comp_class in sorted(components, key=lambda x: x[0]):
                comp_item = QTreeWidgetItem(category_item, [comp_name])
                comp_item.setData(0, Qt.UserRole, comp_class)
                
    def _on_item_clicked(self, item, column):
        """Handle item selection."""
        comp_class = item.data(0, Qt.UserRole)
        if comp_class is not None:
            # This is a component, not a category
            category = item.parent().text(0)
            self.component_selected.emit(category, comp_class)


class ParameterPanel(QWidget):
    """
    Panel for specifying component parameters dynamically.
    """
    
    add_component = Signal(object, dict)  # Signal with (class, parameters)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.current_class = None
        self.param_widgets = {}
        
        layout = QVBoxLayout(self)
        
        # Group box for parameters
        self.group_box = QGroupBox("Component Parameters")
        self.form_layout = QFormLayout()
        self.group_box.setLayout(self.form_layout)
        layout.addWidget(self.group_box)
        
        # Selected component label
        self.selected_label = QLabel("No component selected")
        self.selected_label.setStyleSheet("font-weight: bold; color: #555;")
        self.form_layout.addRow("Selected:", self.selected_label)
        
        # Add button
        self.add_button = QPushButton("Add to Chain")
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self._on_add_clicked)
        layout.addWidget(self.add_button)
        
        layout.addStretch()
        
    def set_component(self, comp_class):
        """
        Configure parameter inputs for the selected component class.
        """
        self.current_class = comp_class
        self.param_widgets.clear()
        
        # Clear existing parameter widgets
        while self.form_layout.rowCount() > 1:
            self.form_layout.removeRow(1)
        
        # Update label
        self.selected_label.setText(comp_class.__name__)
        
        # Inspect __init__ signature
        sig = inspect.signature(comp_class.__init__)
        params = list(sig.parameters.items())[1:]  # Skip 'self'
        
        if not params:
            # No parameters needed
            info_label = QLabel("(No parameters required)")
            info_label.setStyleSheet("color: #777; font-style: italic;")
            self.form_layout.addRow(info_label)
            self.add_button.setEnabled(True)
            return
        
        # Create input widgets based on parameter names and defaults
        for param_name, param in params:
            widget = self._create_widget_for_parameter(param_name, param)
            if widget:
                self.param_widgets[param_name] = widget
                label = param_name.replace('_', ' ').title()
                self.form_layout.addRow(f"{label}:", widget)
        
        self.add_button.setEnabled(True)
        
    def _create_widget_for_parameter(self, param_name, param):
        """Create appropriate input widget for a parameter."""
        default_value = param.default if param.default != inspect.Parameter.empty else None
        
        # Determine widget type based on name and default
        if 'temperature' in param_name.lower():
            widget = QDoubleSpinBox()
            widget.setRange(0, 400)
            widget.setValue(default_value if default_value is not None else 300)
            widget.setSuffix(" K")
            return widget
            
        elif 'length' in param_name.lower():
            widget = QDoubleSpinBox()
            widget.setRange(0, 100)
            widget.setValue(default_value if default_value is not None else 1.0)
            widget.setSingleStep(0.1)
            widget.setSuffix(" m")
            return widget
            
        elif 'attenuation' in param_name.lower():
            widget = QDoubleSpinBox()
            widget.setRange(-100, 0)
            widget.setValue(default_value if default_value is not None else -3.0)
            widget.setSuffix(" dB")
            return widget
            
        else:
            # Generic numeric or text input
            widget = QLineEdit()
            if default_value is not None:
                widget.setText(str(default_value))
            return widget
    
    def _on_add_clicked(self):
        """Emit signal with component and parameters."""
        if not self.current_class:
            return
        
        # Gather parameter values
        params = {}
        for param_name, widget in self.param_widgets.items():
            if isinstance(widget, (QDoubleSpinBox, QSpinBox)):
                params[param_name] = widget.value()
            elif isinstance(widget, QLineEdit):
                text = widget.text()
                # Try to convert to number
                try:
                    params[param_name] = float(text)
                except ValueError:
                    params[param_name] = text
        
        self.add_component.emit(self.current_class, params)


class ChainView(QWidget):
    """
    View showing the current signal chain with reordering capabilities.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.chain = SignalChain("User Chain")
        
        layout = QVBoxLayout(self)
        
        # Label
        label = QLabel("Current Chain")
        label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(label)
        
        # List widget
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)
        
        # Control buttons
        button_layout = QHBoxLayout()
        
        self.up_button = QPushButton("▲ Up")
        self.up_button.clicked.connect(self._move_up)
        button_layout.addWidget(self.up_button)
        
        self.down_button = QPushButton("▼ Down")
        self.down_button.clicked.connect(self._move_down)
        button_layout.addWidget(self.down_button)
        
        self.remove_button = QPushButton("✖ Remove")
        self.remove_button.clicked.connect(self._remove_selected)
        button_layout.addWidget(self.remove_button)
        
        self.clear_button = QPushButton("Clear All")
        self.clear_button.clicked.connect(self._clear_all)
        button_layout.addWidget(self.clear_button)
        
        layout.addLayout(button_layout)
        
    def add_component(self, component, description):
        """Add a component to the chain."""
        self.chain.add_component(component)
        
        item = QListWidgetItem(description)
        item.setData(Qt.UserRole, component)
        self.list_widget.addItem(item)
        
    def _move_up(self):
        """Move selected component up in the chain."""
        current_row = self.list_widget.currentRow()
        if current_row > 0:
            item = self.list_widget.takeItem(current_row)
            self.list_widget.insertItem(current_row - 1, item)
            self.list_widget.setCurrentRow(current_row - 1)
            self._rebuild_chain()
            
    def _move_down(self):
        """Move selected component down in the chain."""
        current_row = self.list_widget.currentRow()
        if current_row < self.list_widget.count() - 1 and current_row >= 0:
            item = self.list_widget.takeItem(current_row)
            self.list_widget.insertItem(current_row + 1, item)
            self.list_widget.setCurrentRow(current_row + 1)
            self._rebuild_chain()
            
    def _remove_selected(self):
        """Remove selected component from chain."""
        current_row = self.list_widget.currentRow()
        if current_row >= 0:
            self.list_widget.takeItem(current_row)
            self._rebuild_chain()
            
    def _clear_all(self):
        """Clear all components from chain."""
        reply = QMessageBox.question(
            self, "Clear Chain",
            "Remove all components from the chain?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.list_widget.clear()
            self._rebuild_chain()
            
    def _rebuild_chain(self):
        """Rebuild the SignalChain object from current list."""
        self.chain = SignalChain("User Chain")
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            component = item.data(Qt.UserRole)
            self.chain.add_component(component)
    
    def get_chain(self):
        """Return the current SignalChain object."""
        self._rebuild_chain()
        return self.chain


class DiagramDisplayDialog(QDialog):
    """
    Dialog for displaying generated signal chain diagrams with save functionality.
    """
    
    def __init__(self, chain, parent=None):
        super().__init__(parent)
        
        self.chain = chain
        self.setWindowTitle("Signal Chain Diagram")
        self.setGeometry(150, 150, 1000, 700)
        
        layout = QVBoxLayout(self)
        
        # Parameter input section
        param_group = QGroupBox("Diagram Options")
        param_layout = QFormLayout()
        
        # Frequency for gain/noise display
        self.frequency_spin = QDoubleSpinBox()
        self.frequency_spin.setRange(0.001, 1000)
        self.frequency_spin.setValue(1.0)
        self.frequency_spin.setSuffix(" GHz")
        self.frequency_spin.setDecimals(3)
        param_layout.addRow("Frequency:", self.frequency_spin)
        
        # Show gain checkbox
        self.show_gain_check = QCheckBox("Show component gain values")
        self.show_gain_check.setChecked(True)
        param_layout.addRow("", self.show_gain_check)
        
        # Show noise checkbox
        self.show_noise_check = QCheckBox("Show component noise values")
        self.show_noise_check.setChecked(False)
        param_layout.addRow("", self.show_noise_check)
        
        param_group.setLayout(param_layout)
        layout.addWidget(param_group)
        
        # Generate button
        generate_button = QPushButton("Generate Diagram")
        generate_button.clicked.connect(self._generate_diagram)
        layout.addWidget(generate_button)
        
        # Matplotlib figure
        self.figure = Figure(figsize=(10, 6))
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)
        
        # Action buttons
        button_layout = QHBoxLayout()
        
        save_button = QPushButton("Save Diagram")
        save_button.clicked.connect(self._save_diagram)
        button_layout.addWidget(save_button)
        
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        button_layout.addWidget(close_button)
        
        layout.addLayout(button_layout)
        
        # Generate initial diagram
        self._generate_diagram()
        
    def _generate_diagram(self):
        """Generate and display the diagram."""
        try:
            frequency = self.frequency_spin.value() * 1e9  # Convert to Hz
            show_gain = self.show_gain_check.isChecked()
            show_noise = self.show_noise_check.isChecked()
            
            # Clear figure
            self.figure.clear()
            
            # Get axis
            ax = self.figure.add_subplot(111)
            ax.set_xlim(0, 10)
            ax.set_ylim(0, 10)
            ax.axis('off')
            
            # Title
            ax.text(5, 9.5, self.chain.name, ha='center', va='top', 
                    fontsize=16, fontweight='bold')
            
            n_components = len(self.chain.components)
            if n_components == 0:
                ax.text(5, 5, "Empty signal chain", ha='center', va='center', 
                        fontsize=12, style='italic')
                self.canvas.draw()
                return
            
            # Calculate layout
            box_width = 8.0 / max(n_components, 1)
            box_width = min(box_width, 1.5)  # Max width
            spacing = 8.0 / max(n_components - 1, 1) if n_components > 1 else 0
            
            start_x = 1.0
            y_center = 5.0
            box_height = 1.2
            
            # Draw components
            for idx, component in enumerate(self.chain.components):
                x = start_x + idx * spacing
                
                # Get component info
                label = self.chain._get_label_for_index(idx)
                comp_type = getattr(component, 'component_type', 'generic')
                
                # Choose color based on type
                if comp_type == 'active':
                    color = '#90EE90'  # Light green
                elif comp_type == 'passive':
                    color = '#ADD8E6'  # Light blue
                else:
                    color = '#F0F0F0'  # Light gray
                
                # Draw box
                box = FancyBboxPatch(
                    (x - box_width/2, y_center - box_height/2),
                    box_width, box_height,
                    boxstyle="round,pad=0.1",
                    edgecolor='black',
                    facecolor=color,
                    linewidth=1.5
                )
                ax.add_patch(box)
                
                # Component name (shortened if needed)
                display_name = label if len(label) <= 15 else label[:12] + "..."
                ax.text(x, y_center + 0.1, display_name, ha='center', va='center',
                        fontsize=8, fontweight='bold')
                
                # Add gain if requested
                if show_gain and hasattr(component, 'gain'):
                    gain_val = component.gain(frequency)
                    gain_text = f"{gain_val:+.1f} dB"
                    ax.text(x, y_center - 0.3, gain_text, ha='center', va='center',
                            fontsize=7, color='blue')
                
                # Add noise if requested
                if show_noise and hasattr(component, 'noise'):
                    noise_val = component.noise(frequency)
                    if noise_val > 0:
                        # Show noise temperature if thermal
                        if hasattr(component, 'temperature'):
                            noise_text = f"T={component.temperature}K"
                        else:
                            noise_text = f"{noise_val:.1e} W/Hz"
                        ax.text(x, y_center - 0.5, noise_text, ha='center', va='center',
                                fontsize=6, color='red', style='italic')
                
                # Draw arrow to next component
                if idx < n_components - 1:
                    next_x = start_x + (idx + 1) * spacing
                    arrow = FancyArrowPatch(
                        (x + box_width/2 + 0.05, y_center),
                        (next_x - box_width/2 - 0.05, y_center),
                        arrowstyle='->,head_width=0.3,head_length=0.2',
                        color='black',
                        linewidth=2
                    )
                    ax.add_patch(arrow)
            
            # Add summary statistics
            if show_gain:
                total_gain = self.chain.total_gain(frequency)
                ax.text(5, 1.5, f"Total Gain: {total_gain:+.1f} dB @ {frequency/1e9:.3f} GHz",
                        ha='center', va='center', fontsize=10, 
                        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
            
            if show_noise:
                spectral_frequency = 1e3  # 1 kHz offset
                total_noise = self.chain.output_noise(frequency, spectral_frequency)
                ax.text(5, 0.8, f"Output Noise: {total_noise:.2e} W/Hz @ {frequency/1e9:.3f} GHz (offset: {spectral_frequency/1e3:.1f} kHz)",
                        ha='center', va='center', fontsize=9,
                        bbox=dict(boxstyle='round', facecolor='lightcoral', alpha=0.5))
            
            self.figure.tight_layout()
            self.canvas.draw()
            
        except Exception as e:
            QMessageBox.critical(self, "Generation Error", 
                               f"Failed to generate diagram:\n{str(e)}")
    
    def _save_diagram(self):
        """Save the current diagram."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Diagram", "chain_diagram.pdf", 
            "PDF Files (*.pdf);;PNG Files (*.png);;SVG Files (*.svg)"
        )
        
        if not file_path:
            return
        
        try:
            self.figure.savefig(file_path, dpi=300, bbox_inches='tight')
            QMessageBox.information(self, "Success", f"Diagram saved to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save diagram:\n{str(e)}")


class SummaryDisplayDialog(QDialog):
    """
    Dialog for displaying chain summary with save functionality.
    """
    
    def __init__(self, chain, parent=None):
        super().__init__(parent)
        
        self.chain = chain
        self.setWindowTitle("Chain Summary")
        self.setGeometry(200, 200, 800, 600)
        
        layout = QVBoxLayout(self)
        
        # Title
        title_label = QLabel("Signal Chain Summary")
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title_label)
        
        # Text display area
        from PySide6.QtWidgets import QTextEdit
        self.text_display = QTextEdit()
        self.text_display.setReadOnly(True)
        self.text_display.setFont(QApplication.font())
        self.text_display.setStyleSheet("font-family: monospace; padding: 10px;")
        layout.addWidget(self.text_display)
        
        # Generate summary
        self._generate_summary()
        
        # Action buttons
        button_layout = QHBoxLayout()
        
        save_button = QPushButton("Save Summary")
        save_button.clicked.connect(self._save_summary)
        button_layout.addWidget(save_button)
        
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        button_layout.addWidget(close_button)
        
        layout.addLayout(button_layout)
        
    def _generate_summary(self):
        """Generate summary text."""
        try:
            # Build summary text
            summary = f"Signal Chain: {self.chain.name}\n"
            summary += f"Total components: {len(self.chain)}\n\n"
            summary += "Component List:\n"
            summary += "=" * 80 + "\n"
            
            for idx, component in enumerate(self.chain.components):
                comp_name = component.__class__.__name__
                label = self.chain._get_label_for_index(idx)
                comp_type = getattr(component, 'component_type', 'unknown')
                
                summary += f"  [{idx:2d}] {label}\n"
                summary += f"       Type: {comp_type}\n"
                
                # Add relevant parameters
                if hasattr(component, 'temperature'):
                    summary += f"       Temperature: {component.temperature} K\n"
                if hasattr(component, 'length'):
                    summary += f"       Length: {component.length} m\n"
                if hasattr(component, 'attenuation'):
                    summary += f"       Attenuation: {component.attenuation} dB\n"
                
                summary += "\n"
            
            summary += "=" * 80 + "\n"
            
            # Add gain calculation at a reference frequency
            ref_freq = 1e9  # 1 GHz
            try:
                total_gain = self.chain.total_gain(ref_freq)
                summary += f"\nTotal Gain @ {ref_freq/1e9:.2f} GHz: {total_gain:+.2f} dB\n"
            except Exception as e:
                summary += f"\nTotal Gain calculation: Error - {str(e)}\n"
            
            # Add noise calculation
            try:
                spectral_freq = 1e3  # 1 kHz
                output_noise = self.chain.output_noise(ref_freq, spectral_freq)
                summary += f"Output Noise @ {ref_freq/1e9:.2f} GHz ({spectral_freq/1e3:.1f} kHz offset): {output_noise:.2e} W/Hz\n"
            except Exception as e:
                summary += f"Output Noise calculation: Error - {str(e)}\n"
            
            self.text_display.setPlainText(summary)
            
        except Exception as e:
            self.text_display.setPlainText(f"Error generating summary:\n{str(e)}")
    
    def _save_summary(self):
        """Save the summary to a text file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Summary", "chain_summary.txt", 
            "Text Files (*.txt);;All Files (*)"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'w') as f:
                f.write(self.text_display.toPlainText())
            
            QMessageBox.information(self, "Success", f"Summary saved to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save summary:\n{str(e)}")


class GainAnalysisDialog(QDialog):
    """
    Dialog for analyzing system gain as a function of carrier frequency.
    """
    
    def __init__(self, chain, parent=None):
        super().__init__(parent)
        
        self.chain = chain
        self.setWindowTitle("Gain vs Frequency Analysis")
        self.setGeometry(200, 200, 900, 700)
        
        layout = QVBoxLayout(self)
        
        # Parameter input section
        param_group = QGroupBox("Frequency Range Parameters")
        param_layout = QFormLayout()
        
        # Start frequency
        self.start_freq_spin = QDoubleSpinBox()
        self.start_freq_spin.setRange(0.001, 1000)
        self.start_freq_spin.setValue(0.1)
        self.start_freq_spin.setSuffix(" GHz")
        self.start_freq_spin.setDecimals(3)
        param_layout.addRow("Start Frequency:", self.start_freq_spin)
        
        # Stop frequency
        self.stop_freq_spin = QDoubleSpinBox()
        self.stop_freq_spin.setRange(0.001, 1000)
        self.stop_freq_spin.setValue(3.0)
        self.stop_freq_spin.setSuffix(" GHz")
        self.stop_freq_spin.setDecimals(3)
        param_layout.addRow("Stop Frequency:", self.stop_freq_spin)
        
        # Number of points
        self.num_points_spin = QSpinBox()
        self.num_points_spin.setRange(10, 10000)
        self.num_points_spin.setValue(100)
        param_layout.addRow("Number of Points:", self.num_points_spin)
        
        # Spacing type
        self.spacing_combo = QComboBox()
        self.spacing_combo.addItems(["Logarithmic", "Linear"])
        param_layout.addRow("Frequency Spacing:", self.spacing_combo)
        
        param_group.setLayout(param_layout)
        layout.addWidget(param_group)
        
        # Calculate button
        calc_button = QPushButton("Calculate && Plot")
        calc_button.clicked.connect(self._calculate_and_plot)
        layout.addWidget(calc_button)
        
        # Matplotlib figure
        self.figure = Figure(figsize=(8, 5))
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)
        
        # Results label
        self.results_label = QLabel("")
        self.results_label.setStyleSheet("padding: 5px; background-color: #f0f0f0;")
        layout.addWidget(self.results_label)
        
        # Action buttons
        button_layout = QHBoxLayout()
        
        export_button = QPushButton("Export Data (CSV)")
        export_button.clicked.connect(self._export_data)
        button_layout.addWidget(export_button)
        
        save_plot_button = QPushButton("Save Plot")
        save_plot_button.clicked.connect(self._save_plot)
        button_layout.addWidget(save_plot_button)
        
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        button_layout.addWidget(close_button)
        
        layout.addLayout(button_layout)
        
        # Store data for export
        self.freq_data = None
        self.gain_data = None
        
    def _calculate_and_plot(self):
        """Calculate gain and plot results."""
        try:
            # Get parameters
            start_freq = self.start_freq_spin.value() * 1e9  # Convert to Hz
            stop_freq = self.stop_freq_spin.value() * 1e9
            num_points = self.num_points_spin.value()
            is_log = self.spacing_combo.currentText() == "Logarithmic"
            
            if start_freq >= stop_freq:
                QMessageBox.warning(self, "Invalid Range", 
                                  "Start frequency must be less than stop frequency.")
                return
            
            # Generate frequency array
            if is_log:
                self.freq_data = np.logspace(np.log10(start_freq), np.log10(stop_freq), num_points)
            else:
                self.freq_data = np.linspace(start_freq, stop_freq, num_points)
            
            # Calculate gain at each frequency
            self.gain_data = np.array([self.chain.total_gain(f) for f in self.freq_data])
            
            # Plot
            self.figure.clear()
            ax = self.figure.add_subplot(111)
            
            if is_log:
                ax.semilogx(self.freq_data / 1e9, self.gain_data, 'b-', linewidth=2)
            else:
                ax.plot(self.freq_data / 1e9, self.gain_data, 'b-', linewidth=2)
            
            ax.grid(True, alpha=0.3)
            ax.set_xlabel('Frequency (GHz)', fontsize=11)
            ax.set_ylabel('Total Gain (dB)', fontsize=11)
            ax.set_title(f'System Gain vs Frequency: {self.chain.name}', fontsize=12, fontweight='bold')
            
            self.figure.tight_layout()
            self.canvas.draw()
            
            # Update results summary
            min_gain = np.min(self.gain_data)
            max_gain = np.max(self.gain_data)
            min_freq = self.freq_data[np.argmin(self.gain_data)] / 1e9
            max_freq = self.freq_data[np.argmax(self.gain_data)] / 1e9
            
            results_text = (f"Min Gain: {min_gain:.2f} dB @ {min_freq:.3f} GHz  |  "
                          f"Max Gain: {max_gain:.2f} dB @ {max_freq:.3f} GHz")
            self.results_label.setText(results_text)
            
        except Exception as e:
            QMessageBox.critical(self, "Calculation Error", 
                               f"Failed to calculate gain:\n{str(e)}")
    
    def _export_data(self):
        """Export frequency and gain data to CSV."""
        if self.freq_data is None or self.gain_data is None:
            QMessageBox.warning(self, "No Data", "Please calculate gain first.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Data", "gain_analysis.csv", "CSV Files (*.csv)"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'w') as f:
                f.write("Frequency_Hz,Frequency_GHz,Gain_dB\n")
                for freq, gain in zip(self.freq_data, self.gain_data):
                    f.write(f"{freq},{freq/1e9},{gain}\n")
            
            QMessageBox.information(self, "Success", f"Data exported to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export data:\n{str(e)}")
    
    def _save_plot(self):
        """Save the current plot."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Plot", "gain_plot.png", 
            "PNG Files (*.png);;PDF Files (*.pdf);;SVG Files (*.svg)"
        )
        
        if not file_path:
            return
        
        try:
            self.figure.savefig(file_path, dpi=300, bbox_inches='tight')
            QMessageBox.information(self, "Success", f"Plot saved to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save plot:\n{str(e)}")


class NoiseAnalysisDialog(QDialog):
    """
    Dialog for analyzing noise spectrum at a given carrier frequency.
    """
    
    def __init__(self, chain, parent=None):
        super().__init__(parent)
        
        self.chain = chain
        self.setWindowTitle("Noise Spectrum Analysis")
        self.setGeometry(200, 200, 900, 700)
        
        layout = QVBoxLayout(self)
        
        # Parameter input section
        param_group = QGroupBox("Analysis Parameters")
        param_layout = QFormLayout()
        
        # Carrier frequency
        self.carrier_freq_spin = QDoubleSpinBox()
        self.carrier_freq_spin.setRange(0.001, 1000)
        self.carrier_freq_spin.setValue(1.0)
        self.carrier_freq_spin.setSuffix(" GHz")
        self.carrier_freq_spin.setDecimals(3)
        param_layout.addRow("Carrier Frequency:", self.carrier_freq_spin)
        
        # Start spectral frequency
        self.start_spectral_spin = QDoubleSpinBox()
        self.start_spectral_spin.setRange(0.001, 1e6)
        self.start_spectral_spin.setValue(0.01)
        self.start_spectral_spin.setSuffix(" kHz")
        self.start_spectral_spin.setDecimals(3)
        param_layout.addRow("Start Offset Freq:", self.start_spectral_spin)
        
        # Stop spectral frequency
        self.stop_spectral_spin = QDoubleSpinBox()
        self.stop_spectral_spin.setRange(0.001, 1e6)
        self.stop_spectral_spin.setValue(100.0)
        self.stop_spectral_spin.setSuffix(" kHz")
        self.stop_spectral_spin.setDecimals(3)
        param_layout.addRow("Stop Offset Freq:", self.stop_spectral_spin)
        
        # Number of points
        self.num_points_spin = QSpinBox()
        self.num_points_spin.setRange(10, 10000)
        self.num_points_spin.setValue(100)
        param_layout.addRow("Number of Points:", self.num_points_spin)
        
        # Spacing type
        self.spacing_combo = QComboBox()
        self.spacing_combo.addItems(["Logarithmic", "Linear"])
        param_layout.addRow("Frequency Spacing:", self.spacing_combo)
        
        # Show contributions checkbox
        self.show_contributions_check = QCheckBox("Show Individual Component Contributions")
        param_layout.addRow("", self.show_contributions_check)
        
        param_group.setLayout(param_layout)
        layout.addWidget(param_group)
        
        # Calculate button
        calc_button = QPushButton("Calculate && Plot")
        calc_button.clicked.connect(self._calculate_and_plot)
        layout.addWidget(calc_button)
        
        # Matplotlib figure
        self.figure = Figure(figsize=(8, 5))
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)
        
        # Results label
        self.results_label = QLabel("")
        self.results_label.setStyleSheet("padding: 5px; background-color: #f0f0f0;")
        layout.addWidget(self.results_label)
        
        # Action buttons
        button_layout = QHBoxLayout()
        
        export_button = QPushButton("Export Data (CSV)")
        export_button.clicked.connect(self._export_data)
        button_layout.addWidget(export_button)
        
        save_plot_button = QPushButton("Save Plot")
        save_plot_button.clicked.connect(self._save_plot)
        button_layout.addWidget(save_plot_button)
        
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        button_layout.addWidget(close_button)
        
        layout.addLayout(button_layout)
        
        # Store data for export
        self.spectral_freq_data = None
        self.noise_data = None
        self.contributions_data = None
        
    def _calculate_and_plot(self):
        """Calculate noise spectrum and plot results."""
        try:
            # Get parameters
            carrier_freq = self.carrier_freq_spin.value() * 1e9  # Convert to Hz
            start_spectral = self.start_spectral_spin.value() * 1e3  # Convert to Hz
            stop_spectral = self.stop_spectral_spin.value() * 1e3
            num_points = self.num_points_spin.value()
            is_log = self.spacing_combo.currentText() == "Logarithmic"
            show_contributions = self.show_contributions_check.isChecked()
            
            if start_spectral >= stop_spectral:
                QMessageBox.warning(self, "Invalid Range", 
                                  "Start offset frequency must be less than stop offset frequency.")
                return
            
            # Generate spectral frequency array
            if is_log:
                self.spectral_freq_data = np.logspace(np.log10(start_spectral), 
                                                     np.log10(stop_spectral), num_points)
            else:
                self.spectral_freq_data = np.linspace(start_spectral, stop_spectral, num_points)
            
            # Calculate noise at each spectral frequency
            if show_contributions:
                self.noise_data = []
                self.contributions_data = {}
                
                for spectral_freq in self.spectral_freq_data:
                    total_noise, contributions = self.chain.noise_at_point(
                        len(self.chain) - 1, carrier_freq, spectral_freq, contributions=True
                    )
                    self.noise_data.append(total_noise)
                    
                    # Store contributions
                    for label, noise_val in contributions.items():
                        if label not in self.contributions_data:
                            self.contributions_data[label] = []
                        self.contributions_data[label].append(noise_val)
                
                self.noise_data = np.array(self.noise_data)
            else:
                self.noise_data = np.array([
                    self.chain.output_noise(carrier_freq, f) 
                    for f in self.spectral_freq_data
                ])
                self.contributions_data = None
            
            # Plot
            self.figure.clear()
            ax = self.figure.add_subplot(111)
            
            if is_log:
                ax.loglog(self.spectral_freq_data / 1e3, self.noise_data, 
                         'b-', linewidth=2, label='Total Noise')
            else:
                ax.semilogy(self.spectral_freq_data / 1e3, self.noise_data, 
                           'b-', linewidth=2, label='Total Noise')
            
            # Plot individual contributions if requested
            if show_contributions and self.contributions_data:
                for label, noise_vals in self.contributions_data.items():
                    if is_log:
                        ax.loglog(self.spectral_freq_data / 1e3, noise_vals, 
                                 '--', alpha=0.6, linewidth=1.5, label=label)
                    else:
                        ax.semilogy(self.spectral_freq_data / 1e3, noise_vals, 
                                   '--', alpha=0.6, linewidth=1.5, label=label)
                ax.legend(fontsize=8, loc='best')
            
            ax.grid(True, alpha=0.3)
            ax.set_xlabel('Offset Frequency (kHz)', fontsize=11)
            ax.set_ylabel('Noise PSD (W/Hz)', fontsize=11)
            ax.set_title(f'Output Noise Spectrum at {carrier_freq/1e9:.2f} GHz Carrier', 
                        fontsize=12, fontweight='bold')
            
            self.figure.tight_layout()
            self.canvas.draw()
            
            # Update results summary
            min_noise = np.min(self.noise_data)
            max_noise = np.max(self.noise_data)
            avg_noise = np.mean(self.noise_data)
            
            results_text = (f"Min: {min_noise:.2e} W/Hz  |  "
                          f"Max: {max_noise:.2e} W/Hz  |  "
                          f"Avg: {avg_noise:.2e} W/Hz")
            self.results_label.setText(results_text)
            
        except Exception as e:
            QMessageBox.critical(self, "Calculation Error", 
                               f"Failed to calculate noise:\n{str(e)}")
    
    def _export_data(self):
        """Export spectral frequency and noise data to CSV."""
        if self.spectral_freq_data is None or self.noise_data is None:
            QMessageBox.warning(self, "No Data", "Please calculate noise first.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Data", "noise_analysis.csv", "CSV Files (*.csv)"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'w') as f:
                # Header
                header = "Spectral_Freq_Hz,Spectral_Freq_kHz,Total_Noise_W_per_Hz"
                if self.contributions_data:
                    for label in self.contributions_data.keys():
                        header += f",{label}_W_per_Hz"
                f.write(header + "\n")
                
                # Data rows
                for i, (spectral_freq, noise) in enumerate(zip(self.spectral_freq_data, self.noise_data)):
                    row = f"{spectral_freq},{spectral_freq/1e3},{noise}"
                    if self.contributions_data:
                        for label in self.contributions_data.keys():
                            row += f",{self.contributions_data[label][i]}"
                    f.write(row + "\n")
            
            QMessageBox.information(self, "Success", f"Data exported to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export data:\n{str(e)}")
    
    def _save_plot(self):
        """Save the current plot."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Plot", "noise_plot.png", 
            "PNG Files (*.png);;PDF Files (*.pdf);;SVG Files (*.svg)"
        )
        
        if not file_path:
            return
        
        try:
            self.figure.savefig(file_path, dpi=300, bbox_inches='tight')
            QMessageBox.information(self, "Success", f"Plot saved to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save plot:\n{str(e)}")


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


def main():
    """Main application entry point."""
    app = QApplication(sys.argv)
    
    # Set application style
    app.setStyle("Fusion")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
