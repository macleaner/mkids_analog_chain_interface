"""
GUI-level save/load tests.

Run headless via QT_QPA_PLATFORM=offscreen. These cover the seam between the
widgets and the model layer - the place the old NoneType-row bug lived - by
driving the real MainWindow rather than reimplementing its logic.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="GUI tests need PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import registry  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    from gui_components import MainWindow
    return MainWindow()


def _add(window, type_id, params):
    entry = registry.resolve(type_id)
    window._on_add_component(entry, params)


def test_library_offers_only_real_components(window):
    """
    Module scanning used to surface imported base classes and helper types
    (ParamSpec, ActiveComponent, PassiveComponent) as selectable components.
    """
    offered = {entry.label
               for entries in window.library.categories.values()
               for entry in entries}
    assert offered
    for bad in ("ParamSpec", "ActiveComponent", "PassiveComponent",
                "Component", "ADCComponent", "DACComponent"):
        assert bad not in offered
    # Every offered entry must actually be constructible from its defaults.
    for entries in window.library.categories.values():
        for entry in entries:
            registry.create(entry.type_id,
                            {s.name: s.default for s in entry.params})


def test_save_load_round_trip_through_the_window(window, tmp_path):
    """Build a chain in the GUI, save it, load it into a fresh window."""
    window.chain_view.set_digitizer(window.digitizer_panel.get_digitizer_config())
    _add(window, "attenuator", {"attenuation": -10.0, "temperature": 300.0})
    _add(window, "cable.sma_ss086_cryo", {"length_m": 0.5, "temperature": 4.0})
    _add(window, "amplifier.asu_3ghz_lna", {})

    path = tmp_path / "chain.json"
    chain = window.chain_view.get_chain(
        window.digitizer_panel.get_digitizer_config())
    chain.save(str(path))

    saved = json.loads(path.read_text())
    # The DAC/ADC display rows must not leak in as components.
    assert [c["type"] for c in saved["components"]] == [
        "attenuator", "cable.sma_ss086_cryo", "amplifier.asu_3ghz_lna"]
    assert saved["digitizer"]["dac"]["type"] == "converter.ad9082_dac"

    from signal_chain import SignalChain
    reloaded = SignalChain.load(str(path))
    assert reloaded.load_warnings == []
    assert reloaded.total_gain(1.5e9) == pytest.approx(chain.total_gain(1.5e9))
    assert reloaded.output_noise(1.5e9, 1e3) == pytest.approx(
        chain.output_noise(1.5e9, 1e3))


def test_loading_into_the_view_shows_digitizer_rows(window, tmp_path):
    """set_chain restores the styled DAC/ADC rows around the components."""
    window.chain_view.set_digitizer(window.digitizer_panel.get_digitizer_config())
    _add(window, "attenuator", {"attenuation": -10.0, "temperature": 300.0})

    path = tmp_path / "chain.json"
    window.chain_view.get_chain(
        window.digitizer_panel.get_digitizer_config()).save(str(path))

    from signal_chain import SignalChain
    window.chain_view.set_chain(SignalChain.load(str(path)))

    # DAC row, one component, ADC row.
    assert window.chain_view.list_widget.count() == 3
    rebuilt = window.chain_view.get_chain()
    assert len(rebuilt.components) == 1
    assert rebuilt.dac is not None and rebuilt.adc is not None


def test_metadata_survives_a_view_rebuild(window):
    """
    Bookkeeping fields live on the chain, not the widget, so a rebuild
    triggered by any list edit must not drop them.
    """
    _add(window, "attenuator", {"attenuation": -10.0, "temperature": 300.0})
    window.chain_view.chain.description = "Cooldown CD-17"
    window.chain_view.chain.metadata = {"sample": "wafer-3"}

    _add(window, "amplifier.asu_3ghz_lna", {})
    chain = window.chain_view.get_chain()

    assert chain.description == "Cooldown CD-17"
    assert chain.metadata == {"sample": "wafer-3"}


def test_labels_survive_a_view_rebuild(window, tmp_path):
    """Saved labels must not be replaced by regenerated positional ones."""
    _add(window, "attenuator", {"attenuation": -10.0, "temperature": 300.0})
    _add(window, "amplifier.asu_3ghz_lna", {})

    path = tmp_path / "chain.json"
    chain = window.chain_view.get_chain()
    # Rename a label the way a loaded file would have.
    chain.labels = {"InputAtten": 0, "LNA": 1}
    chain.save(str(path))

    from signal_chain import SignalChain
    window.chain_view.set_chain(SignalChain.load(str(path)))
    rebuilt = window.chain_view.get_chain()
    assert set(rebuilt.labels) == {"InputAtten", "LNA"}


def test_invalid_parameter_is_reported_not_crashed(window, monkeypatch):
    """An out-of-range value surfaces as a dialog, and adds nothing."""
    shown = {}

    def fake_critical(parent, title, text):
        shown["title"] = title
        shown["text"] = text

    monkeypatch.setattr(
        "gui_components.main_window.QMessageBox.critical", fake_critical)

    before = window.chain_view.list_widget.count()
    _add(window, "attenuator", {"attenuation": 999.0, "temperature": 300.0})

    assert window.chain_view.list_widget.count() == before
    assert "Invalid Parameters" in shown.get("title", "")
