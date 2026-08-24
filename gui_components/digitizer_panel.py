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
        
        # DAC Gain
        self.dac_gain_spin = QDoubleSpinBox()
        self.dac_gain_spin.setRange(-20, 20)
        self.dac_gain_spin.setValue(0.0)
        self.dac_gain_spin.setSuffix(" dB")
        self.dac_gain_spin.setDecimals(1)
        config_layout.addRow("DAC Gain:", self.dac_gain_spin)
        
        # ADC Gain
        self.adc_gain_spin = QDoubleSpinBox()
        self.adc_gain_spin.setRange(-20, 20)
        self.adc_gain_spin.setValue(0.0)
        self.adc_gain_spin.setSuffix(" dB")
        self.adc_gain_spin.setDecimals(1)
        config_layout.addRow("ADC Gain:", self.adc_gain_spin)
        
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
            'dac_gain_db': self.dac_gain_spin.value(),
            'adc_gain_db': self.adc_gain_spin.value()
        }
    
    def set_digitizer_config(self, config):
        """Set the digitizer configuration from a dict."""
        if 'model' in config:
            index = self.model_combo.findText(config['model'])
            if index >= 0:
                self.model_combo.setCurrentIndex(index)
        if 'carrier_power_dbm' in config:
            self.carrier_power_spin.setValue(config['carrier_power_dbm'])
        if 'dac_gain_db' in config:
            self.dac_gain_spin.setValue(config['dac_gain_db'])
        if 'adc_gain_db' in config:
            self.adc_gain_spin.setValue(config['adc_gain_db'])
