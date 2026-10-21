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
)
CAPTURE_ROOT = r'C:\Users\5gvs4\AppData\Roaming\Revopoint\RevoScan6\Projects'


class PathMapper:
    """Map explicit roots, and reject paths that leave the supplied workspace.

    Optional config/path-mapping.local.json contains ``mappings`` entries with
    absolute ``source`` and workspace-relative ``target`` strings. No suffix
    guessing or searches on the old computer are performed.
    """

    def __init__(self, workspace):
        self.root = Path(workspace).resolve()
        mappings = [(root, '.') for root in PROJECT_ROOTS]
        mappings.append((CAPTURE_ROOT, 'data/revo-scan-projects'))
        config = self.root/'config/path-mapping.local.json'
        if config.is_file():
            data = json.loads(config.read_text(encoding='utf-8'))
            for row in data.get('mappings', []):
                mappings.append((row['source'], row['target']))
        self.mappings = []
        for source, target in mappings:
            old = PureWindowsPath(source)
            if not old.is_absolute() or '..' in old.parts:
                raise ValueError('Path mapping source must be an explicit absolute root')
            destination = self._inside(self.root/Path(target))
            self.mappings.append((old, destination))
        self.mappings.sort(key=lambda pair: len(pair[0].parts), reverse=True)

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
            return str(self._lexical_inside(destination.joinpath(*relative.parts)))
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
        return self._inside(candidate if candidate.is_absolute() else self.root/candidate)

    def record(self, value):
        """Return a mapped copy, including path keys in hash dictionaries.

        Digest values and original files remain untouched. Unknown roots remain
        visible in metadata and are rejected if later used for filesystem I/O.
        """
        if isinstance(value, dict):
            return {self.known(key): self.record(item) for key, item in value.items()}
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
    sys.argv = [str(script), '--session', str(mapper.resolve(session)), '--out', str(mapper.resolve(output))]
    module.main()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run the fixed local alignment tool with historical path mapping')
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    run_alignment(args.workspace, args.session, args.out)
