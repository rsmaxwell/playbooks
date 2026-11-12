#!/usr/bin/env python3
"""Isolated schema-2 fixed working-copy regression. No Docker or production data."""
from pathlib import Path
import tempfile, subprocess, sys, json
base=Path(__file__).resolve().parents[1]
scripts=base/'files/sync/scripts'
fixture=Path(__file__).with_name('verify-complete-dataset-manifest.py')
source=fixture.read_text(encoding='utf-8')
namespace={'__name__':'fixture_support','__file__':str(fixture)}
exec(compile(source[:source.index('def mutate_manifest(')],str(fixture),'exec'),namespace)
with tempfile.TemporaryDirectory(prefix='0036-fixed-refresh-') as tmp:
    p=Path(tmp); inputs=p/'inputs'; inputs.mkdir()
    candidate=namespace['create_candidate'](inputs)
    assert namespace['write_manifest'](candidate).returncode==0
    backup_id=candidate.name[1:-8]; src=inputs/backup_id;candidate.rename(src)
    dst=p/'diaries-backup'
    argv=[sys.executable,str(scripts/'fixed-dataset-refresh.py'),'--source',str(src),'--destination',str(dst),'--manifest-tool',str(scripts/'complete-dataset-manifest.py')]
    first=subprocess.run(argv,capture_output=True,text=True)
    assert first.returncode==0,first.stderr
    marker=p/'.diaries-backup-fixed-verified.json'
    assert json.loads(marker.read_text())['backupId']==backup_id
    inode=(dst/'files/a.txt').stat().st_ino
    second=subprocess.run(argv,capture_output=True,text=True)
    assert second.returncode==0,second.stderr
    assert (dst/'files/a.txt').stat().st_ino==inode
    (src/'files/a.txt').write_text('deliberately corrupted\n')
    bad=subprocess.run(argv,capture_output=True,text=True)
    assert bad.returncode!=0
    assert not marker.exists()
    print('PASS: fixed schema-2 refresh, unchanged inode, verify and fail-closed marker')
