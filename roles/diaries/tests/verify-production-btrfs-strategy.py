#!/usr/bin/env python3
"""Historical 0034 Step 3 legacy-capture compatibility regression.

Step 8 superseded direct reflink publication on pluto.  This test is retained
intentionally: Step 2 storage-mode inputs and the legacy capture preflight must
not silently change until a separately documented migration retires them.
"""
import importlib.util
import tempfile
from pathlib import Path
from unittest.mock import patch

engine = Path(__file__).resolve().parents[1] / 'files/sync/scripts/production-complete-dataset.py'
spec = importlib.util.spec_from_file_location('diaries_storage', engine)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

with tempfile.TemporaryDirectory() as base:
    root = Path(base) / 'repository'
    root.mkdir()
    original = root / 'existing-completed-media'
    original.mkdir()
    (original / 'keep').write_text('do not touch')
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob('*'))
    assert m.inspect_repository_capability(root, 'full-copy')['strategy'] == 'full-copy'
    print('PASS: full-copy deliberately bypasses reflink probing')
    with patch.object(m.subprocess, 'run', return_value=m.subprocess.CompletedProcess([], 0, '/mnt/ext4 ext4\n', '')):
        result = m.inspect_repository_capability(root, 'auto')
        assert result['strategy'] == 'full-copy' and not result['reflink']
        print('PASS: auto on ext4 selects full-copy')
        try:
            m.inspect_repository_capability(root, 'required-btrfs')
            raise AssertionError('required-btrfs must fail on ext4')
        except m.ToolError:
            print('PASS: required-btrfs fails closed on ext4')
    def fake_run(argv, **kwargs):
        if argv[0] == 'findmnt':
            return m.subprocess.CompletedProcess(argv, 0, '/mnt/btrfs btrfs\n', '')
        if argv[0] == 'cp':
            Path(argv[-1]).write_bytes(Path(argv[-2]).read_bytes())
            return m.subprocess.CompletedProcess(argv, 0, '', '')
        raise AssertionError(argv)
    with patch.object(m.subprocess, 'run', side_effect=fake_run):
        for mode in ('auto', 'required-btrfs'):
            result = m.inspect_repository_capability(root, mode)
            assert result['strategy'] == 'reflink' and result['reflink']
            print(f'PASS: successful Btrfs clone selects reflink for {mode}')
    def failed_clone(argv, **kwargs):
        if argv[0] == 'findmnt':
            return m.subprocess.CompletedProcess(argv, 0, '/mnt/btrfs btrfs\n', '')
        return m.subprocess.CompletedProcess(argv, 1, '', 'operation not supported')
    with patch.object(m.subprocess, 'run', side_effect=failed_clone):
        assert m.inspect_repository_capability(root, 'auto')['strategy'] == 'full-copy'
        print('PASS: failed clone in auto falls back to full-copy')
        try:
            m.inspect_repository_capability(root, 'required-btrfs')
            raise AssertionError('required-btrfs must reject failed probe')
        except m.ToolError:
            print('PASS: failed clone in required-btrfs fails closed')
    after = sorted(p.relative_to(root).as_posix() for p in root.rglob('*'))
    assert before == after and (original / 'keep').read_text() == 'do not touch'
    print('PASS: probe scratch removed and completed media untouched')
print('PASS: historical 0034 Step 3 legacy-capture strategy regression')
