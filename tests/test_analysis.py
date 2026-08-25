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


def test_output_noise_accepts_an_array_of_spectral_frequencies(sample_chain):
    """
    Frequency sweeps used to raise ValueError from a scalar truth test on an
    array, forcing callers to loop one frequency at a time.
    """
    spectral_freqs = np.logspace(0, 5, 25)
    result = sample_chain.output_noise(1.5e9, spectral_freqs)
    assert np.shape(result) == spectral_freqs.shape
    assert np.all(np.asarray(result) > 0)


def test_noise_at_point_accepts_an_array(sample_chain):
    spectral_freqs = np.logspace(0, 5, 25)
    result = sample_chain.noise_at_point("LNA", 1.5e9, spectral_freqs, at="output")
    assert np.shape(result) == spectral_freqs.shape


def test_vectorized_matches_scalar_loop(sample_chain):
    """The vectorized path must agree with the per-frequency loop it replaces."""
    dac = registry.create("converter.ad9082_dac", {"carrier_power_dbm": -20.0})
    adc = registry.create("converter.ad9082_adc", {})
    sample_chain.set_digitizer(dac, adc)

    spectral_freqs = np.logspace(0, 5, 17)
    vectorized = np.asarray(sample_chain.output_noise(1.5e9, spectral_freqs))
    looped = np.asarray([sample_chain.output_noise(1.5e9, f) for f in spectral_freqs])
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

        def noise(self, carrier_frequency, spectral_frequency):
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
    With no digitizer, the output plane is the last component's output plane, so
    the two methods must give the same answer. They used to differ by the final
    component's own gain; both now share one propagation rule.
    """
    chain = SignalChain(name="convention")
    chain.add_component(
        registry.create("attenuator", {"attenuation": -10, "temperature": 300}),
        label="A")
    chain.add_component(
        registry.create("attenuator", {"attenuation": -6, "temperature": 300}),
        label="B")

    assert chain.noise_at_point("B", 1.5e9, 1e3, at="output") == pytest.approx(
        chain.output_noise(1.5e9, 1e3), rel=1e-12)

    _, point_parts = chain.noise_at_point(
        "B", 1.5e9, 1e3, contributions=True, at="output")
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

    expected = lna.noise(1.5e9, 1e3) * 10 ** (lna.gain(1.5e9) / 10)
    assert chain.output_noise(1.5e9, 1.5e9) == pytest.approx(expected, rel=1e-9)


def _digitizer_chain():
    """LNA then a lossy stage into the ADC - little gain before digitizing."""
    chain = SignalChain(name="referral")
    chain.add_component(registry.create("amplifier.asu_3ghz_lna", {}), label="LNA")
    chain.add_component(
        registry.create("cable.fm_f141", {"length_m": 2.0}), label="OutCable")
    chain.add_component(
        registry.create("attenuator", {"attenuation": -20, "temperature": 300}),
        label="PreAdcAtten")
    chain.set_digitizer(
        registry.create("converter.ad9082_dac", {"carrier_power_dbm": -20.0}),
        registry.create("converter.ad9082_adc", {}))
    return chain


def test_every_source_appears_in_an_interior_budget():
    """
    A budget refers *all* sources to the plane, so both converters appear at an
    interior point - the DAC referred forward, the ADC referred backward.
    """
    chain = _digitizer_chain()
    budget = chain.noise_budget("LNA", 1.5e9, 1e3, at="input")
    labels = {c.label for c in budget.contributions}
    assert {"AD9082_DAC", "AD9082_ADC", "LNA", "PreAdcAtten"} <= labels


def test_downstream_sources_are_referred_backward():
    """A source after the plane is divided by the gain between them."""
    chain = _digitizer_chain()
    budget = chain.noise_budget("LNA", 1.5e9, 1e3, at="input")
    by_label = {c.label: c for c in budget.contributions}

    adc = by_label["AD9082_ADC"]
    # The LNA input plane sits just after the DAC, and the ADC's noise is
    # defined at the chain output, so the referral is the negative of the gain
    # between those two planes.
    expected = float(chain.dac.gain(1.5e9)) - float(chain.total_gain(1.5e9))
    assert float(adc.referral_gain_db) == pytest.approx(expected, rel=1e-9)

    # This chain has positive net gain, so referring the ADC backward shrinks it.
    assert expected < 0
    assert float(adc.power_w) < float(adc.intrinsic_w)


def test_upstream_sources_are_referred_forward():
    """A source before the plane picks up the gains between it and the plane."""
    chain = _digitizer_chain()
    budget = chain.noise_budget("PreAdcAtten", 1.5e9, 1e3, at="input")
    by_label = {c.label: c for c in budget.contributions}

    # DAC noise is defined at the DAC output; between there and the plane sit
    # the LNA and the out cable.
    expected = float(chain.gain_between("LNA", "OutCable", 1.5e9))
    assert float(by_label["AD9082_DAC"].referral_gain_db) == pytest.approx(
        expected, rel=1e-9)


def test_referring_to_input_and_output_differ_by_the_component_gain():
    """This is why `at` is required rather than implicit."""
    chain = _digitizer_chain()
    lna_gain = float(chain.components[0].gain(1.5e9))

    at_input = chain.noise_at_point("LNA", 1.5e9, 1e3, at="input")
    at_output = chain.noise_at_point("LNA", 1.5e9, 1e3, at="output")
    assert float(at_output) / float(at_input) == pytest.approx(
        10 ** (lna_gain / 10), rel=1e-9)


def test_at_is_required_and_validated():
    chain = _digitizer_chain()
    with pytest.raises(TypeError):
        chain.noise_at_point("LNA", 1.5e9, 1e3)
    with pytest.raises(ValueError, match="must be 'input' or 'output'"):
        chain.noise_at_point("LNA", 1.5e9, 1e3, at="middle")


def test_budget_reports_power_and_temperature():
    """Totals and per-source contributions are available in W/Hz and K."""
    from utils import kb

    chain = _digitizer_chain()
    budget = chain.noise_budget("LNA", 1.5e9, 1e3, at="input")

    assert float(budget.total_k) == pytest.approx(
        float(budget.total_w) / kb, rel=1e-12)
    for c in budget.contributions:
        assert float(c.temperature_k) == pytest.approx(
            float(c.power_w) / kb, rel=1e-12)
        assert float(c.intrinsic_k) == pytest.approx(
            float(c.intrinsic_w) / kb, rel=1e-12)


def test_budget_contributions_sum_to_the_total_and_are_ranked():
    chain = _digitizer_chain()
    budget = chain.noise_budget("LNA", 1.5e9, 1e3, at="input")

    assert sum(float(c.power_w) for c in budget.contributions) == pytest.approx(
        float(budget.total_w), rel=1e-12)
    powers = [float(c.power_w) for c in budget.contributions]
    assert powers == sorted(powers, reverse=True)
    assert budget.dominant() is budget.contributions[0]
    assert sum(float(budget.fraction(c)) for c in budget.contributions) == \
        pytest.approx(1.0, rel=1e-12)


def test_budget_table_and_rows_render():
    chain = _digitizer_chain()
    budget = chain.noise_budget("LNA", 1.5e9, 1e3, at="input")

    text = budget.table()
    assert "referred to LNA (input)" in text
    assert "TOTAL" in text
    assert "AD9082_ADC" in text

    rows = budget.to_rows()
    assert len(rows) == len(budget.contributions)
    assert {"source", "intrinsic_K", "referral_gain_dB",
            "contribution_K", "fraction_of_total"} <= set(rows[0])


def test_budget_table_rejects_a_frequency_sweep():
    chain = _digitizer_chain()
    budget = chain.noise_budget("LNA", 1.5e9, np.logspace(0, 4, 5), at="input")
    with pytest.raises(ValueError, match="scalar frequencies"):
        budget.table()
    # to_rows still works, carrying arrays through.
    assert len(budget.to_rows()) == len(budget.contributions)


def test_converters_can_be_referenced_by_name():
    chain = _digitizer_chain()
    at_dac = chain.noise_budget("AD9082_DAC", 1.5e9, 1e3, at="output")
    assert at_dac.reference == "AD9082_DAC (output)"
    # Referred to the DAC output, DAC noise needs no referral at all.
    dac_term = next(c for c in at_dac.contributions if c.label == "AD9082_DAC")
    assert float(dac_term.referral_gain_db) == pytest.approx(0.0)
    assert float(dac_term.power_w) == pytest.approx(float(dac_term.intrinsic_w))


def test_component_labels_take_precedence_over_converter_names():
    chain = SignalChain(name="collide")
    chain.add_component(
        registry.create("attenuator", {"attenuation": -10, "temperature": 300}),
        label="AD9082_DAC")
    chain.set_digitizer(
        registry.create("converter.ad9082_dac", {"carrier_power_dbm": -20.0}),
        None)
    plane, description = chain.resolve_plane("AD9082_DAC", "input")
    # Resolves to the component (stage 1, after the DAC), not the DAC itself.
    assert plane == 1
    assert description == "AD9082_DAC (input)"


def test_unknown_reference_point_is_reported():
    chain = _digitizer_chain()
    with pytest.raises(KeyError, match="cannot resolve reference point"):
        chain.noise_budget("NoSuchThing", 1.5e9, 1e3, at="input")


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
