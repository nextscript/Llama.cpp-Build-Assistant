"""Application updates, extracted from the GUI into a background service."""
import json
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath
from packaging.version import Version
from config import ROOT_DIR, BUNDLE_DIR

API = 'https://api.github.com/repos/nextscript/Llama.cpp-Build-Assistant'
RELEASES = 'https://github.com/nextscript/Llama.cpp-Build-Assistant/releases/latest'


def request(path, raw=False):
    headers = {'User-Agent': 'LlamaCppBuildAssistant',
               'Accept': 'application/vnd.github.v3.raw' if raw else 'application/vnd.github+json'}
    with urllib.request.urlopen(urllib.request.Request(API + path, headers=headers), timeout=30) as response:
        data = response.read()
    return data if raw else json.loads(data)


def local_version():
    try:
        return (Path(BUNDLE_DIR) / 'VERSION').read_text(encoding='utf-8').strip()
    except OSError:
        return '0.0.0'


def check_update(log):
    remote = request('/contents/VERSION?ref=main', True).decode().strip()
    local = local_version()
    result = dict(local=local, remote=remote, available=Version(remote.lstrip('v')) > Version(local.lstrip('v')),
                  files=[], message=f'Update to v{remote}')
    if not result['available']:
        return result
    try:
        sha = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT_DIR, capture_output=True,
                             text=True, timeout=5, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if sha.returncode == 0:
            comparison = request(f'/compare/{sha.stdout.strip()}...main')
            result['files'] = [f['filename'] for f in comparison.get('files', []) if f.get('status') != 'removed']
            commits = comparison.get('commits', [])
            if commits:
                result['message'] = commits[-1]['commit']['message'].split('\n')[0]
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return result


def update_files(files, log):
    if not files:
        files = [item['path'] for item in request('/git/trees/main?recursive=1')['tree'] if item['type'] == 'blob']
    root = Path(ROOT_DIR).resolve()
    # Stage all downloads before replacing files. Keep backups for rollback.
    staged = []
    with tempfile.TemporaryDirectory(prefix='.app-update-', dir=root) as temporary:
        staging = Path(temporary)
        for index, filename in enumerate(files, 1):
            relative = PurePosixPath(filename)
            if relative.is_absolute() or any(part in ('..', '.git') or ':' in part or '\\' in part for part in relative.parts):
                raise ValueError(f'Invalid update path: {filename}')
            target = (root / filename).resolve()
            if not target.is_relative_to(root):
                raise ValueError(f'Invalid update path: {filename}')
            if relative.parts and relative.parts[0] in ('data', 'logs', 'builds', 'repos'):
                log(f'Preserving user data: {filename}')
                continue
            log(f'[{index}/{len(files)}] Downloading: {filename}...')
            content = request('/contents/' + urllib.parse.quote(filename) + '?ref=main', True)
            stage = staging / str(index)
            stage.write_bytes(content)
            backup = staging / (str(index) + '.backup')
            if target.exists():
                backup.write_bytes(target.read_bytes())
            staged.append((target, stage, backup))
        applied = []
        try:
            for target, stage, backup in staged:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(stage, target)
                applied.append((target, backup))
        except OSError:
            for target, backup in reversed(applied):
                if backup.exists():
                    os.replace(backup, target)
                else:
                    target.unlink(missing_ok=True)
            raise
    log('Update complete. Please restart the application to apply changes.')
    return len(staged)
