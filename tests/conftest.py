"""Shared test fixtures and helpers."""

import os
import sys

import pytest

# Tests import the project modules directly, so put the repo root on the path.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Frequencies used across the characterization snapshots. Chosen to sit inside
# the datasheet range of every component, so the values do not depend on each
# component's extrapolation behaviour.
CARRIER_FREQS = [1.0e8, 5.0e8, 1.0e9, 1.5e9, 2.5e9]

# Spectral (audio) frequencies - the offset from the carrier at which noise
# is evaluated. Spans the 1/f region of the DAC phase noise.
SPECTRAL_FREQS = [1.0e0, 1.0e2, 1.0e3, 1.0e5]


@pytest.fixture(autouse=True)
def dialogs(monkeypatch):
    """
    Make Qt message boxes non-blocking, and record them.

    GUI code reports internal errors through QMessageBox.critical. Headless,
    that is a modal dialog with nobody to dismiss it, so a plain bug - a missing
    import, say - manifests as the test suite hanging forever instead of
    failing. Recording them instead means the error surfaces, and tests can
    assert on what the user would have been shown.
    """
    try:
        from PySide6.QtWidgets import QMessageBox
    except ImportError:
        yield []
        return

    recorded = []

    def record(kind, default):
        def handler(parent, title, text, *args, **kwargs):
            recorded.append({"kind": kind, "title": title, "text": text})
            return default
        return staticmethod(handler)

    monkeypatch.setattr(QMessageBox, "critical", record("critical", QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "warning", record("warning", QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "information",
                        record("information", QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "question", record("question", QMessageBox.No))
    yield recorded


@pytest.fixture
def sample_chain():
    """A small but representative chain: warm attenuator, cryo cable, LNA."""
    from hardware_models import ASU_3GHz_LNA, Attenuator, SMA_SS086_cryo
    from signal_chain import SignalChain

    chain = SignalChain(name="Test Chain")
    chain.add_component(Attenuator(-10, 300), label="InputAtten")
    chain.add_component(SMA_SS086_cryo(0.5, temperature=4), label="CryoCable")
    chain.add_component(ASU_3GHz_LNA(), label="LNA")
    return chain
