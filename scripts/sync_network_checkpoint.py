"""Save reviewed local progress to the shared project without mirror deletion.

Existing files are replaced only when they still match this checkout's Git base
or the last successful checkpoint. Every replacement has a recoverable backup.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {'src', 'web', 'scripts', 'tests', 'docs', 'research', 'native_probe'}
TOP_FILES = {'HANDOFF.md', 'README.md', 'pyproject.toml', '.gitignore',
             'requirements-windows-py312.lock.txt'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def checked_relative(name):
    path = PurePosixPath(name.replace('\\', '/'))
    if not path.parts or path.is_absolute() or any(part in {'..', ''} for part in path.parts) or ':' in str(path):
        raise ValueError('Expected a project-relative file: ' + name)
    if str(path) not in TOP_FILES and path.parts[0] not in ALLOWED:
        if not (path.parts[0] == 'reports' and path.suffix.lower() in {'.json', '.md', '.jpg', '.png', '.html', '.csv'}):
            raise ValueError('File is outside checkpoint code/document/evidence scope: ' + name)
    if any(part in {'.git', '.venv', '__pycache__', 'node_modules'} for part in path.parts):
        raise ValueError('Runtime directories are not checkpoint artifacts')
    return str(path)


def within(root, relative):
    result = (root / relative).resolve()
    if not result.is_relative_to(root):
        raise ValueError('Resolved file escapes checkpoint root: ' + relative)
    return result


def git_run(git, *args, check=True):
    return subprocess.run([git, *args], cwd=ROOT, capture_output=True, check=check)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, default=Path(r'P:\revopoint software'))
    parser.add_argument('--git', default=shutil.which('git'))
    parser.add_argument('--include', action='append', default=[])
    parser.add_argument('--changed', action='store_true', help='Include current changed/untracked code and documents')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not args.git:
        parser.error('Supply --git with the installed Git executable')
    target = args.target.resolve(strict=True)
    if target == ROOT or target.is_relative_to(ROOT) or ROOT.is_relative_to(target):
        parser.error('The destination must be a separate existing project directory')
    base = git_run(args.git, 'rev-parse', 'HEAD').stdout.decode().strip()
    names = list(args.include)
    if args.changed:
        for command in [('diff', '--name-only', '-z', 'HEAD'), ('ls-files', '--others', '--exclude-standard', '-z')]:
            names += [name.decode('utf-8') for name in git_run(args.git, *command).stdout.split(b'\0') if name]
    names = sorted({checked_relative(name) for name in names})
    if not names:
        parser.error('Specify --include or --changed; no files were selected')
    cache = ROOT / '.cache/continuation-sync'
    cache.mkdir(parents=True, exist_ok=True)
    manifest_path = cache / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.is_file() else {'files': {}}
    if manifest.get('target') not in {None, str(target)}:
        parser.error('Existing checkpoint manifest belongs to a different destination')
    manifest['target'] = str(target)
    checkpoint = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
    backup = target / '.cache/continuation-sync' / checkpoint
    rows = []
    for relative in names:
        row = {'path': relative}
        try:
            source = within(ROOT, relative)
            destination = within(target, relative)
            if not source.is_file():
                raise ValueError('Local file is absent; checkpoint never propagates deletions')
            before = source.stat()
            content = source.read_bytes()
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError('Local file changed while being captured; retry after editing stops')
            local_sha = digest(content)
            remote = destination.read_bytes() if destination.is_file() else None
            remote_sha = digest(remote) if remote is not None else None
            blob = git_run(args.git, 'cat-file', 'blob', base + ':' + relative, check=False)
            base_sha = digest(blob.stdout) if blob.returncode == 0 else None
            previous = manifest['files'].get(relative, {}).get('sha256')
            row.update(sha256=local_sha, previous_remote_sha256=remote_sha)
            if remote_sha == local_sha:
                row['status'] = 'unchanged'
            elif remote_sha is not None and remote_sha not in {base_sha, previous}:
                raise ValueError('Network file changed independently; preserve both versions and merge first')
            elif args.dry_run:
                row['status'] = 'would_copy'
            else:
                staged = within(backup, 'staged/' + relative)
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_bytes(content)
                if remote is not None:
                    original = within(backup, 'before/' + relative)
                    original.parent.mkdir(parents=True, exist_ok=True)
                    original.write_bytes(remote)
                destination.parent.mkdir(parents=True, exist_ok=True)
                latest = digest(destination.read_bytes()) if destination.is_file() else None
                if latest != remote_sha:
                    raise ValueError('Network file changed during checkpoint preparation')
                os.replace(staged, destination)
                if digest(destination.read_bytes()) != local_sha:
                    raise ValueError('Network readback hash differs')
                row['status'] = 'copied'
            if not args.dry_run and row['status'] in {'unchanged', 'copied'}:
                manifest['files'][relative] = {'sha256': local_sha, 'checkpoint': checkpoint, 'base': base}
                write_json(manifest_path, manifest)
        except (OSError, ValueError) as error:
            row.update(status='conflict_or_error', error=str(error))
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    report = {'checkpoint': checkpoint, 'base': base, 'target': str(target), 'dry_run': args.dry_run,
              'files': rows, 'successful': all(row['status'] != 'conflict_or_error' for row in rows)}
    write_json(cache / (checkpoint + '.json'), report)
    write_json(cache / 'latest.json', report)
    if not args.dry_run:
        write_json(backup / 'checkpoint.json', report)
    print(json.dumps({'checkpoint': checkpoint, 'successful': report['successful'], 'files': len(rows)}), flush=True)
    return 0 if report['successful'] else 2


if __name__ == '__main__':
    sys.exit(main())
