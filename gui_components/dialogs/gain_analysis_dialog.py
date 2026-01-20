"""
Gain Analysis Dialog

Dialog for analyzing system gain as a function of carrier frequency.
"""

import numpy as np
import matplotlib
matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QPushButton, QDoubleSpinBox, QSpinBox, QComboBox, QLabel,
    QMessageBox, QFileDialog
)


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
