"""
Diagram generation tests.

These exist because a missing import in the diagram panel's noise annotation
went undetected: the resulting NameError was caught and reported through a modal
QMessageBox, which headless just blocks forever. The `dialogs` fixture in
conftest turns those into records, so this suite fails instead of hanging.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="GUI tests need PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import registry  # noqa: E402
from signal_chain import SignalChain  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


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
def test_diagram_panel_generates_without_error(app, chain, dialogs,
                                               show_gain, show_noise):
    """
    Every annotation combination must render. show_noise=True is the case that
    exercises the dBm/Hz conversion, and the one that was broken.
    """
    from gui_components.diagram_panel import DiagramPanel

    panel = DiagramPanel()
    panel.set_chain(chain)
    panel.show_gain_check.setChecked(show_gain)
    panel.show_noise_check.setChecked(show_noise)
    panel.generate_diagram()

    errors = [d for d in dialogs if d["kind"] == "critical"]
    assert not errors, f"diagram generation reported: {errors}"


def test_diagram_panel_reports_an_empty_chain(app, dialogs):
    from gui_components.diagram_panel import DiagramPanel

    panel = DiagramPanel()
    panel.set_chain(SignalChain("empty"))
    panel.generate_diagram()
    assert not [d for d in dialogs if d["kind"] == "critical"]


def test_main_window_diagram_action(app, dialogs):
    """The toolbar path, end to end."""
    from gui_components import MainWindow

    window = MainWindow()
    for type_id, params in [
        ("attenuator", {"attenuation": -20.0, "temperature": 300.0}),
        ("amplifier.asu_3ghz_lna", {}),
    ]:
        window._on_add_component(registry.resolve(type_id), params)
    window.chain_view.set_digitizer(
        window.digitizer_panel.get_digitizer_config())

    window._generate_diagram()
    assert not [d for d in dialogs if d["kind"] == "critical"]


def test_diagram_generator_writes_a_file(chain, tmp_path):
    """The non-GUI generator, including its noise annotations."""
    from diagram_generator import DiagramGenerator

    target = tmp_path / "chain.pdf"
    DiagramGenerator(chain).generate(
        filename=str(target), frequency=1.5e9, show_gain=True, show_noise=True)
    assert target.exists() and target.stat().st_size > 0


def test_diagram_generator_detailed_writes_a_file(chain, tmp_path):
    import numpy as np

    from diagram_generator import DiagramGenerator

    target = tmp_path / "detailed.pdf"
    DiagramGenerator(chain).generate_detailed(
        filename=str(target), frequency_range=np.logspace(8, 9.4, 12))
    assert target.exists() and target.stat().st_size > 0
