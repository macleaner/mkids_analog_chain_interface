"""
Diagram generation tests.

``diagram_generator`` is matplotlib rather than the browser build, so nothing
else exercises it: it is reached from a script or a notebook, and the page
draws its own chain view. These check both figures render for a chain that has
converters at both ends, including the noise annotations - a missing import
there once went undetected because the only caller swallowed the NameError.
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("matplotlib", reason="diagram generation needs matplotlib")

import registry  # noqa: E402
from signal_chain import SignalChain  # noqa: E402


@pytest.fixture
def chain():
    c = SignalChain("diagram")
    c.add_component(
        registry.create("attenuator", {"attenuation": -20.0, "temperature": 300.0}),
        label="WarmAtten")
    c.add_component(registry.create("amplifier.asu_3ghz_lna", {}), label="LNA")
    c.add_component(
        registry.create("cable.fm_f141", {"length_m": 2.0}), label="OutCable")
    c.set_digitizer(
        registry.create("converter.ad9082_dac", {"carrier_power_dbm": -20.0}),
        registry.create("converter.ad9082_adc", {}))
    return c


@pytest.mark.parametrize("show_gain,show_noise", [
    (True, True), (True, False), (False, True), (False, False)])
def test_the_block_diagram_writes_a_file(chain, tmp_path, show_gain, show_noise):
    """
    Every annotation combination must render. show_noise=True is the case that
    exercises the dBm/Hz conversion, and the one that was broken.
    """
    from diagram_generator import DiagramGenerator

    target = tmp_path / "chain.pdf"
    DiagramGenerator(chain).generate(
        filename=str(target), frequency=1.5e9,
        show_gain=show_gain, show_noise=show_noise)
    assert target.exists() and target.stat().st_size > 0


def test_the_detailed_diagram_writes_a_file(chain, tmp_path):
    from diagram_generator import DiagramGenerator

    target = tmp_path / "detailed.pdf"
    DiagramGenerator(chain).generate_detailed(
        filename=str(target), frequency_range=np.logspace(8, 9.4, 12))
    assert target.exists() and target.stat().st_size > 0


def test_an_empty_chain_still_writes_a_page(tmp_path):
    """
    A chain with nothing in it is a state the caller can be in, so it renders
    an "Empty signal chain" page rather than raising out of a plotting call.
    """
    from diagram_generator import DiagramGenerator

    target = tmp_path / "empty.pdf"
    DiagramGenerator(SignalChain("empty")).generate(
        filename=str(target), frequency=1.5e9)
    assert target.exists() and target.stat().st_size > 0
