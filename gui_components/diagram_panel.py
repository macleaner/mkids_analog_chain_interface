"""
Diagram Panel

Embeddable widget for displaying signal chain diagrams.
"""

import matplotlib
matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QPushButton, QDoubleSpinBox, QCheckBox, QMessageBox, QFileDialog, QLabel
)
from PySide6.QtCore import Qt


class DiagramPanel(QWidget):
    """
    Embeddable widget for displaying signal chain diagrams.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.chain = None
        self._setup_ui()
        
    def _setup_ui(self):
        """Set up the UI layout."""
        # Main horizontal layout: parameters on left, diagram on right
        main_layout = QHBoxLayout(self)
        
        # Left side: Parameter controls
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
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
        left_layout.addWidget(param_group)
        
        # Buttons in left column
        generate_button = QPushButton("Generate Diagram")
        generate_button.clicked.connect(self.generate_diagram)
        left_layout.addWidget(generate_button)
        
        save_button = QPushButton("Save Diagram")
        save_button.clicked.connect(self._save_diagram)
        left_layout.addWidget(save_button)
        
        left_layout.addStretch()
        
        # Set a maximum width for the left panel
        left_widget.setMaximumWidth(350)
        
        # Right side: Diagram
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # Matplotlib figure
        self.figure = Figure(figsize=(10, 5))
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
        """Set the signal chain to display."""
        self.chain = chain
        
    def generate_diagram(self):
        """Generate and display the diagram."""
        if self.chain is None or len(self.chain.components) == 0:
            self._show_empty_state()
            return
            
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
    
    def _show_empty_state(self):
        """Show empty state message."""
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        ax.axis('off')
        ax.text(5, 5, "Add components to the chain and click\n'Generate Diagram' to see the chain diagram here.",
                ha='center', va='center', fontsize=12, style='italic', color='gray')
        self.canvas.draw()
    
    def _save_diagram(self):
        """Save the current diagram."""
        if self.chain is None or len(self.chain.components) == 0:
            QMessageBox.warning(self, "No Diagram", "Please generate a diagram first.")
            return
            
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
