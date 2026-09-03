"""
Digitizer Panel Widget

Displays and manages digitizer configuration settings.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, 
    QFormLayout, QComboBox, QDoubleSpinBox, QPushButton
)
from PySide6.QtCore import Signal


class DigitizerPanel(QWidget):
    """
    Panel for configuring digitizer DAC/ADC settings.
    """
    
    digitizer_applied = Signal(dict)  # Signal emitting digitizer config when applied
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        
        # Label
        label = QLabel("Digitizer Configuration")
        label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(label)
        
        # Configuration Group
        config_group = QGroupBox("Settings")
        config_layout = QFormLayout()
        
        # Model selector
        self.model_combo = QComboBox()
        self.model_combo.addItem("AD9082")
        self.model_combo.setCurrentIndex(0)
        config_layout.addRow("Model:", self.model_combo)
        
        # Carrier Power
        self.carrier_power_spin = QDoubleSpinBox()
        self.carrier_power_spin.setRange(-50, 10)
        self.carrier_power_spin.setValue(-40.0)
        self.carrier_power_spin.setSuffix(" dBm")
        self.carrier_power_spin.setDecimals(1)
        config_layout.addRow("Carrier Power:", self.carrier_power_spin)
        
        # No gain inputs: a converter is the boundary of the analog path,
        # not a stage along it, so it has no gain (see ConverterComponent).
        # Gain at either end is an amplifier or an attenuator and is added to
        # the chain as one.
        
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)
        
        # Apply button
        self.apply_button = QPushButton("Apply Digitizer Settings")
        self.apply_button.clicked.connect(self._on_apply)
        layout.addWidget(self.apply_button)
        
        # Add stretch to push everything to the top
        layout.addStretch()
    
    def _on_apply(self):
        """Handle Apply button click."""
        config = self.get_digitizer_config()
        self.digitizer_applied.emit(config)
        
    def get_digitizer_config(self):
        """Get the current digitizer configuration."""
        return {
            'model': self.model_combo.currentText(),
            'carrier_power_dbm': self.carrier_power_spin.value(),
        }
    
    def set_digitizer_config(self, config):
        """Set the digitizer configuration from a dict."""
        if 'model' in config:
            index = self.model_combo.findText(config['model'])
            if index >= 0:
                self.model_combo.setCurrentIndex(index)
        if 'carrier_power_dbm' in config:
            self.carrier_power_spin.setValue(config['carrier_power_dbm'])
