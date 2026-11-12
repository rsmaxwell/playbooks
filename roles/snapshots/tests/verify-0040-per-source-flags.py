#!/usr/bin/env python3
"""0040 per-source contract: isolated config, no host or Btrfs mutation."""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

file = Path(__file__).resolve().parents[1] / 'files/btrfs-snapshot-manager.py'
spec = importlib.util.spec_from_file_location('per_source_0040', file)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    sources = [{'name':'root','path':str(root/'root'),'required':False,'creation':False,'prune':False},
               {'name':'@data','path':str(root/'@data'),'required':True,'creation':True,'prune':True}]
    payload = {'snapshot_root':str(root),'sources':sources}
    f = root/'config.json'
    def load():
        f.write_text(json.dumps(payload))
        return m.load_config(f)
    cfg=load()
    assert (cfg.required_snapshot_sources,cfg.creation_source_names,cfg.prune_source_names)==(('@data',),('@data',),('@data',))
    print('PASS: selected per-source flags')
    for flag in ('required','creation','prune'):
        for bad in ('false','true',0,1,None,[],{}):
            sources[0][flag]=bad
            try:load()
            except m.SnapshotError:pass
            else:raise AssertionError((flag,bad))
        sources[0][flag]=False
    print('PASS: all three flags reject non-boolean input')
    for flag in ('required','creation','prune'):
        sources[1][flag]=False
        try:load()
        except m.SnapshotError:pass
        else:raise AssertionError('zero '+flag+' allowed')
        sources[1][flag]=True
    sources[0]['required']=True
    try:load()
    except m.SnapshotError:pass
    else:raise AssertionError('required without creation accepted')
    sources[0]['required']=False
    print('PASS: missing operational source and required-without-creation rejected')
    for key in ('required_snapshot_sources','creation_source_names','prune_source_names'):
        payload[key]=['@data']
        try:load()
        except m.SnapshotError:pass
        else:raise AssertionError('mixed source representations accepted')
        del payload[key]
    print('PASS: ambiguous mixed legacy and per-source representation rejected')
    payload['sources']=[{'name':s['name'],'path':s['path']} for s in sources]
    cfg=load()
    assert cfg.required_snapshot_sources==cfg.creation_source_names==cfg.prune_source_names==('root','@data')
    print('PASS: absent flags preserve historical all-true behaviour')
print('PASS: 0040 per-source config contract')
