"""
Diagram generation for RF signal chains.

Creates visual block diagrams showing components and signal flow.
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np


class DiagramGenerator:
    """
    Generate block diagrams of signal chains.
    """
    
    def __init__(self, signal_chain):
        """
        Initialize diagram generator for a signal chain.
        
        Parameters
        ----------
        signal_chain : SignalChain
            The signal chain to visualize
        """
        self.chain = signal_chain
        
    def generate(self, filename=None, frequency=None, spectral_frequency=1e3, 
                 show_gain=True, show_noise=False, figsize=(12, 6), dpi=150):
        """
        Generate a block diagram of the signal chain.
        
        Parameters
        ----------
        filename : str, optional
            Output filename (PDF, PNG, or SVG). If None, display interactively.
        frequency : float, optional
            Carrier frequency (Hz) to evaluate gain/noise at. Required if show_gain or show_noise is True.
        spectral_frequency : float, optional
            Spectral/offset frequency (Hz) for noise analysis. Default: 1 kHz
        show_gain : bool
            Show gain values on components
        show_noise : bool
            Show noise contributions
        figsize : tuple
            Figure size (width, height) in inches
        dpi : int
            Resolution for raster outputs
        """
        if (show_gain or show_noise) and frequency is None:
            raise ValueError("frequency parameter required when show_gain or show_noise is True")
        
        fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
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
            if filename:
                plt.savefig(filename, bbox_inches='tight')
                plt.close()
            else:
                plt.tight_layout()
                plt.show()
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
        if show_gain and frequency is not None:
            total_gain = self.chain.total_gain(frequency)
            ax.text(5, 1.5, f"Total Gain: {total_gain:+.1f} dB @ {frequency/1e9:.3f} GHz",
                    ha='center', va='center', fontsize=10, 
                    bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
        
        if show_noise and frequency is not None:
            total_noise = self.chain.output_noise(frequency, spectral_frequency)
            ax.text(5, 0.8, f"Output Noise: {total_noise:.2e} W/Hz @ {frequency/1e9:.3f} GHz (offset: {spectral_frequency/1e3:.1f} kHz)",
                    ha='center', va='center', fontsize=9,
                    bbox=dict(boxstyle='round', facecolor='lightcoral', alpha=0.5))
        
        # Save or show
        if filename:
            plt.savefig(filename, bbox_inches='tight', dpi=dpi)
            print(f"Diagram saved to: {filename}")
            plt.close()
        else:
            plt.tight_layout()
            plt.show()
    
    def generate_detailed(self, filename=None, frequency_range=None, 
                         spectral_frequency=1e3, spectral_range=None,
                         carrier_for_spectrum=None, figsize=(14, 12), dpi=150):
        """
        Generate a detailed diagram with gain and noise plots.
        
        Parameters
        ----------
        filename : str, optional
            Output filename
        frequency_range : array-like, optional
            Carrier frequency range in Hz for plotting. Default: 100 MHz to 3 GHz
        spectral_frequency : float, optional
            Spectral/offset frequency (Hz) for noise vs carrier freq plot. Default: 1 kHz
        spectral_range : array-like, optional
            Spectral/offset frequency range in Hz for noise spectrum plot. 
            Default: 0.01 kHz to 10 kHz
        carrier_for_spectrum : float, optional
            Carrier frequency (Hz) to use for noise spectrum plot.
            Default: middle of frequency_range
        figsize : tuple
            Figure size
        dpi : int
            Resolution
        """
        if frequency_range is None:
            frequency_range = np.logspace(8, 9.5, 100)  # 100 MHz to 3 GHz
        
        if spectral_range is None:
            spectral_range = np.logspace(1, 4, 100)  # 10 Hz to 10 kHz
        
        if carrier_for_spectrum is None:
            # Use middle of the carrier frequency range
            carrier_for_spectrum = np.sqrt(frequency_range[0] * frequency_range[-1])
        
        fig = plt.figure(figsize=figsize, dpi=dpi)
        gs = fig.add_gridspec(4, 1, height_ratios=[1, 1.2, 1.2, 1.2], hspace=0.35)
        
        # Top: Block diagram
        ax_diagram = fig.add_subplot(gs[0])
        ax_diagram.set_xlim(0, 10)
        ax_diagram.set_ylim(0, 3)
        ax_diagram.axis('off')
        ax_diagram.text(5, 2.5, self.chain.name, ha='center', va='top',
                        fontsize=14, fontweight='bold')
        
        # Draw simplified component blocks
        n_components = len(self.chain.components)
        if n_components > 0:
            spacing = 8.0 / max(n_components, 1)
            for idx, component in enumerate(self.chain.components):
                x = 1.0 + idx * spacing
                label = self.chain._get_label_for_index(idx)
                short_label = label[:10] + "..." if len(label) > 10 else label
                
                comp_type = getattr(component, 'component_type', 'generic')
                color = '#90EE90' if comp_type == 'active' else '#ADD8E6'
                
                box = FancyBboxPatch((x - 0.3, 0.5), 0.6, 0.8,
                                     boxstyle="round,pad=0.05",
                                     edgecolor='black', facecolor=color, linewidth=1)
                ax_diagram.add_patch(box)
                ax_diagram.text(x, 0.9, short_label, ha='center', va='center',
                                fontsize=6)
                
                if idx < n_components - 1:
                    arrow = FancyArrowPatch((x + 0.3, 0.9), (x + spacing - 0.3, 0.9),
                                           arrowstyle='->', color='black', linewidth=1.5)
                    ax_diagram.add_patch(arrow)
        
        # Middle: Gain plot
        ax_gain = fig.add_subplot(gs[1])
        gains = [self.chain.total_gain(f) for f in frequency_range]
        ax_gain.semilogx(frequency_range / 1e9, gains, 'b-', linewidth=2)
        ax_gain.grid(True, alpha=0.3)
        ax_gain.set_xlabel('Frequency (GHz)', fontsize=10)
        ax_gain.set_ylabel('Total Gain (dB)', fontsize=10)
        ax_gain.set_title('Frequency Response', fontsize=11, fontweight='bold')
        
        # Third: Noise vs carrier frequency plot
        ax_noise = fig.add_subplot(gs[2])
        noise = [self.chain.output_noise(f, spectral_frequency) for f in frequency_range]
        ax_noise.loglog(frequency_range / 1e9, noise, 'r-', linewidth=2)
        ax_noise.grid(True, alpha=0.3)
        ax_noise.set_xlabel('Carrier Frequency (GHz)', fontsize=10)
        ax_noise.set_ylabel('Output Noise PSD (W/Hz)', fontsize=10)
        ax_noise.set_title(f'Output Noise vs Carrier Frequency (at {spectral_frequency/1e3:.1f} kHz spectral offset)', 
                          fontsize=11, fontweight='bold')
        
        # Fourth: Noise spectrum within carrier bandwidth
        ax_spectrum = fig.add_subplot(gs[3])
        noise_spectrum = [self.chain.output_noise(carrier_for_spectrum, f) for f in spectral_range]
        ax_spectrum.loglog(spectral_range / 1e3, noise_spectrum, 'purple', linewidth=2)
        ax_spectrum.grid(True, alpha=0.3)
        ax_spectrum.set_xlabel('Spectral/Offset Frequency (kHz)', fontsize=10)
        ax_spectrum.set_ylabel('Output Noise PSD (W/Hz)', fontsize=10)
        ax_spectrum.set_title(f'Noise Spectrum at {carrier_for_spectrum/1e9:.2f} GHz Carrier', 
                             fontsize=11, fontweight='bold')
        
        if filename:
            plt.savefig(filename, bbox_inches='tight', dpi=dpi)
            print(f"Detailed diagram saved to: {filename}")
            plt.close()
        else:
            plt.tight_layout()
            plt.show()
