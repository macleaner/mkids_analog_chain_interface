#!/usr/bin/env python3
"""Write the browser build's files through the desktop's own save dialog.

    ./save_helper.py               serve until interrupted
    ./save_helper.py --port 8757   serve somewhere else

`open_web_gui.py` starts this, so it is not usually run by hand; run it here
when you opened `dist/analog_chain_calculator.html` some other way and want the
dialog anyway.

A page opened from `file://` cannot put a save dialog up itself. Firefox has no
`showSaveFilePicker` at all, and Chrome's refuses the opaque origin a `file://`
page has, so the only thing the page can do on its own is hand the browser a
download — which lands in whatever folder the browser is configured for, does
not say where it went, and never asks. For a chain file that is the record of a
measurement, the folder it belongs in is the point.

So the page hands the file to this instead: a loopback server that asks where
to put it with zenity (or kdialog, or tkinter), writes it there, and remembers
the folder so the next save opens in the same place. Two things it deliberately
does not do — write anything without that dialog being confirmed, and make
itself required: the page falls back to the download it used to do whenever
this is not listening, which is what happens to a copy of the page mailed to
someone else.
"""
import argparse
import errno
import http.server
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading

# Arbitrary and unassigned. The page carries the port it was built with, and
# gets it from this constant at assembly time, so the two cannot drift.
DEFAULT_PORT = 8756

CONFIG_DIR = os.path.join(
    os.environ.get('XDG_CONFIG_HOME') or os.path.join(os.path.expanduser('~'), '.config'),
    'analog-chain-calculator')
# The shared secret, and the folders last saved to. Both live outside the
# checkout: they are about this machine, not about this revision, and a rebuild
# must not reset either — a token that changed with every build would leave a
# helper started before the build rejecting the page written by it.
TOKEN_FILE = os.path.join(CONFIG_DIR, 'save-token')
DIRS_FILE = os.path.join(CONFIG_DIR, 'save-dirs.json')

# A chain file is kilobytes and a generated notebook is tens of them. This is
# not a tuning knob, it is the point past which the request is not something
# this page sent.
MAX_BODY = 32 * 1024 * 1024

# On the dialog, because a window asking where to put a file has to say what
# put it there — it arrives while you are looking at a browser.
TITLE = 'Save from the analog chain calculator'


class NoDialog(Exception):
    """No dialog program is installed, so this machine cannot ask. Reported to
    the page as its own status, because the answer to it is the plain download
    rather than an error message."""


def token():
    """The secret the page carries and every request has to repeat.

    It is only a loopback port, but a loopback port is reachable from every
    page in the browser, and without this any of them could put a save dialog
    up in front of you. Confirming the dialog is still what writes the file —
    this is what stops the dialog appearing at all."""
    try:
        with open(TOKEN_FILE) as fh:
            existing = fh.read().strip()
        if existing:
            return existing
    except OSError:
        pass
    os.makedirs(CONFIG_DIR, exist_ok=True)
    value = secrets.token_hex(16)
    try:
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # A build and a launch racing for the first one. Whoever won wrote a
        # usable token; the loser reads it rather than overwriting it.
        with open(TOKEN_FILE) as fh:
            return fh.read().strip()
    with os.fdopen(fd, 'w') as fh:
        fh.write(value)
    return value


def remembered():
    """The folder last saved to, per file extension. Kept per extension
    because a chain file and a notebook are filed in different places, and one
    of them opening where the other went is a folder you have to leave every
    time."""
    try:
        with open(DIRS_FILE) as fh:
            saved = json.load(fh)
        return saved if isinstance(saved, dict) else {}
    except (OSError, ValueError):
        return {}


def remember(kind, directory):
    dirs = remembered()
    dirs[kind] = directory
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(DIRS_FILE, 'w') as fh:
        json.dump(dirs, fh, indent=2, sort_keys=True)


def opening_dir(kind):
    """Where the dialog opens: the folder this kind of file last went to,
    still there. The first save of all has nothing to go on, so it offers the
    browser's download folder — the place every file from this page has landed
    until now, which makes the first dialog show the old behaviour and lets you
    move from there."""
    directory = remembered().get(kind)
    if directory and os.path.isdir(directory):
        return directory
    home = os.path.expanduser('~')
    downloads = os.path.join(home, 'Downloads')
    return downloads if os.path.isdir(downloads) else home


def ask_where(directory, filename):
    """Put the desktop's save dialog up, seeded with `directory/filename`.
    Returns the chosen path, or None if it was cancelled."""
    start = os.path.join(directory, filename)

    if shutil.which('zenity'):
        argv = ['zenity', '--file-selection', '--save', '--confirm-overwrite',
                '--title', TITLE, f'--filename={start}']
        done = subprocess.run(argv, capture_output=True, text=True)
        if done.returncode not in (0, 1) and 'confirm-overwrite' in done.stderr:
            # zenity 4 dropped the flag (overwriting asks by default there).
            # Only this failure is retried: a dialog that failed for any other
            # reason would come back a second time in front of someone who has
            # already dealt with one.
            argv.remove('--confirm-overwrite')
            done = subprocess.run(argv, capture_output=True, text=True)
        if done.returncode == 0:
            return done.stdout.strip().splitlines()[0]
        if done.returncode == 1:
            return None                           # cancelled
        raise NoDialog(f'zenity failed: {done.stderr.strip() or done.returncode}')

    if shutil.which('kdialog'):
        done = subprocess.run(
            ['kdialog', '--title', TITLE, '--getsavefilename', start],
            capture_output=True, text=True)
        if done.returncode == 0:
            return done.stdout.strip().splitlines()[0]
        if done.returncode == 1:
            return None
        raise NoDialog('kdialog could not show a dialog')

    # Last resort, and in its own process: tkinter wants the main thread, and
    # the main thread here is serving HTTP.
    script = ('import sys, tkinter, tkinter.filedialog\n'
              'root = tkinter.Tk(); root.withdraw()\n'
              'print(tkinter.filedialog.asksaveasfilename('
              'initialdir=sys.argv[1], initialfile=sys.argv[2],'
              ' title=sys.argv[3]) or "", end="")\n')
    done = subprocess.run([sys.executable, '-c', script, directory, filename, TITLE],
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise NoDialog('no save dialog on this machine — install zenity '
                       '(or kdialog, or python3-tk)')
    return done.stdout.strip() or None


def save(text, filename):
    """Ask where this file goes, write it there, and remember the folder.
    Returns the path written, or None if the dialog was cancelled."""
    kind = os.path.splitext(filename)[1].lstrip('.').lower() or 'file'
    path = ask_where(opening_dir(kind), filename)
    if path is None:
        return None
    # A name typed without one gets the extension the page suggested: the
    # chain files this writes are loaded back by name, and a bare 'run3' is a
    # file the open dialog's .json filter then hides.
    if '.' not in os.path.basename(path):
        path += os.path.splitext(filename)[1]
    with open(path, 'w') as fh:
        fh.write(text)
    remember(kind, os.path.dirname(os.path.abspath(path)))
    return path


class Handler(http.server.BaseHTTPRequestHandler):
    """POST /save {token, filename, text} -> a dialog, then a file.

    The page is served from file://, whose origin is the string "null", so
    every reply says who may read it explicitly. The request itself is kept
    CORS-simple (a text/plain body) — a preflight would be a second exchange
    to get right for a body only this ever reads."""

    server_version = 'AnalogChainSaveHelper/1'
    protocol_version = 'HTTP/1.1'

    # One dialog at a time. Two open at once are indistinguishable on screen,
    # and the second answer would be given to whichever file the first dialog
    # was about.
    dialog = threading.Lock()

    def reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin',
                         self.headers.get('Origin', '*'))
        self.send_header('Vary', 'Origin')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin',
                         self.headers.get('Origin', '*'))
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        # Chrome asks this of anything reaching into a private network.
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Vary', 'Origin')
        self.end_headers()

    def do_GET(self):
        if self.path != '/alive':
            return self.reply(404, {'status': 'error', 'error': 'no such path'})
        self.reply(200, {'status': 'alive'})

    def do_POST(self):
        if self.path != '/save':
            return self.reply(404, {'status': 'error', 'error': 'no such path'})
        # Bound to loopback, so the only way to arrive under another Host is a
        # name that resolves here — which is how a page reaches a local server
        # it is not supposed to be able to name.
        host = self.headers.get('Host', '').split(':')[0]
        if host not in ('127.0.0.1', 'localhost', '[::1]', '::1'):
            return self.reply(403, {'status': 'error', 'error': 'bad host'})

        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            length = -1
        if not 0 < length <= MAX_BODY:
            return self.reply(413, {'status': 'error', 'error': 'bad length'})
        try:
            request = json.loads(self.rfile.read(length))
            filename = os.path.basename(str(request['filename']))
            text = request['text']
            given = str(request['token'])
        except (ValueError, KeyError, TypeError):
            return self.reply(400, {'status': 'error', 'error': 'bad request'})
        if not secrets.compare_digest(given, self.server.token):
            return self.reply(403, {'status': 'error', 'error': 'bad token'})
        if not isinstance(text, str) or not filename or filename.startswith('.'):
            return self.reply(400, {'status': 'error', 'error': 'bad file'})

        if not self.dialog.acquire(blocking=False):
            return self.reply(409, {'status': 'busy'})
        try:
            path = save(text, filename)
        except NoDialog as err:
            print(f'  no save dialog: {err}', flush=True)
            return self.reply(501, {'status': 'nodialog', 'error': str(err)})
        except OSError as err:
            print(f'  could not write: {err}', flush=True)
            return self.reply(500, {'status': 'error', 'error': str(err)})
        finally:
            self.dialog.release()

        if path is None:
            print(f'  {filename}: cancelled', flush=True)
            return self.reply(200, {'status': 'cancelled'})
        print(f'  wrote {path}', flush=True)
        self.reply(200, {'status': 'saved', 'path': path})

    def log_message(self, fmt, *args):
        """Quiet: this runs in the launcher's terminal, where a line per
        request would bury the build output above it. Saves and refusals print
        themselves."""


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, secret):
        super().__init__(('127.0.0.1', port), Handler)
        self.token = secret


def start(port=DEFAULT_PORT, secret=None):
    """A bound server, ready for serve_forever(), or None when the port is
    already taken — which on this machine means a helper from an earlier
    launch is still serving, and a second one would only fight it."""
    try:
        return Server(port, secret or token())
    except OSError as err:
        if err.errno == errno.EADDRINUSE:
            return None
        raise


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--port', type=int, default=DEFAULT_PORT)
    ap.add_argument('--token', help='override the shared secret (for tests)')
    args = ap.parse_args()

    server = start(args.port, args.token)
    if server is None:
        sys.exit(f'127.0.0.1:{args.port} is already taken — a save helper is '
                 f'probably running already')
    print(f'save helper on 127.0.0.1:{args.port} — Ctrl-C to stop', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nstopped')


if __name__ == '__main__':
    main()
