"""Connect, inspect, install or launch CleanFrame. These commands preserve Home/startup settings."""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as XML

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['info', 'install', 'launch'])
parser.add_argument('--host')
parser.add_argument('--sdb-target', help='Use an already connected SDB serial, such as a local relay.')
args = parser.parse_args()
config_file = ROOT / '.local/device.json'
config = json.loads(config_file.read_text()) if config_file.exists() else {}
host = args.host or config.get('host')
sdb_target = args.sdb_target or os.environ.get('CLEANFRAME_SDB_TARGET') or config.get('sdbTarget')
if sdb_target:
    serial = sdb_target
else:
    if not host:
        raise SystemExit('Add the TV address to .local/device.json, pass --host, or provide --sdb-target.')
    ipaddress.ip_address(host)
    serial = host + ':26101'

sdk_override = os.environ.get('CLEANFRAME_TIZEN_SDK')
sdk_candidates = [Path(sdk_override).expanduser()] if sdk_override else [
    ROOT / '.local/tizen-sdk',
    Path('/Users/kplumlee/tizen-studio'),
]
sdb = next((candidate / 'tools/sdb' for candidate in sdk_candidates if (candidate / 'tools/sdb').is_file()), None)
if not sdb:
    raise SystemExit('Official SDB tool missing. Set CLEANFRAME_TIZEN_SDK or see docs/development.md.')
manifest = XML.parse(ROOT / 'app/config.xml').getroot()
app_id = manifest.find('{http://tizen.org/ns/widgets}application').get('id')


def run(*command, quiet=False):
    result = subprocess.run([str(sdb), *command], text=True, capture_output=True, timeout=45)
    output = result.stdout + result.stderr
    if not quiet:
        print(output, end='' if output.endswith('\n') else '\n', flush=True)
    if result.returncode:
        raise SystemExit('SDB command failed.')
    return output

if sdb_target:
    state = run('-s', serial, 'get-state', quiet=True).strip()
    if state != 'device':
        raise SystemExit('Existing SDB target is not connected as a device.')
else:
    connected = run('connect', serial)
    if 'connected to ' not in connected.lower() and 'already connected' not in connected.lower():
        raise SystemExit('TV connection was not confirmed.')
if args.action == 'info':
    run('-s', serial, 'capability')
elif args.action == 'launch':
    output = run('-s', serial, 'shell', '0', 'execute', app_id)
    if 'successfully launched' not in output:
        raise SystemExit('App launch was not confirmed. Check the TV.')
else:
    widget = ROOT / 'dist/CleanFrame.wgt'
    if not widget.exists():
        raise SystemExit('Run npm run package first.')
    digest = hashlib.sha256(widget.read_bytes()).hexdigest()[:12]
    remote = '/home/owner/share/tmp/sdk_tools/CleanFrame-' + digest + '-' + str(time.time_ns()) + '.wgt'
    pushed = run('-s', serial, 'push', str(widget), remote)
    if '1 file(s) pushed' not in pushed or 'failed' in pushed.lower():
        raise SystemExit('Widget transfer was not confirmed.')
    output = run('-s', serial, 'shell', '0', 'vd_appinstall', app_id, remote)
    if 'install completed' not in output or 'install failed' in output:
        raise SystemExit('TV installation failed or was not confirmed.')
    installed = run('-s', serial, 'shell', '0', 'applist', quiet=True)
    if app_id not in installed:
        raise SystemExit('App was not found in the installed-app list.')
    print('CleanFrame installation confirmed. Startup defaults are unchanged.')
