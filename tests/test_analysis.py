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


def test_noise_methods_disagree_on_the_final_component():
    """
    Pins a known inconsistency: noise_at_point() includes the reference
    component's own gain (gain_between is inclusive of its start index) while
    output_noise() excludes it for the last component. They therefore differ by
    exactly the final component's gain.

    Recorded rather than fixed - choosing a convention is a physics decision
    about whether a component's noise is referred to its input or its output.
    """
    chain = SignalChain(name="convention")
    chain.add_component(
        registry.create("attenuator", {"attenuation": -10, "temperature": 300}),
        label="A")
    chain.add_component(
        registry.create("attenuator", {"attenuation": -6, "temperature": 300}),
        label="B")

    at_point = chain.noise_at_point("B", 1.5e9, 1e3)
    at_output = chain.output_noise(1.5e9, 1e3)

    # Both agree on A's contribution; they differ only on B's own gain (-6 dB).
    _, point_parts = chain.noise_at_point("B", 1.5e9, 1e3, contributions=True)
    _, output_parts = chain.output_noise(1.5e9, 1e3, contributions=True)
    assert point_parts["A"] == pytest.approx(output_parts["A"], rel=1e-12)
    ratio = output_parts["B"] / point_parts["B"]
    assert ratio == pytest.approx(10 ** (6 / 10), rel=1e-9)
    # abs=0 matters here: these values are ~1e-21, well inside approx's default
    # 1e-12 absolute tolerance, which would call them equal.
    assert at_point != pytest.approx(at_output, rel=1e-9, abs=0.0)


def test_empty_chain_is_harmless():
    chain = SignalChain(name="empty")
    assert chain.total_gain(1.5e9) == 0.0
    assert chain.output_noise(1.5e9, 1e3) == 0.0
