import importlib.util, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
MODULE=Path(__file__).parents[1]/'files'/'btrfs-snapshot-manager.py'
spec=importlib.util.spec_from_file_location('mgr0040',MODULE); m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m)
UUID='d901ddd2-66c7-0b42-b26c-ab6886273b7a'
STAMP='20261030-030033Z'
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root=Path(self.tmp.name); self.state=self.root/'.agreed-parent.json'
  self.good={'schema':1,'established':{'timestamp':STAMP,'uuid':UUID},'pending':None,'previous':None}
 def config(self,mode='source'):
  return m.Config(snapshot_root=self.root,lock_path=self.root/'lock',writer_lock_path=None,sources=(),retention=m.RetentionPolicy(0,0,0,0,0,30),verification=m.VerificationPolicy(False,'','','',None),mode=mode,receiver_state_dir=self.root)
 def write(self,obj):
  self.state.write_text(json.dumps(obj)); self.state.chmod(0o600)
 def root_owned_fixture(self):
  """Pretend only the disposable state file is root-owned; preserve its real mode and size."""
  original_stat = Path.stat
  state_path = self.state
  def fixture_stat(path, *args, **kwargs):
   result = original_stat(path, *args, **kwargs)
   if path == state_path:
    return SimpleNamespace(st_mode=result.st_mode, st_nlink=result.st_nlink,
                           st_uid=0, st_size=result.st_size)
   return result
  return patch.object(Path, 'stat', fixture_stat)
 def pins(self, mode='source'):
  with self.root_owned_fixture():
   return m.agreed_parent_pins(self.config(mode))
 def test_absent_legacy(self): self.assertEqual(self.pins(),set())
 def test_established(self):
  self.write(self.good); self.assertEqual(self.pins(),{STAMP})
 def test_receiver_same(self):
  self.write(self.good); self.assertEqual(self.pins('receiver'),{STAMP})
 def test_all_generations(self):
  self.good['pending']={'timestamp':'20261031-030033Z','uuid':UUID}; self.write(self.good)
  self.assertEqual(len(self.pins()),2)
 def test_previous(self):
  self.good['previous']={'timestamp':'20261029-030033Z','uuid':UUID}; self.write(self.good)
  self.assertEqual(len(self.pins()),2)
 def test_corruption(self):
  self.state.write_text('{'); self.state.chmod(0o600)
  with self.assertRaises(m.SnapshotError): self.pins()
 def test_nonroot_owner_rejected(self):
  self.write(self.good)
  original_stat = Path.stat
  state_path = self.state
  def nonroot_stat(path, *args, **kwargs):
   result = original_stat(path, *args, **kwargs)
   if path == state_path:
    return SimpleNamespace(st_mode=result.st_mode, st_nlink=result.st_nlink,
                           st_uid=1000, st_size=result.st_size)
   return result
  with patch.object(Path, 'stat', nonroot_stat):
   with self.assertRaises(m.SnapshotError):
    m.agreed_parent_pins(self.config())
 def test_unsafe_mode(self):
  self.write(self.good); self.state.chmod(0o666)
  with self.assertRaises(m.SnapshotError): self.pins()
 def test_duplicate(self):
  self.good['pending']=dict(self.good['established']); self.write(self.good)
  with self.assertRaises(m.SnapshotError): self.pins()
 def test_symlink(self):
  target=self.root/'other'; target.write_text('{}'); self.state.symlink_to(target)
  with self.assertRaises(m.SnapshotError): self.pins()
 def test_invalid_transition(self):
  self.good['previous']={'timestamp':'20261029-030033Z','uuid':UUID}; self.good['pending']={'timestamp':'20261031-030033Z','uuid':UUID}; self.write(self.good)
  with self.assertRaises(m.SnapshotError): self.pins()
if __name__=='__main__': unittest.main(verbosity=2)
