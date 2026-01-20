"""
Summary Display Dialog

Dialog for displaying chain summary with save functionality.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QMessageBox, QFileDialog, QApplication
)


class SummaryDisplayDialog(QDialog):
    """
    Dialog for displaying chain summary with save functionality.
    """
    
    def __init__(self, chain, parent=None):
        super().__init__(parent)
        
        self.chain = chain
        self.setWindowTitle("Chain Summary")
        self.setGeometry(200, 200, 800, 600)
        
        layout = QVBoxLayout(self)
        
        # Title
        title_label = QLabel("Signal Chain Summary")
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title_label)
        
        # Text display area
        self.text_display = QTextEdit()
        self.text_display.setReadOnly(True)
        self.text_display.setFont(QApplication.font())
        self.text_display.setStyleSheet("font-family: monospace; padding: 10px;")
        layout.addWidget(self.text_display)
        
        # Generate summary
        self._generate_summary()
        
        # Action buttons
        button_layout = QHBoxLayout()
        
        save_button = QPushButton("Save Summary")
        save_button.clicked.connect(self._save_summary)
        button_layout.addWidget(save_button)
        
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        button_layout.addWidget(close_button)
        
        layout.addLayout(button_layout)
        
    def _generate_summary(self):
        """Generate summary text."""
        try:
            # Build summary text
            summary = f"Signal Chain: {self.chain.name}\n"
            summary += f"Total components: {len(self.chain)}\n\n"
            summary += "Component List:\n"
            summary += "=" * 80 + "\n"
            
            for idx, component in enumerate(self.chain.components):
                comp_name = component.__class__.__name__
                label = self.chain._get_label_for_index(idx)
                comp_type = getattr(component, 'component_type', 'unknown')
                
                summary += f"  [{idx:2d}] {label}\n"
                summary += f"       Type: {comp_type}\n"
                
                # Add relevant parameters
                if hasattr(component, 'temperature'):
                    summary += f"       Temperature: {component.temperature} K\n"
                if hasattr(component, 'length'):
                    summary += f"       Length: {component.length} m\n"
                if hasattr(component, 'attenuation'):
                    summary += f"       Attenuation: {component.attenuation} dB\n"
                
                summary += "\n"
            
            summary += "=" * 80 + "\n"
            
            # Add gain calculation at a reference frequency
            ref_freq = 1e9  # 1 GHz
            try:
                total_gain = self.chain.total_gain(ref_freq)
                summary += f"\nTotal Gain @ {ref_freq/1e9:.2f} GHz: {total_gain:+.2f} dB\n"
            except Exception as e:
                summary += f"\nTotal Gain calculation: Error - {str(e)}\n"
            
            # Add noise calculation
            try:
                spectral_freq = 1e3  # 1 kHz
                output_noise = self.chain.output_noise(ref_freq, spectral_freq)
                summary += f"Output Noise @ {ref_freq/1e9:.2f} GHz ({spectral_freq/1e3:.1f} kHz offset): {output_noise:.2e} W/Hz\n"
            except Exception as e:
                summary += f"Output Noise calculation: Error - {str(e)}\n"
            
            self.text_display.setPlainText(summary)
            
        except Exception as e:
            self.text_display.setPlainText(f"Error generating summary:\n{str(e)}")
    
    def _save_summary(self):
        """Save the summary to a text file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Summary", "chain_summary.txt", 
            "Text Files (*.txt);;All Files (*)"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'w') as f:
                f.write(self.text_display.toPlainText())
            
            QMessageBox.information(self, "Success", f"Summary saved to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save summary:\n{str(e)}")
