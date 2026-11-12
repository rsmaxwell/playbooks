#!/usr/bin/env python3
"""0035 Step 8: disposable fault injection of production sender/receiver control flow.

No SSH calls, live mounts, production paths or privileges are used. Imports production
source files from the role, stubbing subprocess and snapshot endpoint interactions.
"""
from __future__ import annotations
import errno, importlib.util, io, json, os, pathlib, subprocess, sys, tempfile
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]

def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

sender = load('sender', 'roles/btrfs-replication/files/btrfs-native-push.py')
receiver = load('receiver', 'roles/btrfs-replication/files/btrfs-native-push-receiver.py')
S1='20261015-010000Z'; S2='20261015-020000Z'
U1='11111111-1111-1111-1111-111111111111'; U2='22222222-2222-2222-2222-222222222222'

class FakeProcess:
    def __init__(self, rc, stdout=None): self.returncode=rc; self.stdout=stdout or io.BytesIO(b'bytes')
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def wait(self): return self.returncode

def push_fault(receiver_rc=255, sender_rc=0, acknowledged=False):
    pins=[]; releases=[]
    listing=[{'snapshot':S1,'source_uuid':U1}]
    def local(role,snapshot,expected=None):
        if role=='inspect-source':return {'flags':'readonly','parent_uuid':sender.SOURCE_PARENT,'received_uuid':'-','uuid':U2 if snapshot==S2 else U1}
        if role=='protect-source': pins.append(snapshot);return {'source_uuid':U2 if snapshot==S2 else U1}
        if role=='release-source': releases.append(snapshot);return {}
        raise AssertionError(role)
    def remote(*args):
        if args==('--list',): return json.dumps(listing+([{'snapshot':S2,'source_uuid':U2}] if acknowledged else []))
        return json.dumps({'snapshot':S2,'source_uuid':U2,'action':'incremental'})
    procs=[]
    def popen(args,**kw):
        obj=FakeProcess(sender_rc if not procs else receiver_rc)
        procs.append(obj);return obj
    with tempfile.TemporaryDirectory() as td:
        lock=pathlib.Path(td)/'push.lock'; lock.touch()
        with mock.patch.object(sender,'LOCK',lock), mock.patch.object(sender,'local',side_effect=local),mock.patch.object(sender,'remote',side_effect=remote),mock.patch.object(sender,'receiver_values',side_effect=lambda: listing+([{'snapshot':S2,'source_uuid':U2}] if acknowledged and len(procs)==2 else [])),mock.patch.object(sender.subprocess,'Popen',side_effect=popen),mock.patch.object(sender.os,'geteuid',return_value=1000),mock.patch.object(sys,'argv',['push','--snapshot',S2]):
            try: sender.main()
            except RuntimeError: failed=True
            else: failed=False
    return failed,pins,releases

assert (lambda x:x[0] and x[1]==[S2,S1] and x[2]==[])(push_fault(receiver_rc=255))
print('PASS: simulated SSH receive failure retains candidate and parent pins')
assert (lambda x:x[0] and x[1]==[S2,S1] and x[2]==[])(push_fault(sender_rc=141))
print('PASS: simulated broken-pipe sender failure retains candidate and parent pins')
assert (lambda x:x[0] and x[1]==[S2,S1] and x[2]==[])(push_fault(acknowledged=False))
print('PASS: successful stream without independently visible acknowledgement retains pins')
assert (lambda x:not x[0] and x[2]==[S1])(push_fault(receiver_rc=0,acknowledged=True))
print('PASS: independently accepted receipt permits prior-parent release')

with tempfile.TemporaryDirectory() as td:
    state=pathlib.Path(td); old=state/(S1+'.json'); old.write_text('accepted-old\n')
    data={'snapshot':S2,'source_uuid':U2}
    with mock.patch.object(receiver,'STATE',state),mock.patch.object(receiver.os,'replace',side_effect=OSError(errno.ENOSPC,'No space left on device')):
        try: receiver.atomic_receipt(data)
        except OSError as exc: assert exc.errno==errno.ENOSPC
        else: raise AssertionError('expected ENOSPC')
    assert old.read_text()=='accepted-old\n'
    assert not (state/(S2+'.json')).exists()
    assert not list(state.glob('.push-receipt-*'))
print('PASS: injected receipt-publication ENOSPC preserves prior receipt and leaves no newly accepted receipt')
print('GATE B2 isolated transport/acknowledgement and receipt-publication fault injection PASS')
print('NOT TESTED: actual SSH connection drop, real receipt-file ENOSPC, or new schema-2 restore')
