"""
Tests for the save helper — the loopback server that turns the browser build's
downloads into files written where a save dialog says.

The dialog itself is the one thing not exercised here: it is zenity, and a test
that waits for someone to click Save is not a test. Everything around it is,
because that is where a mistake is expensive — a file written without the
dialog being confirmed, a file written by a page that is not this one, or the
remembered folder failing to come back, which is the whole point of it.
"""

import json
import os
import shutil
import threading
import urllib.error
import urllib.request

import pytest

import save_helper

TOKEN = 'test-token'


@pytest.fixture
def helper(tmp_path, monkeypatch):
    """A server on a port the OS picks, whose dialog is a stub. `helper.asked`
    records what the dialog was shown; `helper.answer` is what it returns —
    a path, or None for a cancelled dialog."""
    monkeypatch.setattr(save_helper, 'CONFIG_DIR', str(tmp_path / 'config'))
    monkeypatch.setattr(save_helper, 'DIRS_FILE',
                        str(tmp_path / 'config' / 'save-dirs.json'))

    server = save_helper.Server(0, TOKEN)

    def stub(directory, filename):
        server.asked.append((directory, filename))
        answer = server.answer
        if isinstance(answer, Exception):
            raise answer
        return answer

    server.asked = []
    server.answer = None
    monkeypatch.setattr(save_helper, 'ask_where', stub)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.url = f'http://127.0.0.1:{server.server_address[1]}'
    yield server
    server.shutdown()
    server.server_close()


def post(helper, body, path='/save'):
    """Returns (status, decoded JSON), including for the refusals — a page that
    is told why is a page that can fall back to downloading."""
    request = urllib.request.Request(
        helper.url + path, data=json.dumps(body).encode(),
        headers={'Content-Type': 'text/plain;charset=UTF-8'}, method='POST')
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as err:
        return err.code, json.load(err)


def save_body(filename='chain.json', text='{"name": "Test Chain"}', token=TOKEN):
    return {'token': token, 'filename': filename, 'text': text}


def test_writes_where_the_dialog_said(helper, tmp_path):
    chosen = tmp_path / 'runs' / 'chain.json'
    chosen.parent.mkdir()
    helper.answer = str(chosen)

    status, reply = post(helper, save_body())

    assert (status, reply['status'], reply['path']) == (200, 'saved', str(chosen))
    assert chosen.read_text() == '{"name": "Test Chain"}'


def test_opens_where_this_kind_of_file_last_went(helper, tmp_path):
    """The folder is remembered per extension: a notebook filed somewhere else
    must not move where the next chain file is offered."""
    runs, books = tmp_path / 'runs', tmp_path / 'books'
    runs.mkdir(), books.mkdir()

    helper.answer = str(runs / 'chain.json')
    post(helper, save_body())
    helper.answer = str(books / 'chain.ipynb')
    post(helper, save_body(filename='chain.ipynb', text='{}'))
    helper.answer = str(runs / 'other.json')
    post(helper, save_body(filename='other.json'))

    assert [directory for directory, _ in helper.asked][2] == str(runs)


def test_a_cancelled_dialog_writes_nothing(helper, tmp_path):
    helper.answer = None

    status, reply = post(helper, save_body())

    assert (status, reply['status']) == (200, 'cancelled')
    assert list(tmp_path.glob('**/*.json')) == []


def test_a_page_without_the_token_never_sees_a_dialog(helper):
    """The refusal has to come before the dialog, not after it: a dialog put up
    by another page is the thing the token exists to prevent."""
    status, reply = post(helper, save_body(token='guessed'))

    assert (status, reply['status']) == (403, 'error')
    assert helper.asked == []


def test_no_dialog_program_is_reported_as_its_own_status(helper):
    """Not an error — the page answers it by downloading, the way it did
    before there was a helper at all."""
    helper.answer = save_helper.NoDialog('nothing installed')

    status, reply = post(helper, save_body())

    assert (status, reply['status']) == (501, 'nodialog')


def test_an_extensionless_name_keeps_the_suggested_one(helper, tmp_path):
    helper.answer = str(tmp_path / 'run3')

    status, reply = post(helper, save_body())

    assert reply['path'] == str(tmp_path / 'run3.json')
    assert os.path.exists(reply['path'])


def test_the_remembered_folder_survives_a_restart(helper, tmp_path, monkeypatch):
    """It is written to the config directory rather than held in memory: the
    helper is stopped every time the launcher is, and a folder that only lasted
    as long as one session would be forgotten between one day's work and the
    next."""
    runs = tmp_path / 'runs'
    runs.mkdir()
    helper.answer = str(runs / 'chain.json')
    post(helper, save_body())

    assert save_helper.opening_dir('json') == str(runs)


def test_a_forgotten_folder_falls_back_instead_of_failing(helper, tmp_path):
    """A remembered folder can be on a share that is not mounted today, and a
    dialog that opens nowhere is worse than one that opens at home."""
    gone = tmp_path / 'gone'
    gone.mkdir()
    helper.answer = str(gone / 'chain.json')
    post(helper, save_body())
    shutil.rmtree(gone)

    assert os.path.isdir(save_helper.opening_dir('json'))


def test_unknown_paths_are_refused(helper):
    status, reply = post(helper, save_body(), path='/write')

    assert status == 404
    assert helper.asked == []
