#!/usr/bin/env python3
"""Build the browser GUI if it is out of date, then open it.

    ./open_web_gui.py              build if stale, open in the browser
    ./open_web_gui.py --force      rebuild both stages unconditionally
    ./open_web_gui.py --no-open    build only, print the path
    ./open_web_gui.py --desktop    install a double-clickable desktop entry

The two-stage build (`pip wheel` then `tools/assemble_web.py`) is documented in
web/README.md and is still the thing to run when you care which stage ran. This
is the shortcut: one entry point that works out which stages are needed.

Staleness is decided from mtimes, and the wheel's own contents decide what
counts as a source for it — whatever .py files are inside the wheel are the ones
compared against it. That way adding a module to `py-modules` in pyproject.toml
does not also have to be recorded here. The revision the page records is
checked too, so a `git pull` rebuilds even if it moved a file no list here
names: after pulling, launching is the whole update procedure.

Launched from the desktop entry there is no terminal to print to, so in that
case a failure is also shown in a dialog and the build output is kept in
dist/last-build.log. Otherwise a double-click that cannot build looks exactly
like a double-click that did nothing.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import webbrowser
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, 'dist')
PAGE = os.path.join(DIST, 'analog_chain_calculator.html')
ICON = os.path.join(ROOT, 'web', 'icon.svg')
# Where a failing build step's output is kept, for the launches that have no
# terminal to write it to.
LOG = os.path.join(DIST, 'last-build.log')

# Set in main(): true when this run has to report through the desktop rather
# than through stdout. Module scope because run() is where failures surface.
GUI = False
ANNOUNCED = False

# Sources for the assembly stage. The wheel is added at run time, since its
# filename carries the version.
PAGE_SOURCES = [
    os.path.join(ROOT, 'web', 'template.html'),
    os.path.join(ROOT, 'web', 'vendor', 'uPlot.min.css'),
    os.path.join(ROOT, 'web', 'vendor', 'uPlot.iife.min.js'),
    os.path.join(ROOT, 'tools', 'assemble_web.py'),
]


def desktop_launch():
    """True when this run has no terminal to print to but does have a desktop
    to put a window on — which is what being started from the applications
    menu looks like from in here."""
    return not sys.stdout.isatty() and bool(
        os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))


def first_available(*commands):
    """Run the first of these command lines whose program is installed. None of
    them is required: they are how the machine happens to show messages, and a
    machine that shows none still has stdout and the log file."""
    for argv in commands:
        if shutil.which(argv[0]):
            subprocess.run(argv, capture_output=True)
            return True
    return False


def show_error(message):
    # 'see above' is the right thing to say to a terminal and a dead end in a
    # dialog, where the only 'above' the reader has is the log file.
    body = message.replace('see above', 'see the log below') + \
        f'\n\nBuild output: {LOG}'
    first_available(
        ['zenity', '--error', '--no-wrap', '--title', 'Analog Chain Calculator',
         '--text', body],
        ['kdialog', '--title', 'Analog Chain Calculator', '--error', body],
        ['xmessage', '-center', f'Analog Chain Calculator\n\n{body}'],
        ['notify-send', '-u', 'critical', 'Analog Chain Calculator', body],
    )


def announce_build():
    """Say that a rebuild has started, once per run. Three seconds of nothing
    after a double-click reads as a launcher that did not work, and the answer
    people reach for is to double-click again."""
    global ANNOUNCED
    if GUI and not ANNOUNCED:
        ANNOUNCED = True
        first_available(['notify-send', '-t', '5000', '-i', ICON,
                         'Analog Chain Calculator',
                         'Updating to match your checkout…'])


def git_sha():
    """The revision checked out now, or None if git cannot say — an export with
    no .git, say, which is then left to the mtime checks alone."""
    try:
        out = subprocess.run(['git', '-C', ROOT, 'describe', '--always', '--dirty'],
                             capture_output=True, text=True, check=True)
        return out.stdout.strip() or None
    except (subprocess.CalledProcessError, OSError):
        return None


def page_sha():
    """The revision the assembler recorded in the built page's config."""
    if not os.path.exists(PAGE):
        return None
    with open(PAGE) as fh:
        match = re.search(r'"git_sha":\s*"([^"]*)"', fh.read())
    return match.group(1) if match and match.group(1) != 'unknown' else None


def newer_than(target, sources):
    """Sources modified after target, as repo-relative paths."""
    if not os.path.exists(target):
        return ['(missing)']
    cutoff = os.path.getmtime(target)
    return [os.path.relpath(s, ROOT) for s in sources
            if os.path.exists(s) and os.path.getmtime(s) > cutoff]


def wheel_paths():
    return sorted(os.path.join(DIST, f) for f in os.listdir(DIST)
                  if f.endswith('.whl')) if os.path.isdir(DIST) else []


def find_wheel():
    """The single wheel in dist/, or None. Several is still not a thing to
    guess between — embedding the wrong version gives a page that works and
    reports numbers from code you are not looking at — but by here one has just
    been built and the rest pruned, so it is an invariant check."""
    wheels = wheel_paths()
    if len(wheels) > 1:
        sys.exit(f"several wheels in dist/ "
                 f"({', '.join(os.path.basename(w) for w in wheels)}) — remove "
                 f"the stale one, or run tools/assemble_web.py --wheel to choose")
    return wheels[0] if wheels else None


def prune_wheels():
    """Keep only the wheel just written. `pip wheel` writes a new file when the
    version changes instead of replacing the old one, and find_wheel() refuses
    to choose between two — so without this the first version bump after a pull
    wedges every later launch, complaining to a terminal nobody is looking at.
    Newest-by-mtime is the one pip just produced."""
    wheels = sorted(wheel_paths(), key=os.path.getmtime)
    for path in wheels[:-1]:
        os.remove(path)
        print(f'  removed superseded wheel {os.path.basename(path)}')


def wheel_sources(wheel):
    """The repo files the wheel was built from: its own top-level modules, plus
    the packaging metadata that decides which modules those are."""
    with zipfile.ZipFile(wheel) as zf:
        modules = [n for n in zf.namelist()
                   if n.endswith('.py') and '/' not in n]
    return [os.path.join(ROOT, m) for m in modules] + \
           [os.path.join(ROOT, 'pyproject.toml')]


def run(step, argv):
    announce_build()
    # Flushed, because the failure branch below writes the subprocess's
    # diagnostics to stderr and they have to land after this line, not before
    # it, when stdout is a pipe.
    print(f'  {step}', flush=True)
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stdout.write(result.stdout)
        sys.stdout.flush()
        sys.stderr.write(result.stderr)
        os.makedirs(DIST, exist_ok=True)
        with open(LOG, 'w') as fh:
            fh.write(f"$ {' '.join(argv)}\n\n{result.stdout}\n{result.stderr}")
        sys.exit(f'\n{step} failed — see above. The documented manual build is '
                 f'in web/README.md.')
    return result.stdout


def build_wheel():
    run('building the wheel (pip wheel . --no-deps)',
        [sys.executable, '-m', 'pip', 'wheel', '.', '--no-deps', '-w', DIST])
    prune_wheels()
    wheel = find_wheel()
    if wheel is None:
        sys.exit('pip reported success but wrote no wheel to dist/')
    return wheel


def assemble(wheel):
    out = run('assembling the page (tools/assemble_web.py)',
              [sys.executable, os.path.join('tools', 'assemble_web.py'),
               '--wheel', wheel])
    for line in out.splitlines():
        print(f'  {line.strip()}' if line.strip() else '')


def install_desktop_entry():
    """Write a desktop entry so the page can be launched by double-click. It
    holds absolute paths, so it is generated here rather than committed."""
    directory = os.path.join(os.path.expanduser('~'), '.local', 'share',
                             'applications')
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, 'analog-chain-calculator.desktop')
    with open(path, 'w') as fh:
        fh.write('[Desktop Entry]\n'
                 'Type=Application\n'
                 'Name=Analog Chain Calculator\n'
                 'Comment=RF signal chain gain and noise calculator\n'
                 f'Exec={sys.executable} {os.path.join(ROOT, os.path.basename(__file__))}\n'
                 f'Path={ROOT}\n'
                 f'Icon={ICON}\n'
                 'Terminal=false\n'
                 # So the desktop shows the launch as pending while a rebuild
                 # runs, instead of nothing happening for a few seconds.
                 'StartupNotify=true\n'
                 'Categories=Science;Engineering;\n')
    os.chmod(path, 0o755)
    print(f'wrote {path}')
    print('  Launch it as "Analog Chain Calculator" from your applications '
          'menu, or double-click that file.')
    print('  Only needed once: the entry runs this launcher, which rebuilds '
          'whatever a `git pull` changed before opening the page.')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--force', action='store_true',
                    help='rebuild the wheel and the page even if both are current')
    ap.add_argument('--no-open', action='store_true',
                    help='build only; print the path instead of opening it')
    ap.add_argument('--desktop', action='store_true',
                    help='install a desktop entry and exit')
    args = ap.parse_args()

    global GUI
    GUI = desktop_launch() and not args.no_open

    if args.desktop:
        install_desktop_entry()
        return

    # The revision the page was built from against the one checked out now.
    # The mtime checks below catch an edited file, but they only compare the
    # sources someone remembered to list; a pull is a whole-checkout change,
    # so take a moved revision as stale regardless of what it touched.
    revision, built_from = git_sha(), page_sha()
    moved = (f'checkout is at {revision}, page was built from {built_from}'
             if revision and built_from and revision != built_from else None)

    # Several wheels means a version bump left the superseded one behind, from
    # a build before prune_wheels() existed. Rebuilding settles it — pip writes
    # the version the checkout asks for and the prune drops the others — which
    # is better than stopping to ask, since the launch that has to ask is the
    # one with no terminal to ask in.
    wheels = wheel_paths()
    if args.force or len(wheels) != 1:
        if len(wheels) > 1:
            print(f'  {len(wheels)} wheels in dist/ — rebuilding to settle '
                  f'which one the checkout wants')
        wheel = build_wheel()
    else:
        wheel = wheels[0]
        changed = ([moved] if moved else []) + newer_than(wheel, wheel_sources(wheel))
        if changed:
            print(f'  wheel is stale ({", ".join(changed[:3])}'
                  f'{" +more" if len(changed) > 3 else ""})')
            wheel = build_wheel()

    changed = newer_than(PAGE, PAGE_SOURCES + [wheel])
    if args.force or changed:
        if not args.force and changed != ['(missing)']:
            print(f'  page is stale ({", ".join(changed[:3])}'
                  f'{" +more" if len(changed) > 3 else ""})')
        assemble(wheel)
    else:
        print(f'  {os.path.relpath(PAGE, ROOT)} is up to date')

    if args.no_open:
        print(PAGE)
        return

    # The page fetches Pyodide from a CDN the first time it is opened; after
    # that the browser cache serves it.
    if webbrowser.open(f'file://{PAGE}'):
        print(f'\nopened {os.path.relpath(PAGE, ROOT)} '
              f'(needs the network on first open)')
    else:
        print(f'\nno browser could be launched — open this file yourself:\n'
              f'  file://{PAGE}')


if __name__ == '__main__':
    try:
        main()
    except SystemExit as exc:
        # sys.exit(str) is how every failure above is reported. With no
        # terminal that message is lost, so repeat it where it can be seen.
        if GUI and isinstance(exc.code, str):
            show_error(exc.code.strip())
        raise
