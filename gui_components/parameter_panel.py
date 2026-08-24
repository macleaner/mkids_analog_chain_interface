"""
Parameter Panel Widget

Builds parameter inputs from the specification each component declares in the
registry, rather than inferring them from its ``__init__`` signature.

Reflection had two problems the specs remove: widget type and range were guessed
from substrings in the parameter name ('temperature' anywhere in the name meant
a 0-400 K spinbox), and constraints enforced inside a constructor were invisible
to the GUI, so the panel would happily offer a value that then raised.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPushButton, QDoubleSpinBox, QSpinBox, QComboBox, QCheckBox, QGroupBox
)
from PySide6.QtCore import Signal


class ParameterPanel(QWidget):
    """Panel for specifying component parameters."""

    add_component = Signal(object, dict)  # (RegistryEntry, parameters)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.current_entry = None
        self.param_widgets = {}

        layout = QVBoxLayout(self)

        self.group_box = QGroupBox("Component Parameters")
        self.form_layout = QFormLayout()
        self.group_box.setLayout(self.form_layout)
        layout.addWidget(self.group_box)

        self.selected_label = QLabel("No component selected")
        self.selected_label.setStyleSheet("font-weight: bold; color: #555;")
        self.selected_label.setWordWrap(True)
        self.form_layout.addRow("Selected:", self.selected_label)

        self.add_button = QPushButton("Add to Chain")
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self._on_add_clicked)
        layout.addWidget(self.add_button)

        layout.addStretch()

    def set_component(self, entry):
        """Configure parameter inputs for the selected registry entry."""
        self.current_entry = entry
        self.param_widgets = {}

        while self.form_layout.rowCount() > 1:
            self.form_layout.removeRow(1)

        self.selected_label.setText(entry.label)

        if not entry.params:
            info_label = QLabel("(No parameters required)")
            info_label.setStyleSheet("color: #777; font-style: italic;")
            self.form_layout.addRow(info_label)
            self.add_button.setEnabled(True)
            return

        for spec in entry.params:
            widget = self._create_widget(spec)
            self.param_widgets[spec.name] = widget
            label = spec.display_label
            if spec.unit:
                label = f"{label} ({spec.unit})"
            self.form_layout.addRow(f"{label}:", widget)
            if spec.help:
                widget.setToolTip(spec.help)

        self.add_button.setEnabled(True)

    def _create_widget(self, spec):
        """Create the input widget a parameter spec calls for."""
        if spec.choices:
            widget = QComboBox()
            for choice in spec.choices:
                widget.addItem(f"{choice:g}" if isinstance(choice, (int, float))
                               else str(choice), choice)
            if spec.default is not None:
                index = widget.findData(spec.default)
                if index >= 0:
                    widget.setCurrentIndex(index)
            return widget

        if spec.kind == "bool":
            widget = QCheckBox()
            widget.setChecked(bool(spec.default))
            return widget

        if spec.kind in ("float", "int"):
            widget = QDoubleSpinBox() if spec.kind == "float" else QSpinBox()
            low = spec.minimum if spec.minimum is not None else -1e9
            high = spec.maximum if spec.maximum is not None else 1e9
            widget.setRange(low, high)
            if spec.step is not None:
                widget.setSingleStep(spec.step)
            if isinstance(widget, QDoubleSpinBox):
                widget.setDecimals(3)
            if spec.default is not None:
                widget.setValue(spec.default)
            if spec.unit:
                widget.setSuffix(f" {spec.unit}")
            return widget

        widget = QLineEdit()
        if spec.default is not None:
            widget.setText(str(spec.default))
        return widget

    def _read_widget(self, spec, widget):
        """Read a value back out in the parameter's declared type."""
        if isinstance(widget, QComboBox):
            return widget.currentData()
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, (QDoubleSpinBox, QSpinBox)):
            return widget.value()
        return spec.coerce(widget.text())

    def _on_add_clicked(self):
        """Emit the entry plus the collected parameter values."""
        if not self.current_entry:
            return

        params = {}
        for spec in self.current_entry.params:
            widget = self.param_widgets.get(spec.name)
            if widget is not None:
                params[spec.name] = self._read_widget(spec, widget)

        self.add_component.emit(self.current_entry, params)
