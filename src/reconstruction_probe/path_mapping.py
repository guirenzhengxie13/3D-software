"""Resolve known historical paths at runtime without rewriting evidence files."""

import argparse
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
import sys


PROJECT_ROOTS = (
    r'G:\project\revopoint software',
    r'G:\project\面向三维扫描模型的交互式辅助重建软件设计与实现',
    r'P:\revopoint software',
    r'C:\Users\5gvs4\Documents\my project\revo software',
    r'\\192.168.1.105\project\revopoint software',
)
CAPTURE_ROOT = r'C:\Users\5gvs4\AppData\Roaming\Revopoint\RevoScan6\Projects'


class PathMapper:
    """Map explicit roots, with a read-only exception for the original capture PC.

    Optional config/path-mapping.local.json contains ``mappings`` entries with
    absolute ``source`` and workspace-relative ``target`` strings. Explicit
    ``read_mappings`` may name an external read-only data directory. No suffix
    guessing or searches on the old computer are performed.
    """

    def __init__(self, workspace):
        self.root = Path(workspace).resolve()
        self.capture_root = self._native_capture_root()
        self.read_roots = [self.root] + ([self.capture_root] if self.capture_root else [])
        mappings = [(root, self.root) for root in PROJECT_ROOTS]
        mappings.append((CAPTURE_ROOT, self.capture_root or self.root/'data/revo-scan-projects'))
        config = self.root/'config/path-mapping.local.json'
        if config.is_file():
            data = json.loads(config.read_text(encoding='utf-8'))
            for row in data.get('mappings', []):
                mappings.append((row['source'], self._inside(self.root/Path(row['target']))))
            for row in data.get('read_mappings', []):
                target = Path(row['target'])
                if not target.is_absolute() or target == Path(target.anchor):
                    raise ValueError('Read mapping target must be an explicit absolute data directory')
                target = target.resolve()
                if not target.is_dir():
                    raise ValueError('Read mapping data directory is unavailable')
                self.read_roots.append(target)
                mappings.append((row['source'], target))
        unique = {}
        for source, destination in mappings:
            old = PureWindowsPath(source)
            if not old.is_absolute() or '..' in old.parts:
                raise ValueError('Path mapping source must be an explicit absolute root')
            unique[old] = destination
        self.mappings = sorted(unique.items(), key=lambda pair: len(pair[0].parts), reverse=True)

    def _native_capture_root(self):
        # The original installation keeps raw scans in AppData. A migrated
        # machine must use its copied data, even if its username happens to match.
        if os.name == 'nt' and PureWindowsPath(str(self.root)) in {PureWindowsPath(p) for p in PROJECT_ROOTS[:2]}:
            candidate = Path(CAPTURE_ROOT).resolve()
            if candidate.is_dir():
                return candidate
        return None

    def _read_path(self, path, resolve=False):
        lexical = Path(os.path.abspath(path))
        boundary = next((root for root in self.read_roots if lexical == root or root in lexical.parents), None)
        if boundary is None:
            raise ValueError('Path is outside the workspace and trusted capture root')
        result = lexical.resolve() if resolve else lexical
        if result != boundary and boundary not in result.parents:
            raise ValueError('Read path escapes its trusted root')
        return result

    def _lexical_inside(self, path):
        lexical = Path(os.path.abspath(path))
        if lexical != self.root and self.root not in lexical.parents:
            raise ValueError('Path is outside the current workspace')
        return lexical

    def _inside(self, path):
        # Reject foreign drives/shares before resolve() can probe their I/O.
        lexical = self._lexical_inside(path)
        resolved = lexical.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise ValueError('Path is outside the current workspace')
        return resolved

    def known(self, value):
        """Map only recognized prefixes; leave other metadata strings intact."""
        if not isinstance(value, str):
            return value
        if not (len(value)>2 and value[1]==':' and value[2] in '\\/' or value.startswith('\\\\')):
            return value
        old = PureWindowsPath(value)
        for source, destination in self.mappings:
            try:
                relative = old.relative_to(source)
            except ValueError:
                continue
            if '..' in relative.parts or any(':' in part for part in relative.parts):
                raise ValueError('Historical path escapes its mapped root')
            # Mapping metadata should not stat thousands of frame paths. Actual
            # filesystem use goes through resolve(), which also checks symlinks.
            return str(self._read_path(destination.joinpath(*relative.parts)))
        return value

    def resolve(self, value):
        if not isinstance(value, (str, Path)) or not str(value):
            raise ValueError('A nonempty workspace path is required')
        text = str(value)
        if '\x00' in text:
            raise ValueError('Invalid path')
        mapped = self.known(text)
        candidate = Path(mapped)
        # On POSIX, foreign Windows absolute paths are not native absolutes.
        if mapped == text and PureWindowsPath(text).drive and not candidate.is_absolute():
            raise ValueError('Unknown historical path root')
        if '..' in PureWindowsPath(text).parts:
            raise ValueError('Parent path references are not accepted')
        return self._read_path(candidate if candidate.is_absolute() else self.root/candidate, resolve=True)

    def resolve_output(self, value):
        """Derived files must stay in the workspace, including on the capture PC."""
        return self._inside(self.resolve(value))

    def record(self, value):
        """Return a mapped copy, including path keys in hash dictionaries.

        Digest values and original files remain untouched. Unknown roots remain
        visible in metadata and are rejected if later used for filesystem I/O.
        """
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                mapped = self.known(key)
                converted = self.record(item)
                if mapped in result and result[mapped] != converted:
                    raise ValueError('Historical paths map to conflicting values')
                result[mapped] = converted
            return result
        if isinstance(value, list):
            return [self.record(item) for item in value]
        return self.known(value)


def run_alignment(workspace, session, output):
    """Run the one fixed alignment tool with mapped JSON reads in memory.

    Candidate hashes still read the original file bytes. This adapter does not
    make arbitrary legacy CLI recipes portable.
    """
    mapper = PathMapper(workspace)
    scripts = mapper.root/'scripts'
    script = scripts/'apply_landmark_alignment.py'
    sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location('_mapped_landmark_alignment', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_read = module.read
    module.read = lambda path: mapper.record(original_read(mapper.resolve(path)))
    sys.argv = [str(script), '--session', str(mapper.resolve(session)), '--out', str(mapper.resolve_output(output))]
    module.main()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run the fixed local alignment tool with historical path mapping')
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    run_alignment(args.workspace, args.session, args.out)
