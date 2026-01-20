"""
Parameter Panel Widget

Allows users to specify component parameters dynamically.
"""

import inspect
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLabel, QLineEdit, 
    QPushButton, QDoubleSpinBox, QSpinBox, QGroupBox
)
from PySide6.QtCore import Signal


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
