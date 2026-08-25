#!/usr/bin/env python3
"""Assemble the single-file browser build of the analog chain calculator.

    python3 tools/assemble_web.py [--out DIR] [--wheel PATH] [--preset KEY]

The deliverable is one HTML file that boots CPython in the browser (Pyodide),
installs the analog-chain-core wheel embedded in it, and drives it from a
JavaScript view. The physics is never reimplemented: the page's every number
comes from the same wheel a notebook installs.

web/template.html carries five markers, replaced with inlined payloads:

    <!--__PYODIDE_TAG__-->  the Pyodide loader (CDN tag, or inlined)
    /*__UPLOT_CSS__*/       web/vendor/uPlot.min.css
    /*__UPLOT_JS__*/        web/vendor/uPlot.iife.min.js
    /*__CONFIG__*/          build config as a JSON literal
    /*__WHEEL_B64__*/       the wheel, base64, inside a JS string literal

Checks, all of which write nothing if they fail: markers present and in source
order, no '</script' or '-->' inside any payload, the config is valid JSON, the
wheel is a real zip containing chain_api, and the page's own script block
parses (node, if available).

--offline is accepted and deliberately unimplemented; see the note below.
"""
import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Order matters: the assembler asserts the markers appear in this sequence, so
# a template edit that moves one is caught rather than silently reordering the
# payloads.
MARKERS = ['<!--__PYODIDE_TAG__-->', '/*__UPLOT_CSS__*/', '/*__UPLOT_JS__*/',
           '/*__CONFIG__*/', '/*__WHEEL_B64__*/']

# Pinned deliberately. A floating 'latest' would mean an artifact built today
# and opened next year silently runs a different numpy - which is exactly the
# staleness that makes an undated build untrustworthy as a record.
PYODIDE_VERSION = '0.27.7'
PYODIDE_INDEX = f'https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/'


def read(*parts, mode='r'):
    with open(os.path.join(ROOT, *parts), mode) as fh:
        return fh.read()


def git_sha():
    try:
        out = subprocess.run(['git', '-C', ROOT, 'describe', '--always', '--dirty'],
                             capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 'unknown'


def find_wheel(explicit):
    if explicit:
        return explicit
    dist = os.path.join(ROOT, 'dist')
    wheels = sorted(f for f in os.listdir(dist) if f.endswith('.whl')) \
        if os.path.isdir(dist) else []
    if not wheels:
        sys.exit("no wheel found in dist/ — build one first:\n"
                 "    python -m pip wheel . --no-deps -w dist/")
    if len(wheels) > 1:
        sys.exit(f"several wheels in dist/ ({', '.join(wheels)}); "
                 f"pass --wheel to choose one")
    return os.path.join(dist, wheels[0])


def check_wheel(path):
    """A wheel that installs but lacks chain_api produces a page that boots and
    then fails on its first call, which is a much worse failure than not
    building. Verify the contents before embedding."""
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        bad = zf.testzip()
    if bad is not None:
        sys.exit(f'wheel is corrupt at {bad}')
    required = {'chain_api.py', 'signal_chain.py', 'registry.py',
                'hardware_models.py', 'component.py', 'noise_budget.py', 'utils.py'}
    missing = required - set(names)
    if missing:
        sys.exit(f'wheel is missing {sorted(missing)} — check '
                 f'[tool.setuptools] py-modules in pyproject.toml')
    return names


def page_script(html):
    """The page's own script is the last <script> block without a src."""
    blocks = re.findall(r'<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)</script>', html)
    if not blocks:
        sys.exit('no inline script block found in the assembled page')
    return blocks[-1]


def check_syntax(script):
    node = shutil.which('node')
    if node is None:
        return 'skipped (node not installed)'
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False) as fh:
        fh.write(script)
        path = fh.name
    try:
        result = subprocess.run([node, '--check', path],
                                capture_output=True, text=True)
        if result.returncode != 0:
            sys.exit(f'assembled page script is not valid JS:\n{result.stderr}')
        return 'OK'
    finally:
        os.unlink(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(ROOT, 'dist'))
    ap.add_argument('--wheel', help='wheel to embed (default: the one in dist/)')
    ap.add_argument('--preset', default='cryo_example',
                    help='preset the page opens on')
    ap.add_argument('--name', default='analog_chain_calculator.html')
    ap.add_argument('--offline', action='store_true',
                    help='not implemented; see the note in this file')
    args = ap.parse_args()

    if args.offline:
        # The thin build needs the network once and is ~100 KB. A genuinely
        # offline build has to inline the Pyodide runtime, the stdlib archive
        # and the numpy/scipy wheels (tens of MB) AND shim fetch/XHR so the
        # loader reads them from the page instead of the network. That is a
        # real piece of work and it belongs in its own change, not bolted on
        # here where it would be untested.
        sys.exit('--offline is not implemented yet; the thin build needs the '
                 'network on first open. Build without --offline.')

    template = read('web', 'template.html')
    positions = []
    for marker in MARKERS:
        if marker not in template:
            sys.exit(f'template is missing marker {marker}')
        positions.append(template.index(marker))
    if positions != sorted(positions):
        sys.exit(f'markers are out of source order: '
                 f'{list(zip(MARKERS, positions))}')

    wheel_path = find_wheel(args.wheel)
    check_wheel(wheel_path)
    wheel_bytes = read(os.path.relpath(wheel_path, ROOT), mode='rb') \
        if not os.path.isabs(wheel_path) else open(wheel_path, 'rb').read()
    wheel_b64 = base64.b64encode(wheel_bytes).decode('ascii')

    config = {
        'wheel_name': os.path.basename(wheel_path),
        'pyodide_index': PYODIDE_INDEX,
        'pyodide_version': PYODIDE_VERSION,
        'default_preset': args.preset,
        'built_at': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
        'git_sha': git_sha(),
        'offline': False,
    }
    config_json = json.dumps(config, indent=2)
    json.loads(config_json)                       # must be a valid JSON literal

    payloads = {
        '<!--__PYODIDE_TAG__-->':
            f'<script src="{PYODIDE_INDEX}pyodide.js"></script>',
        '/*__UPLOT_CSS__*/': read('web', 'vendor', 'uPlot.min.css'),
        '/*__UPLOT_JS__*/': read('web', 'vendor', 'uPlot.iife.min.js'),
        '/*__CONFIG__*/': config_json,
        '/*__WHEEL_B64__*/': wheel_b64,
    }

    # What must not appear depends on where the payload lands: a sequence that
    # closes the enclosing element early gives a page that loads and is
    # silently broken. The Pyodide payload is itself a <script> tag, so it is
    # the one marker for which '</script' is correct rather than fatal.
    forbidden = {
        '<!--__PYODIDE_TAG__-->': ('-->',),
        '/*__UPLOT_CSS__*/': ('</style',),
        '/*__UPLOT_JS__*/': ('</script',),
        '/*__CONFIG__*/': ('</script',),
        # This one lands inside a double-quoted JS string literal, so a quote,
        # a backslash or a newline would break out of it. Base64 cannot
        # produce any of them, which is exactly why it is asserted.
        '/*__WHEEL_B64__*/': ('</script', '"', '\\', '\n'),
    }
    assert set(forbidden) == set(MARKERS), 'forbidden-sequence table is out of date'
    for marker, sequences in forbidden.items():
        for sequence in sequences:
            if sequence in payloads[marker]:
                sys.exit(f'{sequence!r} inside the {marker} payload')

    page = template
    for marker in MARKERS:
        index = page.index(marker)
        page = page[:index] + payloads[marker] + page[index + len(marker):]
    for marker in MARKERS:
        if marker in page:
            sys.exit(f'{marker} still present after substitution')

    syntax = check_syntax(page_script(page))

    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, args.name)
    with open(out_path, 'w') as fh:
        fh.write(page)

    print(f'{out_path}')
    print(f'  {os.path.getsize(out_path)/1e3:.1f} KB  '
          f'(wheel {len(wheel_bytes)/1e3:.1f} KB -> {len(wheel_b64)/1e3:.1f} KB base64)')
    print(f'  pyodide {PYODIDE_VERSION} from CDN, preset {args.preset!r}, '
          f'{config["git_sha"]}')
    print(f'  page script syntax: {syntax}')


if __name__ == '__main__':
    main()
