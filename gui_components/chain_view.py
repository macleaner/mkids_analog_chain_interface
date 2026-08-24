"""
Chain View Widget

Displays and manages the current signal chain with reordering capabilities.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QListWidget, QListWidgetItem, QPushButton, QMessageBox
)
from PySide6.QtCore import Qt

import registry
from signal_chain import SignalChain


def describe_component(component):
    """
    One-line description of a component for the chain list.

    Built from the component's declared parameters, so it stays accurate as
    parameters change and always reflects what will actually be serialized.
    """
    try:
        label = registry.resolve(component.type_id).label
    except (KeyError, AttributeError):
        label = type(component).__name__

    params = getattr(component, "params", {}) or {}
    if not params:
        return label

    try:
        specs = {s.name: s for s in registry.resolve(component.type_id).params}
    except (KeyError, AttributeError):
        specs = {}

    parts = []
    for key, value in params.items():
        unit = specs[key].unit if key in specs else ""
        rendered = f"{value:g}" if isinstance(value, (int, float)) else str(value)
        parts.append(f"{rendered}{(' ' + unit) if unit else ''}")
    return f"{label} ({', '.join(parts)})"


class ChainView(QWidget):
    """
    View showing the current signal chain with reordering capabilities.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.chain = SignalChain("User Chain")
        self.digitizer_config = None  # Store current digitizer config
        
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
        item.setData(Qt.UserRole + 1, False)  # Mark as regular component (not digitizer)
        
        # If ADC is at the bottom, insert before it; otherwise add at the end
        if self._has_adc_at_bottom():
            # Insert before the last item (which is the ADC)
            self.list_widget.insertItem(self.list_widget.count() - 1, item)
        else:
            self.list_widget.addItem(item)
    
    def set_digitizer(self, config):
        """Set and display the digitizer at the top and bottom of the chain."""
        self.digitizer_config = config
        
        # Remove existing digitizer items if present
        items_to_remove = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole + 1):  # Check if it's a digitizer item
                items_to_remove.append(i)
        
        # Remove in reverse order to maintain indices
        for i in reversed(items_to_remove):
            self.list_widget.takeItem(i)
        
        from PySide6.QtGui import QFont, QColor
        
        # Create DAC display text and item (at the top)
        dac_text = f"🔸 {config['model']} DAC (Pcarrier={config['carrier_power_dbm']:.1f} dBm, Gain={config['dac_gain_db']:.1f} dB)"
        dac_item = QListWidgetItem(dac_text)
        dac_item.setData(Qt.UserRole, None)  # No actual component object
        dac_item.setData(Qt.UserRole + 1, True)  # Mark as digitizer item
        dac_item.setFlags(dac_item.flags() & ~Qt.ItemIsSelectable)  # Make non-selectable
        
        # Style DAC item
        font = QFont()
        font.setBold(True)
        dac_item.setFont(font)
        dac_item.setForeground(QColor(0, 100, 200))  # Blue color
        
        # Insert DAC at the top
        self.list_widget.insertItem(0, dac_item)
        
        # Create ADC display text and item (at the bottom)
        adc_text = f"🔸 {config['model']} ADC (Gain={config['adc_gain_db']:.1f} dB)"
        adc_item = QListWidgetItem(adc_text)
        adc_item.setData(Qt.UserRole, None)  # No actual component object
        adc_item.setData(Qt.UserRole + 1, True)  # Mark as digitizer item
        adc_item.setFlags(adc_item.flags() & ~Qt.ItemIsSelectable)  # Make non-selectable
        
        # Style ADC item
        adc_item.setFont(font)
        adc_item.setForeground(QColor(0, 100, 200))  # Blue color
        
        # Add ADC at the bottom
        self.list_widget.addItem(adc_item)
        
    def _move_up(self):
        """Move selected component up in the chain."""
        current_row = self.list_widget.currentRow()
        # Prevent moving above digitizer (if present)
        min_row = 1 if self._has_digitizer() else 0
        if current_row > min_row:
            item = self.list_widget.takeItem(current_row)
            self.list_widget.insertItem(current_row - 1, item)
            self.list_widget.setCurrentRow(current_row - 1)
            self._rebuild_chain()
            
    def _move_down(self):
        """Move selected component down in the chain."""
        current_row = self.list_widget.currentRow()
        # Prevent moving below ADC (if present at bottom)
        max_row = self.list_widget.count() - 2 if self._has_adc_at_bottom() else self.list_widget.count() - 1
        if current_row < max_row and current_row >= 0:
            item = self.list_widget.takeItem(current_row)
            self.list_widget.insertItem(current_row + 1, item)
            self.list_widget.setCurrentRow(current_row + 1)
            self._rebuild_chain()
            
    def _remove_selected(self):
        """Remove selected component from chain."""
        current_row = self.list_widget.currentRow()
        if current_row >= 0:
            item = self.list_widget.item(current_row)
            # Don't allow removing digitizer item
            if not item.data(Qt.UserRole + 1):  # Not a digitizer item
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
        """
        Rebuild the SignalChain from the current list rows.

        Carries the chain's bookkeeping fields across the rebuild - they came
        from a loaded file or from the user, not from the widget, so recreating
        a bare SignalChain here would silently drop them on the next save.
        Saved labels are likewise preserved, since they are the stable handle
        for referring to a point in the chain.
        """
        previous = self.chain
        self.chain = SignalChain(
            name=previous.name if previous is not None else "User Chain",
            description=previous.description if previous is not None else "",
            metadata=previous.metadata if previous is not None else None,
        )
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            # Skip digitizer items (they're handled separately)
            if item.data(Qt.UserRole + 1):
                continue
            component = item.data(Qt.UserRole)
            self.chain.add_component(component, label=item.data(Qt.UserRole + 2))
    
    def _has_digitizer(self):
        """Check if a digitizer item is present at the top."""
        if self.list_widget.count() > 0:
            first_item = self.list_widget.item(0)
            return first_item.data(Qt.UserRole + 1) if first_item else False
        return False
    
    def _has_adc_at_bottom(self):
        """Check if an ADC digitizer item is present at the bottom."""
        if self.list_widget.count() > 0:
            last_item = self.list_widget.item(self.list_widget.count() - 1)
            return last_item.data(Qt.UserRole + 1) if last_item else False
        return False
    
    def get_chain(self, digitizer_config=None):
        """
        Return the current SignalChain, including the digitizer endpoints.

        Args:
            digitizer_config: Digitizer panel configuration dict. If None, the
                stored config is used.
        """
        self._rebuild_chain()

        config = digitizer_config or self.digitizer_config
        if config and config.get('model') == 'AD9082':
            self.chain.set_digitizer(
                registry.create("converter.ad9082_dac", {
                    "carrier_power_dbm": config['carrier_power_dbm'],
                    "gain_db": config['dac_gain_db'],
                }, name='AD9082_DAC'),
                registry.create("converter.ad9082_adc", {
                    "gain_db": config['adc_gain_db'],
                }, name='AD9082_ADC'),
            )

        return self.chain

    def set_chain(self, chain):
        """
        Replace the displayed chain with ``chain``, e.g. after loading a file.

        Rebuilds the list rows from the chain's components, preserving their
        saved labels, and restores the digitizer rows if the chain has them.
        """
        self.list_widget.clear()
        self.chain = chain
        self.digitizer_config = None

        if chain.dac is not None or chain.adc is not None:
            dac_params = chain.dac.params if chain.dac is not None else {}
            adc_params = chain.adc.params if chain.adc is not None else {}
            self.digitizer_config = {
                'model': 'AD9082',
                'carrier_power_dbm': dac_params.get('carrier_power_dbm', 0.0),
                'dac_gain_db': dac_params.get('gain_db', 0.0),
                'adc_gain_db': adc_params.get('gain_db', 0.0),
            }

        labels = {index: label for label, index in chain.labels.items()}
        for idx, component in enumerate(chain.components):
            item = QListWidgetItem(describe_component(component))
            item.setData(Qt.UserRole, component)
            item.setData(Qt.UserRole + 1, False)
            item.setData(Qt.UserRole + 2, labels.get(idx))
            self.list_widget.addItem(item)

        if self.digitizer_config is not None:
            # Adds the styled DAC/ADC rows at top and bottom.
            self.set_digitizer(self.digitizer_config)
