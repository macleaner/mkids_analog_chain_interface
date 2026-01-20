"""
Noise Analysis Dialog

Dialog for analyzing noise spectrum at a given carrier frequency.
"""

import numpy as np
import matplotlib
matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QPushButton, QDoubleSpinBox, QSpinBox, QComboBox, QCheckBox, QLabel,
    QMessageBox, QFileDialog
)


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
