"""GUI tests for the noise budget panel. Headless via QT_QPA_PLATFORM=offscreen."""

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


def _build_chain(window):
    for type_id, params in [
        ("attenuator", {"attenuation": -10.0, "temperature": 300.0}),
        ("amplifier.asu_3ghz_lna", {}),
        ("cable.fm_f141", {"length_m": 2.0}),
    ]:
        window._on_add_component(registry.resolve(type_id), params)
    window.chain_view.set_digitizer(window.digitizer_panel.get_digitizer_config())


def test_reference_points_include_the_converters(window):
    _build_chain(window)
    window._analyze_chain()

    points = [window.budget_panel.point_combo.itemData(i)
              for i in range(window.budget_panel.point_combo.count())]
    assert "AD9082_DAC" in points
    assert "AD9082_ADC" in points
    assert len(points) == 5  # DAC + 3 components + ADC


def test_computing_a_budget_renders_a_table(window):
    _build_chain(window)
    window._analyze_chain()
    window.budget_panel.compute()

    text = window.budget_panel.table_view.toPlainText()
    assert "referred to" in text
    assert "TOTAL" in text
    assert "AD9082_DAC" in text
    assert window.budget_panel.export_button.isEnabled()
    assert "Dominated by" in window.budget_panel.summary_label.text()


def test_switching_side_changes_the_result(window):
    _build_chain(window)
    window._analyze_chain()

    panel = window.budget_panel
    panel.point_combo.setCurrentIndex(panel.point_combo.findData("ASU_3GHz_LNA_1"))

    panel.side_combo.setCurrentIndex(panel.side_combo.findData("input"))
    panel.compute()
    at_input = float(panel.budget.total_w)

    panel.side_combo.setCurrentIndex(panel.side_combo.findData("output"))
    panel.compute()
    at_output = float(panel.budget.total_w)

    assert at_output != pytest.approx(at_input, rel=1e-6, abs=0.0)


def test_empty_chain_is_handled(window):
    window.budget_panel.set_chain(window.chain_view.get_chain())
    window.budget_panel.compute()
    assert "Add components" in window.budget_panel.table_view.toPlainText()
    assert not window.budget_panel.export_button.isEnabled()


def test_csv_export_includes_referral_gains(window, tmp_path, monkeypatch):
    _build_chain(window)
    window._analyze_chain()
    window.budget_panel.compute()

    target = tmp_path / "budget.csv"
    monkeypatch.setattr(
        "gui_components.budget_panel.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(target), "CSV Files (*.csv)"))
    window.budget_panel._export_csv()

    text = target.read_text()
    assert "# reference_plane," in text
    assert "# total_K," in text
    assert "referral_gain_dB" in text
    assert "contribution_K" in text
    # One header row plus one row per contribution.
    data_lines = [l for l in text.splitlines()
                  if l and not l.startswith("#")]
    assert len(data_lines) == 1 + len(window.budget_panel.budget.contributions)


def test_unit_selector_defaults_to_dbm_and_toggles(window):
    _build_chain(window)
    window._analyze_chain()
    panel = window.budget_panel

    assert panel.current_unit() == "dBm/Hz"
    panel.compute()
    assert "[dBm/Hz]" in panel.table_view.toPlainText()
    assert "dBm/Hz" in panel.summary_label.text()

    # Switching units reformats the existing budget without recomputing.
    budget_before = panel.budget
    panel.unit_combo.setCurrentIndex(panel.unit_combo.findData("W/Hz"))
    assert panel.budget is budget_before
    assert "[W/Hz]" in panel.table_view.toPlainText()
    assert "W/Hz" in panel.summary_label.text()
