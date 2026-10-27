"""Build and sign with Kevin's installed official Tizen SDK (macOS)."""
from pathlib import Path
import os
import pty
import select
import signal
import subprocess
import time
import xml.etree.ElementTree as XML
import zipfile
from font_assets import write_widget_archive

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / '.local/certificates/private'
sdk_override = os.environ.get('CLEANFRAME_TIZEN_SDK')
sdk_candidates = [Path(sdk_override).expanduser()] if sdk_override else [Path('/Users/kplumlee/tizen-studio'), ROOT / '.local/tizen-sdk']
SDK = next((candidate for candidate in sdk_candidates if (candidate / 'tools/ide/bin/tizen').is_file()), sdk_candidates[0])
CLI = SDK / 'tools/ide/bin/tizen'
profile_name = os.environ.get('CLEANFRAME_SIGNING_PROFILE', 'KevinQN90D')
if not CLI.exists():
    raise SystemExit('Official Tizen SDK missing. Set CLEANFRAME_TIZEN_SDK to its installed path.')
sdk_info = SDK / 'sdk.info'
sdk_data = None
if sdk_info.is_file():
    for line in sdk_info.read_text().splitlines():
        if line.startswith('TIZEN_SDK_DATA_PATH='):
            sdk_data = Path(line.split('=', 1)[1]).expanduser()
            break
profile_override = os.environ.get('CLEANFRAME_TIZEN_PROFILE_PATH')
profile_candidates = [Path(profile_override).expanduser()] if profile_override else [
    sdk_data / 'profile/profiles.xml' if sdk_data else PRIVATE / 'profiles.xml',
    PRIVATE / 'profiles.xml'
]
profile = next((candidate for candidate in profile_candidates if candidate.is_file()), profile_candidates[0])
password_file = Path(os.environ.get('CLEANFRAME_SIGNING_PASSWORD_FILE', PRIVATE / 'certificate-password.txt')).expanduser()
if not profile.exists():
    raise SystemExit('Kevin\'s Samsung signing profile is missing. Complete the certificate workflow first.')
# Certificate Manager stores the profile credentials in the SDK profile. A local
# password file is optional for command-line-only profiles that still prompt.
password = password_file.read_bytes().strip() if password_file.exists() else None
if password == b'':
    raise SystemExit('Signing password file is empty.')
dist = ROOT / 'dist'
dist.mkdir(exist_ok=True)
tree = XML.parse(profile)
profiles = {item.get('name') for item in tree.getroot().iter('profile')}
if profile_name not in profiles:
    raise SystemExit('CLEANFRAME_SIGNING_PROFILE does not exist in Kevin\'s local profiles.xml.')
result = subprocess.run([str(CLI), 'cli-config', 'default.profiles.path=' + str(profile)], capture_output=True, timeout=30)
if result.returncode:
    raise SystemExit('SDK signing profile configuration failed.')
unsigned = dist / 'CleanFrame-unsigned.wgt'
write_widget_archive(unsigned)
signed_dir = dist / 'signed'
signed_dir.mkdir(exist_ok=True)
command = [str(CLI), 'package', '-t', 'wgt', '-s', profile_name, '-o', str(signed_dir), '--', str(unsigned)]
pid, terminal = pty.fork()
if pid == 0:
    os.execv(command[0], command)
output = b''
passwords = saves = 0
missing_password = False
deadline = time.monotonic() + 60
try:
    while time.monotonic() < deadline:
        ready, _, _ = select.select([terminal], [], [], 1)
        if ready:
            try:
                chunk = os.read(terminal, 8192)
            except OSError:
                break
            if not chunk:
                break
            output += chunk
            count = output.lower().count(b'password:')
            if count > passwords:
                if password is None:
                    missing_password = True
                    os.kill(pid, signal.SIGTERM)
                    break
                os.write(terminal, password + b'\n')
                passwords = count
            count = output.count(b'No: (N) ?')
            if count > saves:
                os.write(terminal, b'n\n')
                saves = count
    else:
        os.kill(pid, signal.SIGTERM)
        raise SystemExit('SDK signing timed out.')
finally:
    os.close(terminal)
os.waitpid(pid, 0)
redacted = output.replace(password, b'[redacted]').decode(errors='replace') if password else output.decode(errors='replace')
if missing_password:
    raise SystemExit('SDK requested a signing password. Recreate or repair the Certificate Manager profile, or set CLEANFRAME_SIGNING_PASSWORD_FILE to a private password file.')
if 'is created successfully' not in redacted:
    print(redacted)
    raise SystemExit('SDK did not confirm a signed package.')
signed = signed_dir / unsigned.name
with zipfile.ZipFile(signed) as package:
    if not {'author-signature.xml', 'signature1.xml'}.issubset(package.namelist()):
        raise SystemExit('Package is missing its signing files.')
target = dist / 'CleanFrame.wgt'
target.write_bytes(signed.read_bytes())
print('Signed widget created: ' + str(target))
