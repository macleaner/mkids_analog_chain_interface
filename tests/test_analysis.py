"""
Analysis-path tests: vectorization, error surfacing, and the one place where
the two noise methods disagree.
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import registry  # noqa: E402
from signal_chain import SignalChain  # noqa: E402


def test_output_noise_accepts_an_array_of_offset_frequencies(sample_chain):
    """
    Frequency sweeps used to raise ValueError from a scalar truth test on an
    array, forcing callers to loop one frequency at a time.
    """
    offsets = np.logspace(0, 5, 25)
    result = sample_chain.output_noise(1.5e9, offsets)
    assert np.shape(result) == offsets.shape
    assert np.all(np.asarray(result) > 0)


def test_noise_at_point_accepts_an_array(sample_chain):
    offsets = np.logspace(0, 5, 25)
    result = sample_chain.noise_at_point("LNA", 1.5e9, offsets)
    assert np.shape(result) == offsets.shape


def test_vectorized_matches_scalar_loop(sample_chain):
    """The vectorized path must agree with the per-frequency loop it replaces."""
    dac = registry.create("converter.ad9082_dac", {"carrier_power_dbm": -20.0})
    adc = registry.create("converter.ad9082_adc", {})
    sample_chain.set_digitizer(dac, adc)

    offsets = np.logspace(0, 5, 17)
    vectorized = np.asarray(sample_chain.output_noise(1.5e9, offsets))
    looped = np.asarray([sample_chain.output_noise(1.5e9, f) for f in offsets])
    assert np.allclose(vectorized, looped, rtol=1e-12)


def test_contributions_sum_to_the_total(sample_chain):
    """A noise budget breakdown has to actually add up."""
    dac = registry.create("converter.ad9082_dac", {"carrier_power_dbm": -20.0})
    adc = registry.create("converter.ad9082_adc", {})
    sample_chain.set_digitizer(dac, adc)

    total, contributions = sample_chain.output_noise(1.5e9, 1e3, contributions=True)
    assert sum(contributions.values()) == pytest.approx(total, rel=1e-12)
    # DAC, ADC, attenuator and LNA all contribute; the cable is noiseless.
    assert set(contributions) == {"AD9082_DAC", "AD9082_ADC", "InputAtten", "LNA"}


def test_total_gain_includes_digitizer(sample_chain):
    before = sample_chain.total_gain(1.5e9)
    sample_chain.set_digitizer(
        registry.create("converter.ad9082_dac", {"gain_db": 2.0}),
        registry.create("converter.ad9082_adc", {"gain_db": 3.0}),
    )
    assert sample_chain.total_gain(1.5e9) == pytest.approx(before + 5.0)


def test_a_failing_noise_model_is_not_silently_treated_as_noiseless():
    """
    The previous implementation wrapped DAC/ADC noise in a bare except, so a
    broken model contributed zero noise with no indication - a plausible but
    wrong answer, the worst outcome for an analysis tool.
    """
    from component import ADCComponent

    class BrokenADC(ADCComponent):
        def gain(self, frequency):
            return 0.0

        def noise(self, frequency=None):
            raise RuntimeError("datasheet interpolation failed")

    chain = SignalChain(name="broken")
    chain.add_component(
        registry.create("attenuator", {"attenuation": -10, "temperature": 300}),
        label="A")
    chain.set_digitizer(None, BrokenADC())

    with pytest.raises(RuntimeError, match="datasheet interpolation failed"):
        chain.output_noise(1.5e9, 1e3)


def test_noise_methods_agree_at_the_end_of_the_chain():
    """
    output_noise() and noise_at_point(last) must give the same answer. They used
    to differ by the final component's own gain; both now share one propagation
    rule.
    """
    chain = SignalChain(name="convention")
    chain.add_component(
        registry.create("attenuator", {"attenuation": -10, "temperature": 300}),
        label="A")
    chain.add_component(
        registry.create("attenuator", {"attenuation": -6, "temperature": 300}),
        label="B")

    assert chain.noise_at_point("B", 1.5e9, 1e3) == pytest.approx(
        chain.output_noise(1.5e9, 1e3), rel=1e-12)

    _, point_parts = chain.noise_at_point("B", 1.5e9, 1e3, contributions=True)
    _, output_parts = chain.output_noise(1.5e9, 1e3, contributions=True)
    assert point_parts == pytest.approx(output_parts, rel=1e-12)


def test_attenuator_does_not_attenuate_its_own_johnson_noise():
    """
    An attenuator's k_B*T noise is present at its output; the attenuator does
    not act on it. A lone attenuator at 300 K therefore contributes exactly
    k_B*T at the chain output, whatever its attenuation.
    """
    from utils import kb

    for attenuation in (-3.0, -10.0, -30.0):
        chain = SignalChain(name="atten")
        chain.add_component(
            registry.create("attenuator",
                            {"attenuation": attenuation, "temperature": 300}),
            label="A")
        assert chain.output_noise(1.5e9, 1e3) == pytest.approx(kb * 300, rel=1e-12)


def test_amplifier_noise_is_amplified_by_its_own_gain():
    """
    An amplifier's noise temperature is input-referred, so its contribution at
    the output is its noise times its own gain.
    """
    lna = registry.create("amplifier.asu_3ghz_lna", {})
    chain = SignalChain(name="lna")
    chain.add_component(lna, label="LNA")

    expected = lna.noise(1.5e9) * 10 ** (lna.gain(1.5e9) / 10)
    assert chain.output_noise(1.5e9, 1.5e9) == pytest.approx(expected, rel=1e-9)


def test_noise_at_point_ignores_the_digitizer():
    """
    Documents a known gap, not desired behaviour: noise_at_point() iterates only
    self.components, so it omits DAC phase noise even though the DAC is upstream
    of every point in the chain. Since the DAC often dominates the budget, the
    method understates noise at an interior point whenever a digitizer is set.

    output_noise() minus the two converter contributions equals it exactly,
    which is what this pins.
    """
    chain = SignalChain(name="gap")
    chain.add_component(
        registry.create("attenuator", {"attenuation": -10, "temperature": 300}),
        label="A")
    chain.add_component(registry.create("amplifier.asu_3ghz_lna", {}), label="LNA")
    dac = registry.create("converter.ad9082_dac", {"carrier_power_dbm": -20.0})
    adc = registry.create("converter.ad9082_adc", {})
    chain.set_digitizer(dac, adc)

    total, parts = chain.output_noise(1.5e9, 1e3, contributions=True)
    components_only = total - parts[dac.name] - parts[adc.name]

    assert chain.noise_at_point("LNA", 1.5e9, 1e3) == pytest.approx(
        components_only, rel=1e-9)
    # And the omitted DAC term is not negligible - here it dominates.
    assert parts[dac.name] > 10 * components_only


def test_noise_reference_is_declared_per_component():
    """The convention is a component property, not hard-coded in the chain."""
    assert registry.create("attenuator",
                           {"attenuation": -10,
                            "temperature": 300}).noise_reference == "output"
    assert registry.create("amplifier.asu_3ghz_lna",
                           {}).noise_reference == "input"
    assert registry.create("converter.ad9082_dac",
                           {}).noise_reference == "output"


def test_empty_chain_is_harmless():
    chain = SignalChain(name="empty")
    assert chain.total_gain(1.5e9) == 0.0
    assert chain.output_noise(1.5e9, 1e3) == 0.0
