#!/usr/bin/env python3
"""0040 Step 4: non-destructive paired-to-@data source migration checks."""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

manager = Path(__file__).resolve().parents[1] / 'files/btrfs-snapshot-manager.py'
spec = importlib.util.spec_from_file_location('step04_manager', manager)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    (root/'root').mkdir()
    (root/'@data').mkdir()
    data = {
        'snapshot_root':str(root),
        'sources':[{'name':'root','path':str(root/'root'), 'required':False, 'creation':False, 'prune':False}, {'name':'@data','path':str(root/'@data')}]
    }
    configfile=root/'config.json'
    configfile.write_text(json.dumps(data))
    config=m.load_config(configfile)
    assert config.required_snapshot_sources == ('@data',)
    assert config.creation_source_names == ('@data',)
    for name in ('20261001-080000Z','20261002-080000Z'):
        (root/'@data'/name).mkdir()
    (root/'root'/'20261001-080000Z').mkdir()
    complete, incomplete = m.managed_snapshot_sets(config)
    assert len(complete) == 2 and not incomplete, (complete,incomplete)
    (root/'root'/'20261003-080000Z').mkdir()
    complete, incomplete = m.managed_snapshot_sets(config)
    assert len(complete) == 2 and '20261003-080000Z' in incomplete
    # Creation selects @data only, verified without invoking btrfs.
    (root/'root'/'20261003-080000Z').rmdir()
    with patch.object(m,'preflight'), patch.object(m,'read_verified_diaries',return_value=None), patch.object(m,'run') as run:
        m.create_all(config,'20261004-080000Z')
        calls=[call.args[0] for call in run.call_args_list]
        assert len(calls)==1 and calls[0][4]==str(root/'@data')
    # Default remains the original paired-set behaviour.
    data['sources']=[{'name':n,'path':str(root/n)} for n in ('root','@data')]
    configfile.write_text(json.dumps(data))
    old=m.load_config(configfile)
    assert len(old.required_snapshot_sources)==2 and len(old.creation_source_names)==2
    complete,incomplete=m.managed_snapshot_sets(old)
    assert '20261002-080000Z' in incomplete
    # Malformed migration contracts fail closed.
    for invalid in (['root','root'], ['unknown'], []):
        data['required_snapshot_sources']=invalid
        configfile.write_text(json.dumps(data))
        try: m.load_config(configfile)
        except m.SnapshotError: pass
        else: raise AssertionError(f'accepted invalid sources: {invalid}')
print('PASS: @data-only completeness, legacy paired history, source-only creation, default compatibility and invalid-config rejection')
