"""Run Qt's native Windows renderer at the requested DPI scale factors."""
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
results = []
for scale in (1, 1.25, 1.5, 1.75, 2):
    env = dict(os.environ, QT_SCALE_FACTOR=str(scale))
    env.pop('QT_QPA_PLATFORM', None)
    output = root / 'build' / f'qt-dpi-{int(scale * 100)}'
    result = subprocess.run([sys.executable, str(root / 'app.py'), '--smoke-test', str(output)],
                            env=env, capture_output=True, text=True, timeout=60,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    report = json.loads((output / 'report.json').read_text())
    assert len(report['pages']) == 8
    assert report['sidebar_width'] == 150
    assert report['qwindows_present']
    assert not report['tk_loaded']
    results.append({'scale': scale, **report})
    print(f"DPI {scale}: native Qt platform={report['platform']}; eight pages rendered; qwindows.dll present", flush=True)
(root / 'build' / 'qt-dpi-report.json').write_text(json.dumps(results, indent=2))
