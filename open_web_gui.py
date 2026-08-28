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
does not also have to be recorded here.
"""
import argparse
import os
import subprocess
import sys
import webbrowser
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, 'dist')
PAGE = os.path.join(DIST, 'analog_chain_calculator.html')
ICON = os.path.join(ROOT, 'web', 'icon.svg')

# Sources for the assembly stage. The wheel is added at run time, since its
# filename carries the version.
PAGE_SOURCES = [
    os.path.join(ROOT, 'web', 'template.html'),
    os.path.join(ROOT, 'web', 'vendor', 'uPlot.min.css'),
    os.path.join(ROOT, 'web', 'vendor', 'uPlot.iife.min.js'),
    os.path.join(ROOT, 'tools', 'assemble_web.py'),
]


def newer_than(target, sources):
    """Sources modified after target, as repo-relative paths."""
    if not os.path.exists(target):
        return ['(missing)']
    cutoff = os.path.getmtime(target)
    return [os.path.relpath(s, ROOT) for s in sources
            if os.path.exists(s) and os.path.getmtime(s) > cutoff]


def find_wheel():
    """The single wheel in dist/, or None. Several wheels is an error rather
    than a guess: embedding the wrong version gives a page that works and
    reports numbers from code you are not looking at."""
    wheels = sorted(f for f in os.listdir(DIST) if f.endswith('.whl')) \
        if os.path.isdir(DIST) else []
    if len(wheels) > 1:
        sys.exit(f"several wheels in dist/ ({', '.join(wheels)}) — remove the "
                 f"stale one, or run tools/assemble_web.py --wheel to choose")
    return os.path.join(DIST, wheels[0]) if wheels else None


def wheel_sources(wheel):
    """The repo files the wheel was built from: its own top-level modules, plus
    the packaging metadata that decides which modules those are."""
    with zipfile.ZipFile(wheel) as zf:
        modules = [n for n in zf.namelist()
                   if n.endswith('.py') and '/' not in n]
    return [os.path.join(ROOT, m) for m in modules] + \
           [os.path.join(ROOT, 'pyproject.toml')]


def run(step, argv):
    # Flushed, because the failure branch below writes the subprocess's
    # diagnostics to stderr and they have to land after this line, not before
    # it, when stdout is a pipe.
    print(f'  {step}', flush=True)
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stdout.write(result.stdout)
        sys.stdout.flush()
        sys.stderr.write(result.stderr)
        sys.exit(f'\n{step} failed — see above. The documented manual build is '
                 f'in web/README.md.')
    return result.stdout


def build_wheel():
    run('building the wheel (pip wheel . --no-deps)',
        [sys.executable, '-m', 'pip', 'wheel', '.', '--no-deps', '-w', DIST])
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
                 'Categories=Science;Engineering;\n')
    os.chmod(path, 0o755)
    print(f'wrote {path}')
    print('  Launch it as "Analog Chain Calculator" from your applications '
          'menu, or double-click that file.')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--force', action='store_true',
                    help='rebuild the wheel and the page even if both are current')
    ap.add_argument('--no-open', action='store_true',
                    help='build only; print the path instead of opening it')
    ap.add_argument('--desktop', action='store_true',
                    help='install a desktop entry and exit')
    args = ap.parse_args()

    if args.desktop:
        install_desktop_entry()
        return

    wheel = find_wheel()
    if args.force or wheel is None:
        wheel = build_wheel()
    else:
        changed = newer_than(wheel, wheel_sources(wheel))
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
    main()
