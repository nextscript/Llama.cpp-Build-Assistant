"""Validate a frozen Windows executable without touching the user's settings."""
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
exe = Path(sys.argv[1]).resolve()
output = root / 'build' / 'qt-frozen-smoke'
user_data = root / 'build' / 'qt-frozen-user'
env = dict(os.environ, LOCALAPPDATA=str(user_data))
env.pop('QT_QPA_PLATFORM', None)
process = subprocess.run([str(exe), '--smoke-test', str(output)], env=env, timeout=90,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
assert process.returncode == 0, process.returncode
report = json.loads((output / 'report.json').read_text())
assert report['platform'] == 'windows'
assert report['qwindows_present']
assert not report['tk_loaded']
assert len(report['pages']) == 8
print(f"Frozen smoke test passed: {exe.name}; native Windows platform; eight pages; no Tk loaded")
