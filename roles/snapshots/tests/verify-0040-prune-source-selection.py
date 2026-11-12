#!/usr/bin/env python3
"""0040: prevent routine retention from retiring historical root snapshots.
Disposable fixtures and mock Btrfs commands; no live Btrfs mutations.
"""
import importlib.util
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

script = Path(__file__).resolve().parents[1] / 'files/btrfs-snapshot-manager.py'
spec = importlib.util.spec_from_file_location('manager0040prune', script)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

with tempfile.TemporaryDirectory(prefix='0040-prune-source-') as td:
    root = Path(td)
    for name in ('root', '@data'):
        (root/name).mkdir()
    stamps = ('20261001-080000Z','20261002-080000Z','20261003-080000Z')
    for stamp in stamps:
        (root/'@data'/stamp).mkdir()
        (root/'root'/stamp).mkdir()
    payload = {'snapshot_root': str(root),
        'sources': [{'name':n,'path':str(root/n), 'required':n=='@data', 'creation':n=='@data', 'prune':n=='@data'} for n in ('root','@data')]}
    configpath = root/'config.json'
    def load():
        configpath.write_text(json.dumps(payload))
        return m.load_config(configpath)
    config = load()
    assert config.prune_source_names == ('@data',)
    assert len(m.managed_snapshot_sets(config)[0]) == 3
    def context(kept=set(), holds={}):
        return [patch.object(m,'preflight'),
                patch.object(m,'retention_keep_set',return_value=set()),
                patch.object(m,'replication_pins',return_value=set(kept)),
                patch.object(m,'read_checkpoint_holds',return_value=dict(holds)),
                patch.object(m,'validate_prune_candidate'),
                patch.object(m,'native_prune_subvolume_id',return_value=42)]
    # Exercise dry-run and actual deletion loops; no root paths may appear.
    for dry in (True,False):
        import contextlib
        with contextlib.ExitStack() as stack:
            for cm in context(kept={stamps[0]},holds={stamps[1]:{'reason':'held'}}):
                stack.enter_context(cm)
            run = stack.enter_context(patch.object(m,'run'))
            out=io.StringIO()
            with redirect_stdout(out):
                result=m.prune(config,dry_run=dry)
            assert result == 1
            lines=out.getvalue()
            assert ('WOULD-DELETE @data ' if dry else 'DELETE @data ') + stamps[2] in lines
            assert 'DELETE root ' not in lines and 'WOULD-DELETE root ' not in lines
            assert stamps[0] not in [x for x in lines.splitlines() if 'DELETE' in x]
            if dry:
                run.assert_not_called()
            else:
                commands=[c.args[0] for c in run.call_args_list]
                assert commands == [['btrfs','subvolume','delete',str(root/'@data'/stamps[2])]], commands
    print('PASS: only @data chosen by dry-run and deletion; held/pinned timestamps retained')
    # Without prune_source_names the historical all-source contract remains.
    payload['sources']=[{'name':n,'path':str(root/n)} for n in ('root','@data')]
    legacy=load()
    assert legacy.prune_source_names == ('root','@data')
    with __import__('contextlib').ExitStack() as stack:
        for cm in context():stack.enter_context(cm)
        run=stack.enter_context(patch.object(m,'run'))
        output=io.StringIO()
        with redirect_stdout(output):m.prune(legacy,dry_run=True)
        assert 'WOULD-DELETE root '+stamps[2] in output.getvalue()
        run.assert_not_called()
    print('PASS: omitted prune setting retains all-source behaviour')
    for invalid in ([], ['unknown'], ['@data','@data'], ['root','not-configured'], 'root'):
        payload['prune_source_names']=invalid
        try:load()
        except m.SnapshotError:pass
        else:raise AssertionError(f'accepted invalid pruning sources: {invalid!r}')
    print('PASS: malformed pruning selection fails closed')
print('PASS: 0040 prune source selection regression (no Btrfs operations)')
