"""
Noise Budget Panel

Shows every noise source in the chain referred to one reference plane, with
each source's own noise, the gain applied to refer it to that plane, and the
result in both power and equivalent temperature.

The referral gain column is the point of the view: it makes visible why a source
matters, e.g. an ADC that is negligible at the chain output but dominant when
referred back to a cryogenic LNA input through insufficient gain.
"""

import csv

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout, QLabel,
    QComboBox, QDoubleSpinBox, QPushButton, QPlainTextEdit, QFileDialog,
    QMessageBox
)
from PySide6.QtGui import QFont

from noise_budget import DEFAULT_POWER_UNIT, POWER_UNITS


class BudgetPanel(QWidget):
    """Panel presenting a noise budget at a selectable reference plane."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.chain = None
        self.budget = None

        main_layout = QHBoxLayout(self)

        # ---- Controls -------------------------------------------------
        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls.setMaximumWidth(320)

        group = QGroupBox("Reference Plane")
        form = QFormLayout()

        self.point_combo = QComboBox()
        self.point_combo.setToolTip(
            "The component to refer all noise sources to.")
        form.addRow("Point:", self.point_combo)

        self.side_combo = QComboBox()
        self.side_combo.addItem("Input", "input")
        self.side_combo.addItem("Output", "output")
        self.side_combo.setToolTip(
            "Input and output differ by that component's gain, which for an "
            "amplifier is tens of dB.")
        form.addRow("Side:", self.side_combo)

        self.carrier_spin = QDoubleSpinBox()
        self.carrier_spin.setRange(0.001, 100.0)
        self.carrier_spin.setValue(1.5)
        self.carrier_spin.setDecimals(4)
        self.carrier_spin.setSuffix(" GHz")
        form.addRow("Carrier:", self.carrier_spin)

        self.spectral_spin = QDoubleSpinBox()
        self.spectral_spin.setRange(0.001, 1e9)
        self.spectral_spin.setValue(1000.0)
        self.spectral_spin.setDecimals(3)
        self.spectral_spin.setSuffix(" Hz")
        self.spectral_spin.setToolTip(
            "Spectral (audio) frequency: the offset from the carrier at "
            "which noise is evaluated.")
        form.addRow("Spectral freq:", self.spectral_spin)

        self.unit_combo = QComboBox()
        for unit in POWER_UNITS:
            self.unit_combo.addItem(unit, unit)
        self.unit_combo.setCurrentIndex(
            self.unit_combo.findData(DEFAULT_POWER_UNIT))
        self.unit_combo.setToolTip(
            "Display unit for noise powers. dBm/Hz is easier to read; W/Hz is "
            "the underlying unit. Temperatures are always in K.")
        # Re-render immediately - no need to recompute, only reformat.
        self.unit_combo.currentIndexChanged.connect(self._render)
        form.addRow("Units:", self.unit_combo)

        group.setLayout(form)
        controls_layout.addWidget(group)

        compute_button = QPushButton("Compute Budget")
        compute_button.clicked.connect(self.compute)
        controls_layout.addWidget(compute_button)

        self.export_button = QPushButton("Export CSV...")
        self.export_button.clicked.connect(self._export_csv)
        self.export_button.setEnabled(False)
        controls_layout.addWidget(self.export_button)

        self.summary_label = QLabel("No budget computed.")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("color: #555;")
        controls_layout.addWidget(self.summary_label)

        controls_layout.addStretch()

        # ---- Table ----------------------------------------------------
        self.table_view = QPlainTextEdit()
        self.table_view.setReadOnly(True)
        font = QFont("Monospace")
        font.setStyleHint(QFont.TypeWriter)
        self.table_view.setFont(font)
        self.table_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.table_view.setPlaceholderText(
            "Build a chain, then compute a budget to see which source dominates "
            "at a given point and how the intervening gains got it there."
        )

        main_layout.addWidget(controls)
        main_layout.addWidget(self.table_view, stretch=1)

    def set_chain(self, chain):
        """Point the panel at a chain and refresh the reference-point list."""
        self.chain = chain
        self._refresh_points()

    def _refresh_points(self):
        """Repopulate the reference-point choices from the chain's stages."""
        previous = self.point_combo.currentData()
        self.point_combo.clear()
        if self.chain is None:
            return
        for label, _, kind in self.chain.stages():
            suffix = {"dac": "  (DAC)", "adc": "  (ADC)"}.get(kind, "")
            self.point_combo.addItem(f"{label}{suffix}", label)
        if previous is not None:
            index = self.point_combo.findData(previous)
            if index >= 0:
                self.point_combo.setCurrentIndex(index)

    def compute(self):
        """Build and display the budget for the selected plane."""
        if self.chain is None or not self.chain.components:
            self.table_view.setPlainText("Add components to the chain first.")
            return

        self._refresh_points()
        point = self.point_combo.currentData()
        if point is None:
            return

        carrier = self.carrier_spin.value() * 1e9
        spectral = self.spectral_spin.value()

        try:
            self.budget = self.chain.noise_budget(
                point, carrier, spectral, at=self.side_combo.currentData())
        except (KeyError, ValueError, TypeError) as exc:
            self.budget = None
            self.export_button.setEnabled(False)
            QMessageBox.warning(self, "Cannot compute budget", str(exc))
            return

        self._render()

    def current_unit(self):
        """The selected display unit for noise powers."""
        return self.unit_combo.currentData() or DEFAULT_POWER_UNIT

    def _render(self):
        """Format the existing budget in the selected unit."""
        if self.budget is None:
            return

        unit = self.current_unit()
        self.table_view.setPlainText(self.budget.table(unit))
        self.export_button.setEnabled(True)

        dominant = self.budget.dominant()
        if dominant is None:
            self.summary_label.setText("No noise sources in this chain.")
            return

        if unit == "dBm/Hz":
            total_text = f"{float(self.budget.total_dbm_per_hz):.2f} dBm/Hz"
        else:
            total_text = f"{float(self.budget.total_w):.3e} W/Hz"
        self.summary_label.setText(
            f"Total {total_text} "
            f"({float(self.budget.total_k):.1f} K equivalent).\n\n"
            f"Dominated by {dominant.label} at "
            f"{100 * float(self.budget.fraction(dominant)):.1f}%."
        )

    def _export_csv(self):
        """Write the budget rows, including the referral gains, to CSV."""
        if self.budget is None:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Noise Budget", "", "CSV Files (*.csv)")
        if not file_path:
            return
        if not file_path.lower().endswith(".csv"):
            file_path += ".csv"

        rows = self.budget.to_rows()
        try:
            with open(file_path, "w", newline="") as fh:
                # Provenance first, so the numbers stay interpretable later.
                fh.write(f"# chain,{self.chain.name}\n")
                fh.write(f"# reference_plane,{self.budget.reference}\n")
                fh.write(f"# carrier_Hz,{float(self.budget.carrier_hz)}\n")
                fh.write(f"# spectral_Hz,{float(self.budget.spectral_hz)}\n")
                fh.write(f"# total_W_per_Hz,{float(self.budget.total_w)}\n")
                fh.write(f"# total_dBm_per_Hz,{float(self.budget.total_dbm_per_hz)}\n")
                fh.write(f"# total_K,{float(self.budget.total_k)}\n")
                writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
                writer.writeheader()
                for row in rows:
                    writer.writerow({k: float(v) if not isinstance(v, str) else v
                                     for k, v in row.items()})
        except OSError as exc:
            QMessageBox.critical(self, "Error", f"Failed to export:\n{exc}")
            return

        self.summary_label.setText(f"Exported to {file_path}")
