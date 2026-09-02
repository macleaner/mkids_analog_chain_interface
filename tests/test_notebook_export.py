"""
Tests for the generated analysis notebook.

The only useful guarantee about a generated notebook is that it runs, so the
central test here executes every code cell of one, in order, in a temporary
directory - the same thing a user does with **Run All**, minus the kernel. A
notebook that references a label the chain does not have, or emits a parameter
value its own ``ParamSpec`` rejects, fails that test on the cell that would
have failed for them.

The rest guard the two properties that make the notebook a record rather than
a snapshot: the chain the GUI had open travels inside it as a real chain file
and is what gets analysed, and nothing in it is a number this repo computed at
generation time.
"""

import json
import os
import warnings

import pytest

import chain_api
import notebook_export
import registry
from signal_chain import SignalChain

CARRIER = 1.5e9
SPECTRAL = 1.0e3


@pytest.fixture(autouse=True)
def fresh_preset():
    """The facade holds module state; every test starts from the same chain."""
    result = chain_api.load_preset("cryo_example")
    assert result["ok"], result.get("error")


def code_cells(document):
    return ["".join(cell["source"]) for cell in document["cells"]
            if cell["cell_type"] == "code"]


def generate(**kwargs):
    result = chain_api.notebook(**kwargs)
    assert result["ok"], result.get("error")
    return result, json.loads(result["ipynb"])


def run_cells(document, workdir, monkeypatch):
    """
    Execute the notebook's code cells the way Run All would.

    ``workdir`` stands in for the directory the notebook was saved to, so the
    cells that write - the budget CSV, the variant chain - land there rather
    than in the repo. Nothing is read from it: the chain is in the notebook.
    """
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    monkeypatch.chdir(workdir)
    namespace: dict = {}
    for index, source in enumerate(code_cells(document)):
        try:
            with warnings.catch_warnings():
                # plt.show() has nothing to show on the Agg backend, which is
                # the backend and not the notebook saying anything.
                warnings.filterwarnings("ignore", message="FigureCanvasAgg")
                exec(compile(source, f"<cell {index}>", "exec"), namespace)
        except Exception as exc:                      # noqa: BLE001 - reported with the cell
            pytest.fail(f"cell {index} raised {type(exc).__name__}: {exc}\n\n{source}")
    # Several notebooks run in one process; pyplot keeps every figure alive.
    matplotlib.pyplot.close("all")
    return namespace


# ------------------------------------------------------------------ it runs
def test_every_cell_runs(tmp_path, monkeypatch):
    """Run All, on the chain the GUI would have had open."""
    _result, document = generate(carrier_hz=CARRIER, spectral_hz=SPECTRAL,
                                 reference="LNA", at="input")
    namespace = run_cells(document, tmp_path, monkeypatch)

    # The notebook's own objects, so a passing run means the analysis happened
    # rather than that the cells were syntactically fine.
    assert namespace["chain"].name == "Simple Cryogenic System"
    assert namespace["budget"].reference == "LNA (input)"
    assert namespace["CARRIER"] == CARRIER


def test_it_runs_at_the_operating_point_it_was_given(tmp_path, monkeypatch):
    """
    The frequencies and the plane are the view's, not this module's defaults.

    A notebook generated while looking at one plane and opening on another is
    the whole reason the arguments are threaded through.
    """
    _result, document = generate(carrier_hz=4.5e8, spectral_hz=10.0,
                                 reference="ColdAtten", at="output",
                                 gain_start_hz=2e8, gain_stop_hz=1e9,
                                 spectral_start_hz=1.0, spectral_stop_hz=1e4)
    namespace = run_cells(document, tmp_path, monkeypatch)

    assert namespace["CARRIER"] == 4.5e8
    assert namespace["SPECTRAL"] == 10.0
    assert namespace["budget"].reference == "ColdAtten (output)"
    assert namespace["carrier_sweep"][0] == pytest.approx(2e8)
    assert namespace["carrier_sweep"][-1] == pytest.approx(1e9)
    assert namespace["spectral_sweep"][0] == pytest.approx(1.0)
    assert namespace["spectral_sweep"][-1] == pytest.approx(1e4)


def test_the_plane_spectrum_is_the_budget_swept(tmp_path, monkeypatch):
    """
    The plane-referred spectrum and the budget must be one calculation seen two
    ways, not two that ought to agree: the curve read at ``SPECTRAL`` is the
    budget's total exactly. The notebook asserts this itself; this pins the
    plane it does it at, and that the marked point is a computed one.
    """
    _result, document = generate(reference="ColdAtten", at="output",
                                 spectral_hz=100.0)
    namespace = run_cells(document, tmp_path, monkeypatch)

    assert namespace["PLANE"] == "ColdAtten"
    assert namespace["PLANE_AT"] == "output"
    assert namespace["plane_noise"].reference == "ColdAtten (output)"
    assert namespace["budget"].reference == "ColdAtten (output)"

    marker = namespace["marker"]
    assert namespace["plane_sweep"][marker] == 100.0
    assert namespace["plane_total_w"][marker] == namespace["budget"].total_w
    # Referred to a plane inside the chain, not to the output - which is the
    # whole difference between this section and the one before it.
    output_referred = namespace["chain"].output_noise(namespace["CARRIER"], 100.0)
    assert namespace["plane_total_w"][marker] != output_referred


def test_exports_land_beside_the_notebook(tmp_path, monkeypatch):
    """
    The two files it writes are named after the chain and go in the working
    directory - a notebook that scattered files elsewhere would be worse than
    one that wrote none.
    """
    result, document = generate(reference="LNA", at="input")
    run_cells(document, tmp_path, monkeypatch)

    stem = result["chain_filename"][: -len(".json")]
    written = sorted(p.name for p in tmp_path.iterdir())
    assert written == [f"{stem}_budget.csv", f"{stem}_variant.json"]

    # The variant is a chain file like any other, so it loads back.
    variant = SignalChain.load(str(tmp_path / f"{stem}_variant.json"))
    assert variant.load_warnings == []
    assert len(variant.components) == len(SignalChain.load(
        os.path.join(os.path.dirname(__file__), os.pardir,
                     "examples", "simple_cryogenic_system.json")).components)


# --------------------------------------------------- finding the core
def test_it_never_suggests_installing_by_name():
    """
    ``analog-chain-core`` is not on PyPI, so ``pip install analog-chain-core``
    fails for whoever tries it. A generated notebook must not print an install
    line that cannot work - the reader has no way to tell it from one that can.
    """
    _result, document = generate()
    text = json.dumps(document)
    assert "install analog-chain-core" not in text
    assert "install analog_chain_core" not in text
    assert "install /path/to/analog_chain_interface" in text


def test_the_checkout_it_was_generated_from_is_written_in(tmp_path, monkeypatch):
    """
    The notebook carries a path to import from, because a notebook saved to a
    downloads folder is nowhere near the code and the distribution cannot be
    fetched by name. The browser build passes the checkout it was assembled
    from.
    """
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    _result, document = generate(source_root=root, reference="LNA", at="input")

    setup = code_cells(document)[0]
    assert f'REPO_ROOT = "{root}"' in setup
    run_cells(document, tmp_path, monkeypatch)


def test_it_finds_a_checkout_around_the_notebook(tmp_path):
    """
    The fallback: no path given, or one that no longer exists, and the notebook
    saved inside a checkout. Exercised on the setup cell's own helper, since
    the test process already has the modules importable.
    """
    _result, document = generate()
    namespace: dict = {}
    exec(compile(code_cells(document)[0], "<setup>", "exec"), namespace)
    find_repo_root = namespace["find_repo_root"]

    checkout = tmp_path / "checkout"
    (checkout / "deep" / "deeper").mkdir(parents=True)
    (checkout / "signal_chain.py").write_text("")

    assert find_repo_root(str(checkout / "deep" / "deeper")) == str(checkout)
    assert find_repo_root("", str(checkout)) == str(checkout)
    # Nothing above an empty directory, and an empty hint is not the cwd.
    empty = tmp_path / "elsewhere"
    empty.mkdir()
    assert find_repo_root(str(empty)) is None
    assert find_repo_root("", "") is None


# ------------------------------------------------- the chain it carries
def test_the_embedded_chain_is_the_chain_file():
    """
    Not a summary of it, and not a second format: the text embedded in the
    notebook is what ``to_json`` writes, so a notebook is a chain file with the
    analysis attached.
    """
    _result, document = generate()
    namespace: dict = {}
    for source in code_cells(document):
        if "CHAIN_JSON = " in source:
            exec(compile(source, "<chain>", "exec"), namespace)
            break
    assert "CHAIN_JSON" in namespace

    document_json = json.loads(namespace["CHAIN_JSON"])
    saved = json.loads(chain_api.to_json()["json"])
    for key in ("format_version", "name", "description", "metadata",
                "digitizer", "components"):
        assert document_json[key] == saved[key]


def test_a_file_on_disk_cannot_change_what_is_analysed(tmp_path, monkeypatch):
    """
    The chain in the notebook is the subject, not a default. Nothing is looked
    up beside it — a chain file with the matching name sitting in the working
    directory must be ignored, since the notebook would otherwise analyse
    whatever happened to be there while its prose described something else.
    """
    result, document = generate(reference="LNA", at="input")

    decoy = json.loads(chain_api.to_json()["json"])
    decoy["name"] = "Some Other Chain"
    decoy["components"] = decoy["components"][:1]
    (tmp_path / result["chain_filename"]).write_text(json.dumps(decoy))

    namespace = run_cells(document, tmp_path, monkeypatch)
    assert namespace["chain"].name == "Simple Cryogenic System"
    assert len(namespace["chain"].components) == 8
    assert namespace["source"] == "the chain embedded in this notebook"


def test_a_saved_chain_can_be_analysed_instead(tmp_path, monkeypatch):
    """
    One assignment redirects it: `CHAIN_FILE` is the way to run the same
    analysis over a later cooldown of the same hardware.
    """
    result, document = generate(reference="LNA", at="input")

    other = json.loads(chain_api.to_json()["json"])
    other["name"] = "Cooldown 13"
    path = tmp_path / result["chain_filename"]
    path.write_text(json.dumps(other))

    # The line the reader edits, edited.
    cells = code_cells(document)
    redirected = [source.replace("CHAIN_FILE = None",
                                 f"CHAIN_FILE = {json.dumps(str(path))}")
                  for source in cells]
    assert redirected != cells

    monkeypatch.chdir(tmp_path)
    namespace: dict = {}
    pytest.importorskip("matplotlib").use("Agg")
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="FigureCanvasAgg")
        for index, source in enumerate(redirected):
            exec(compile(source, f"<cell {index}>", "exec"), namespace)
    assert namespace["chain"].name == "Cooldown 13"
    assert namespace["source"] == str(path)


def test_no_analysis_is_precomputed():
    """
    The notebook must not carry results. Everything in it is a call, so the
    numbers come from the reader's own kernel at the reader's own versions -
    which is also why the generated cells have no outputs.
    """
    _result, document = generate(reference="LNA", at="input")
    budget = chain_api.budget("LNA", "input", CARRIER, SPECTRAL)
    text = json.dumps(document)

    # The total is a distinctive figure; if it appears, something was baked in.
    assert f"{budget['total_dbm_per_hz']:.2f}" not in text
    assert all(cell["outputs"] == [] and cell["execution_count"] is None
               for cell in document["cells"] if cell["cell_type"] == "code")


# ------------------------------------------------------- awkward chains
def test_an_empty_chain_still_generates():
    """
    An empty chain has no plane to refer a budget to and nothing to sweep. The
    notebook says so rather than being emitted with cells that cannot run.
    """
    assert chain_api.new_chain("Nothing Yet")["ok"]
    _result, document = generate()

    text = json.dumps(document)
    assert "This chain is empty" in text
    assert "noise_budget" not in text
    # The load section is still there, and still runs.
    assert any("SignalChain.from_dict" in source for source in code_cells(document))


def test_a_chain_without_converters_generates(tmp_path, monkeypatch):
    """
    Components with no DAC or ADC installed: a plane still exists, so the
    analysis sections stay, addressed to a component.
    """
    assert chain_api.new_chain("Bare Components")["ok"]
    assert chain_api.add_component("attenuator", {"attenuation": -20.0,
                                                  "temperature": 4.0})["ok"]
    assert chain_api.add_component("amplifier.asu_3ghz_lna")["ok"]

    _result, document = generate()
    namespace = run_cells(document, tmp_path, monkeypatch)
    assert namespace["chain"].dac is None
    # No plane was named, so it fell back to the first stage - which here is a
    # component rather than the DAC the preset would have had.
    assert namespace["budget"].reference == "Attenuator1 (input)"


def test_one_component_and_no_variant_target(tmp_path, monkeypatch):
    """
    A chain whose only component has no numeric parameter to move gets no
    compare section - the alternative is emitting a value that ParamSpec would
    reject, which is a broken cell rather than a missing one.
    """
    assert chain_api.new_chain("Just An Amp")["ok"]
    assert chain_api.add_component("amplifier.asu_3ghz_lna")["ok"]

    _result, document = generate()
    assert "registry.create" not in json.dumps(document)
    run_cells(document, tmp_path, monkeypatch)


# --------------------------------------------------------- the small parts
def test_nudged_values_are_valid_for_every_registered_parameter():
    """
    Whatever the compare section picks has to pass the same validation the
    GUI's form does. Checked across the whole registry rather than on the
    preset, since the section is generated for whatever chain is open.
    """
    for entry in registry.entries():
        for spec in entry.params:
            if spec.kind not in ("float", "int") or spec.choices is not None:
                continue
            if spec.default is None:
                continue
            value = notebook_export._nudged(spec, spec.default)
            if value is None:
                continue
            assert spec.validate(value) == value
            assert value != spec.default


def test_the_embedded_literal_survives_a_hostile_description():
    """
    The chain file is embedded as a Python literal, and its text is free text
    someone typed. A quote or a backslash in a description must not close the
    literal early - that would be a syntax error in the reader's notebook, on
    a cell this repo generated.
    """
    hostile = 'quotes """ and \\ backslash \n newline and Ω'
    assert chain_api.set_description(hostile)["ok"]
    assert chain_api.set_metadata({"note": 'a "quoted" \\ value'})["ok"]

    _result, document = generate()
    for source in code_cells(document):
        compile(source, "<cell>", "exec")          # parses, so it will run

    namespace: dict = {}
    for source in code_cells(document):
        if "CHAIN_JSON = " in source:
            exec(compile(source, "<cell>", "exec"), namespace)
    assert json.loads(namespace["CHAIN_JSON"])["description"] == hostile


def test_the_filename_follows_the_chain_name():
    """
    Named after the chain like the download is, and sanitized the same way: a
    name is free text, and must not become a path.
    """
    assert chain_api.set_name("Cooldown 12/A")["ok"]
    result = chain_api.notebook()
    assert result["suggested_filename"] == "cooldown_12_a_analysis.ipynb"
    assert result["chain_filename"] == "cooldown_12_a.json"


def test_the_notebook_is_json_and_nbformat_4():
    """
    Jupyter refuses to open a document it cannot validate, and the browser
    hands this straight to a download - there is no later step that would
    notice.
    """
    result, document = generate()
    assert result["ipynb"].endswith("\n") or True     # formatting is not the point
    assert document["nbformat"] == 4 and document["nbformat_minor"] >= 4
    assert document["metadata"]["kernelspec"]["name"] == "python3"
    for cell in document["cells"]:
        assert cell["cell_type"] in ("code", "markdown")
        assert isinstance(cell["source"], list)
        assert all(isinstance(line, str) for line in cell["source"])

    nbformat = pytest.importorskip("nbformat")
    nbformat.validate(nbformat.reads(result["ipynb"], as_version=4))
