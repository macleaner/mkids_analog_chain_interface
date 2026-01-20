"""
Diagram Display Dialog

Dialog for displaying generated signal chain diagrams with save functionality.
"""

import matplotlib
matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QPushButton, QDoubleSpinBox, QCheckBox, QMessageBox, QFileDialog
)


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
