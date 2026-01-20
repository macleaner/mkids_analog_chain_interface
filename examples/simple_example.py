"""
Simple example demonstrating the RF signal chain analysis tool.

This script builds a basic signal chain and analyzes its performance.
"""

import sys
import os
# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from signal_chain import SignalChain
from hardware_models import (
    Attenuator, ZX60_3018Gplus, ASU_3GHz_LNA, 
    SMA_FM_F141_cables, SMA_SS086_cryo
)
from diagram_generator import DiagramGenerator


def main():
    """Build and analyze a simple RF signal chain."""
    
    print("=" * 70)
    print("RF Signal Chain Analysis - Simple Example")
    print("=" * 70)
    
    # Create a new signal chain
    chain = SignalChain(name="Simple Cryogenic System")
    
    # Build the chain: Room temp → Cryostat → Amplifier → Room temp
    
    # Input side (room temperature)
    chain.add_component(Attenuator(-10, 300), label="InputAtten")
    chain.add_component(SMA_FM_F141_cables(2.0), label="WarmCable_In")
    
    # Cryogenic section
    chain.add_component(SMA_SS086_cryo(0.5, temperature=4), label="CryoCable")
    chain.add_component(Attenuator(-20, 4), label="ColdAtten")
    
    # Output side (starting with cold amplifier)
    chain.add_component(ASU_3GHz_LNA(), label="LNA")
    chain.add_component(SMA_SS086_cryo(0.5, temperature=50), label="ReturnCable")
    
    # Room temperature amplification
    chain.add_component(ZX60_3018Gplus(), label="WarmAmp1")
    chain.add_component(ZX60_3018Gplus(), label="WarmAmp2")
    
    # Print chain summary
    print("\n")
    chain.summary()
    
    # Analyze at a specific frequency
    freq = 1.5e9  # 1.5 GHz
    print(f"\n{'=' * 70}")
    print(f"Analysis at {freq/1e9:.2f} GHz")
    print(f"{'=' * 70}")
    
    # Calculate gains between different points
    print("\n--- Gain Analysis ---")
    
    input_loss = chain.gain_between("InputAtten", "ColdAtten", freq)
    print(f"Input path loss (to detector): {input_loss:.2f} dB")
    
    lna_gain = chain.gain_between("LNA", "LNA", freq)
    print(f"LNA gain: {lna_gain:+.2f} dB")
    
    output_gain = chain.gain_between("LNA", "WarmAmp2", freq)
    print(f"Output path gain (from LNA): {output_gain:+.2f} dB")
    
    total_gain = chain.total_gain(freq)
    print(f"Total system gain: {total_gain:+.2f} dB")
    
    # Calculate noise at different points
    print("\n--- Noise Analysis ---")
    
    # For noise analysis, we need both carrier and spectral frequencies
    # Carrier frequency: the RF carrier (1.5 GHz in this case)
    # Spectral frequency: the offset frequency for noise spectrum (e.g., 1 kHz for phase noise)
    spectral_freq = 1e3  # 1 kHz offset for noise analysis
    
    noise_at_detector = chain.noise_at_point("ColdAtten", freq, spectral_freq)
    print(f"Noise at detector (cold attenuator) at {spectral_freq/1e3:.1f} kHz offset: {noise_at_detector:.2e} W/Hz")
    
    noise_at_lna = chain.noise_at_point("LNA", freq, spectral_freq)
    print(f"Noise at LNA output at {spectral_freq/1e3:.1f} kHz offset: {noise_at_lna:.2e} W/Hz")
    
    noise_at_output = chain.output_noise(freq, spectral_freq)
    print(f"Noise at system output at {spectral_freq/1e3:.1f} kHz offset: {noise_at_output:.2e} W/Hz")
    
    # Show individual noise contributions at output
    print("\n--- Noise Contributors at Output ---")
    total_noise, contributions = chain.noise_at_point("WarmAmp2", freq, spectral_freq, contributions=True)
    
    # Sort by contribution magnitude
    sorted_contrib = sorted(contributions.items(), key=lambda x: x[1], reverse=True)
    
    for label, noise_power in sorted_contrib:
        percentage = 100 * noise_power / total_noise
        print(f"  {label:20s}: {noise_power:.2e} W/Hz ({percentage:.1f}%)")
    
    # Frequency sweep
    print(f"\n{'=' * 70}")
    print("Frequency Sweep Analysis")
    print(f"{'=' * 70}\n")
    
    frequencies = np.logspace(8, 9.5, 20)  # 100 MHz to 3 GHz
    spectral_freq = 1e3  # 1 kHz offset
    print(f"{'Freq (GHz)':>12} {'Gain (dB)':>12} {'Noise (W/Hz)':>15}")
    print(f"(Noise measured at {spectral_freq/1e3:.1f} kHz spectral offset)")
    print("-" * 42)
    
    for f in frequencies:
        gain = chain.total_gain(f)
        noise = chain.output_noise(f, spectral_freq)
        print(f"{f/1e9:12.3f} {gain:12.2f} {noise:15.2e}")
    
    # Generate diagrams
    print(f"\n{'=' * 70}")
    print("Generating Diagrams")
    print(f"{'=' * 70}\n")
    
    diagram_gen = DiagramGenerator(chain)
    
    # Simple block diagram
    output_dir = os.path.dirname(os.path.abspath(__file__))
    
    print("Creating simple block diagram...")
    diagram_gen.generate(
        filename=os.path.join(output_dir, "simple_chain_diagram.pdf"),
        frequency=freq,
        show_gain=True,
        show_noise=True
    )
    
    print("Creating detailed diagram with plots...")
    diagram_gen.generate_detailed(
        filename=os.path.join(output_dir, "simple_chain_detailed.pdf"),
        frequency_range=np.logspace(8, 9.5, 100)
    )
    
    print(f"\n{'=' * 70}")
    print("Analysis Complete!")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
