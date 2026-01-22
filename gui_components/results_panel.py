"""
Results Panel

Embeddable widget for displaying gain and noise analysis results.
"""

import numpy as np
import matplotlib
matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QPushButton, QDoubleSpinBox, QSpinBox, QComboBox, QCheckBox, QLabel,
    QMessageBox, QFileDialog
)


class ResultsPanel(QWidget):
    """
    Embeddable widget for displaying both gain and noise analysis results.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.chain = None
        self.freq_data = None
        self.gain_data = None
        self.spectral_freq_data = None
        self.noise_data = None
        self.contributions_data = None
        
        self._setup_ui()
        
    def _setup_ui(self):
        """Set up the UI layout."""
        # Main horizontal layout: parameters on left, plots on right
        main_layout = QHBoxLayout(self)
        
        # Left side: Parameter controls
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        # Parameter input section
        param_group = QGroupBox("Analysis Parameters")
        param_layout = QFormLayout()
        
        # Gain Analysis Parameters
        gain_label = QLabel("<b>Gain Analysis:</b>")
        param_layout.addRow(gain_label)
        
        self.gain_start_freq_spin = QDoubleSpinBox()
        self.gain_start_freq_spin.setRange(0.001, 1000)
        self.gain_start_freq_spin.setValue(0.1)
        self.gain_start_freq_spin.setSuffix(" GHz")
        self.gain_start_freq_spin.setDecimals(3)
        param_layout.addRow("  Start Freq:", self.gain_start_freq_spin)
        
        self.gain_stop_freq_spin = QDoubleSpinBox()
        self.gain_stop_freq_spin.setRange(0.001, 1000)
        self.gain_stop_freq_spin.setValue(3.0)
        self.gain_stop_freq_spin.setSuffix(" GHz")
        self.gain_stop_freq_spin.setDecimals(3)
        param_layout.addRow("  Stop Freq:", self.gain_stop_freq_spin)
        
        # Noise Analysis Parameters
        noise_label = QLabel("<b>Noise Analysis:</b>")
        param_layout.addRow(noise_label)
        
        self.carrier_freq_spin = QDoubleSpinBox()
        self.carrier_freq_spin.setRange(0.001, 1000)
        self.carrier_freq_spin.setValue(1.0)
        self.carrier_freq_spin.setSuffix(" GHz")
        self.carrier_freq_spin.setDecimals(3)
        param_layout.addRow("  Carrier Freq:", self.carrier_freq_spin)
        
        self.start_spectral_spin = QDoubleSpinBox()
        self.start_spectral_spin.setRange(0.001, 1e6)
        self.start_spectral_spin.setValue(0.01)
        self.start_spectral_spin.setSuffix(" kHz")
        self.start_spectral_spin.setDecimals(3)
        param_layout.addRow("  Start Offset:", self.start_spectral_spin)
        
        self.stop_spectral_spin = QDoubleSpinBox()
        self.stop_spectral_spin.setRange(0.001, 1e6)
        self.stop_spectral_spin.setValue(100.0)
        self.stop_spectral_spin.setSuffix(" kHz")
        self.stop_spectral_spin.setDecimals(3)
        param_layout.addRow("  Stop Offset:", self.stop_spectral_spin)
        
        # Common Parameters
        common_label = QLabel("<b>Common:</b>")
        param_layout.addRow(common_label)
        
        self.num_points_spin = QSpinBox()
        self.num_points_spin.setRange(10, 10000)
        self.num_points_spin.setValue(100)
        param_layout.addRow("  Number of Points:", self.num_points_spin)
        
        self.spacing_combo = QComboBox()
        self.spacing_combo.addItems(["Logarithmic", "Linear"])
        param_layout.addRow("  Frequency Spacing:", self.spacing_combo)
        
        self.show_contributions_check = QCheckBox("Show Individual Component Contributions (Noise)")
        param_layout.addRow("", self.show_contributions_check)
        
        param_group.setLayout(param_layout)
        left_layout.addWidget(param_group)
        
        # Buttons in left column
        calc_button = QPushButton("Calculate && Plot Both")
        calc_button.clicked.connect(self.calculate_and_plot)
        left_layout.addWidget(calc_button)
        
        export_button = QPushButton("Export Data (CSV)")
        export_button.clicked.connect(self._export_data)
        left_layout.addWidget(export_button)
        
        save_plot_button = QPushButton("Save Plots")
        save_plot_button.clicked.connect(self._save_plots)
        left_layout.addWidget(save_plot_button)
        
        # Results label in left column
        self.results_label = QLabel("")
        self.results_label.setStyleSheet("padding: 5px; background-color: #f0f0f0;")
        self.results_label.setWordWrap(True)
        left_layout.addWidget(self.results_label)
        
        left_layout.addStretch()
        
        # Set a maximum width for the left panel
        left_widget.setMaximumWidth(350)
        
        # Right side: Plots
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # Matplotlib figure with two subplots
        self.figure = Figure(figsize=(10, 8))
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        
        right_layout.addWidget(self.toolbar)
        right_layout.addWidget(self.canvas)
        
        # Add left and right to main layout
        main_layout.addWidget(left_widget)
        main_layout.addWidget(right_widget)
        
        # Show empty state initially
        self._show_empty_state()
        
    def set_chain(self, chain):
        """Set the signal chain to analyze."""
        self.chain = chain
        
    def calculate_and_plot(self):
        """Calculate both gain and noise analyses and plot results."""
        if self.chain is None or len(self.chain.components) == 0:
            self._show_empty_state()
            return
            
        try:
            # Get parameters
            gain_start = self.gain_start_freq_spin.value() * 1e9
            gain_stop = self.gain_stop_freq_spin.value() * 1e9
            carrier_freq = self.carrier_freq_spin.value() * 1e9
            start_spectral = self.start_spectral_spin.value() * 1e3
            stop_spectral = self.stop_spectral_spin.value() * 1e3
            num_points = self.num_points_spin.value()
            is_log = self.spacing_combo.currentText() == "Logarithmic"
            show_contributions = self.show_contributions_check.isChecked()
            
            # Validate parameters
            if gain_start >= gain_stop:
                QMessageBox.warning(self, "Invalid Range", 
                                  "Gain start frequency must be less than stop frequency.")
                return
            if start_spectral >= stop_spectral:
                QMessageBox.warning(self, "Invalid Range", 
                                  "Noise start offset must be less than stop offset.")
                return
            
            # Calculate gain data
            if is_log:
                self.freq_data = np.logspace(np.log10(gain_start), np.log10(gain_stop), num_points)
            else:
                self.freq_data = np.linspace(gain_start, gain_stop, num_points)
            
            self.gain_data = np.array([self.chain.total_gain(f) for f in self.freq_data])
            
            # Calculate noise data
            if is_log:
                self.spectral_freq_data = np.logspace(np.log10(start_spectral), 
                                                     np.log10(stop_spectral), num_points)
            else:
                self.spectral_freq_data = np.linspace(start_spectral, stop_spectral, num_points)
            
            if show_contributions:
                self.noise_data = []
                self.contributions_data = {}
                
                for spectral_freq in self.spectral_freq_data:
                    total_noise, contributions = self.chain.noise_at_point(
                        len(self.chain) - 1, carrier_freq, spectral_freq, contributions=True
                    )
                    self.noise_data.append(total_noise)
                    
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
            
            # Plot both
            self.figure.clear()
            
            # Gain plot (top)
            ax1 = self.figure.add_subplot(2, 1, 1)
            if is_log:
                ax1.semilogx(self.freq_data / 1e9, self.gain_data, 'b-', linewidth=2)
            else:
                ax1.plot(self.freq_data / 1e9, self.gain_data, 'b-', linewidth=2)
            
            ax1.grid(True, alpha=0.3)
            ax1.set_xlabel('Frequency (GHz)', fontsize=11)
            ax1.set_ylabel('Total Gain (dB)', fontsize=11)
            ax1.set_title(f'System Gain vs Frequency: {self.chain.name}', 
                         fontsize=12, fontweight='bold')
            
            # Noise plot (bottom)
            ax2 = self.figure.add_subplot(2, 1, 2)
            if is_log:
                ax2.loglog(self.spectral_freq_data / 1e3, self.noise_data, 
                         'b-', linewidth=2, label='Total Noise')
            else:
                ax2.semilogy(self.spectral_freq_data / 1e3, self.noise_data, 
                           'b-', linewidth=2, label='Total Noise')
            
            # Plot individual contributions if requested
            if show_contributions and self.contributions_data:
                for label, noise_vals in self.contributions_data.items():
                    if is_log:
                        ax2.loglog(self.spectral_freq_data / 1e3, noise_vals, 
                                 '--', alpha=0.6, linewidth=1.5, label=label)
                    else:
                        ax2.semilogy(self.spectral_freq_data / 1e3, noise_vals, 
                                   '--', alpha=0.6, linewidth=1.5, label=label)
                ax2.legend(fontsize=8, loc='best')
            
            ax2.grid(True, alpha=0.3)
            ax2.set_xlabel('Offset Frequency (kHz)', fontsize=11)
            ax2.set_ylabel('Noise PSD (W/Hz)', fontsize=11)
            ax2.set_title(f'Output Noise Spectrum at {carrier_freq/1e9:.2f} GHz Carrier', 
                        fontsize=12, fontweight='bold')
            
            self.figure.tight_layout()
            self.canvas.draw()
            
            # Update results summary
            min_gain = np.min(self.gain_data)
            max_gain = np.max(self.gain_data)
            min_freq = self.freq_data[np.argmin(self.gain_data)] / 1e9
            max_freq = self.freq_data[np.argmax(self.gain_data)] / 1e9
            
            min_noise = np.min(self.noise_data)
            max_noise = np.max(self.noise_data)
            avg_noise = np.mean(self.noise_data)
            
            results_text = (f"<b>Gain:</b> Min={min_gain:.2f} dB @ {min_freq:.3f} GHz  |  "
                          f"Max={max_gain:.2f} dB @ {max_freq:.3f} GHz<br>"
                          f"<b>Noise:</b> Min={min_noise:.2e} W/Hz  |  "
                          f"Max={max_noise:.2e} W/Hz  |  Avg={avg_noise:.2e} W/Hz")
            self.results_label.setText(results_text)
            
        except Exception as e:
            QMessageBox.critical(self, "Calculation Error", 
                               f"Failed to calculate results:\n{str(e)}")
    
    def _show_empty_state(self):
        """Show empty state message."""
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        ax.axis('off')
        ax.text(5, 5, "Add components to the chain and click\n'Calculate & Plot Both' to see analysis results here.",
                ha='center', va='center', fontsize=12, style='italic', color='gray')
        self.canvas.draw()
        self.results_label.setText("")
    
    def _export_data(self):
        """Export both gain and noise data to CSV files."""
        if self.freq_data is None or self.gain_data is None:
            QMessageBox.warning(self, "No Data", "Please calculate results first.")
            return
        
        # Export gain data
        gain_file, _ = QFileDialog.getSaveFileName(
            self, "Export Gain Data", "gain_analysis.csv", "CSV Files (*.csv)"
        )
        
        if gain_file:
            try:
                with open(gain_file, 'w') as f:
                    f.write("Frequency_Hz,Frequency_GHz,Gain_dB\n")
                    for freq, gain in zip(self.freq_data, self.gain_data):
                        f.write(f"{freq},{freq/1e9},{gain}\n")
                QMessageBox.information(self, "Success", f"Gain data exported to:\n{gain_file}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export gain data:\n{str(e)}")
        
        # Export noise data
        noise_file, _ = QFileDialog.getSaveFileName(
            self, "Export Noise Data", "noise_analysis.csv", "CSV Files (*.csv)"
        )
        
        if noise_file:
            try:
                with open(noise_file, 'w') as f:
                    header = "Spectral_Freq_Hz,Spectral_Freq_kHz,Total_Noise_W_per_Hz"
                    if self.contributions_data:
                        for label in self.contributions_data.keys():
                            header += f",{label}_W_per_Hz"
                    f.write(header + "\n")
                    
                    for i, (spectral_freq, noise) in enumerate(zip(self.spectral_freq_data, self.noise_data)):
                        row = f"{spectral_freq},{spectral_freq/1e3},{noise}"
                        if self.contributions_data:
                            for label in self.contributions_data.keys():
                                row += f",{self.contributions_data[label][i]}"
                        f.write(row + "\n")
                
                QMessageBox.information(self, "Success", f"Noise data exported to:\n{noise_file}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export noise data:\n{str(e)}")
    
    def _save_plots(self):
        """Save the current plots."""
        if self.freq_data is None or self.gain_data is None:
            QMessageBox.warning(self, "No Plots", "Please calculate results first.")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Plots", "analysis_results.png", 
            "PNG Files (*.png);;PDF Files (*.pdf);;SVG Files (*.svg)"
        )
        
        if not file_path:
            return
        
        try:
            self.figure.savefig(file_path, dpi=300, bbox_inches='tight')
            QMessageBox.information(self, "Success", f"Plots saved to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save plots:\n{str(e)}")
