#!/usr/bin/env python3
"""0036 Step 5: disposable 0035 manager compatibility; no Btrfs or deployed state touched."""
import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

MANAGER = Path(__file__).resolve().parents[1] / "files/btrfs-snapshot-manager.py"
spec = importlib.util.spec_from_file_location("snapshot_manager_step5", MANAGER)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

def reject(config, reason):
    try:
        m.read_verified_diaries(config, strict=True)
    except m.SnapshotError:
        print("PASS:", reason)
    else:
        raise AssertionError(reason)

with tempfile.TemporaryDirectory(prefix="diaries-0036-snapshot-") as temporary:
    root = Path(temporary)/"source"
    dataset = root/"backup/pluto/diaries-backup"
    dataset.mkdir(parents=True)
    manifest = dataset/"dataset-manifest.json"
    marker = root/"backup/.diaries-snapshot-verified.json"
    lock = root/"backup/.btrfs-snapshot-writer.lock"
    lock.touch()
    def publish(backup_id):
        manifest.write_text(json.dumps({"backupId":backup_id,"logicalDataset":"production"}))
        marker.write_text(json.dumps({"state":"verified-published","snapshotEligible":True,
            "datasetRelativePath":"backup/pluto/diaries-backup","backupId":backup_id,
            "logicalDataset":"production","manifestSha256":hashlib.sha256(manifest.read_bytes()).hexdigest()}))
    policy = m.VerificationPolicy(True,"root","backup/pluto/diaries-backup",
                                  "backup/.diaries-snapshot-verified.json",None)
    config = m.Config(root/"snapshots",root/"manager.lock",lock,
              (m.SnapshotSource("root",root),),m.RetentionPolicy(2,2,2,2,2,0),policy)
    publish("20261016-120100Z")
    assert m.read_verified_diaries(config, strict=True)["backupId"] == "20261016-120100Z"
    print("PASS: existing 0035 verification accepts fixed working dataset and marker")
    marker.unlink()
    reject(config,"unmarked working dataset is not eligible")
    publish("20261016-120200Z")
    manifest.write_text(json.dumps({"backupId":"20261016-120300Z","logicalDataset":"production"}))
    reject(config,"changed manifest is rejected until receiver republishes marker")
    publish("20261016-120200Z")
    marker_doc=json.loads(marker.read_text()); marker_doc["datasetRelativePath"]="other"
    marker.write_text(json.dumps(marker_doc))
    reject(config,"marker path mismatch is rejected")
    publish("20261016-120200Z")
    assert m.read_verified_diaries(config,strict=True)["backupId"] == "20261016-120200Z"
    print("PASS: subsequent accepted fixed receive becomes snapshot-eligible")
    with m.with_lock(lock, shared=False, nonblocking=True):
        try:
            m.with_lock(lock, shared=True, nonblocking=True, require_existing=True)
        except m.SnapshotError:
            print("PASS: active receiver exclusive lock blocks 0035 shared snapshot lock")
        else:
            raise AssertionError("snapshot lock acquired during write")
    with patch.object(m,"preflight"), patch.object(m,"managed_snapshot_sets",return_value=([],{})), \
         patch.object(m,"replication_pins",return_value=set()), patch.object(m,"read_checkpoint_holds",return_value={}):
        assert m.prune(config,dry_run=True) == 0
    print("PASS: 0035 prune does not target fixed working directory")
print("PASS: 0036 Step 5 targeted compatibility regression")
