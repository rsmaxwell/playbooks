"""0040 receiver inventory: agreed-parent metadata must not masquerade as a receipt."""
import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "files" / "btrfs-snapshot-manager.py"
spec = importlib.util.spec_from_file_location("receiver_inventory_0040", MODULE)
manager = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = manager
spec.loader.exec_module(manager)

class ReceiverInventoryMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.config = type("ConfigFixture", (), {
            "mode": "receiver", "receiver_state_dir": self.state,
            "sources": [object()]
        })()

    def inventory(self):
        output = io.StringIO()
        with patch.object(manager, "preflight"), \
             patch.object(manager, "list_managed", return_value=[]), \
             patch.object(manager, "source_directory", return_value=self.state), \
             redirect_stdout(output):
            try:
                result = manager.receiver_inventory(self.config)
                return result, output.getvalue()
            except manager.SnapshotError:
                return None, output.getvalue()

    def test_agreed_parent_metadata_is_not_a_receipt(self):
        (self.state / ".agreed-parent.json").write_text("{}")
        result, output = self.inventory()
        self.assertEqual(result, [])
        self.assertIn("RECEIVER-INVENTORY problems=0", output)

    def test_unknown_json_still_fails_closed(self):
        (self.state / ".agreed-parent.json").write_text("{}")
        (self.state / "unexpected.json").write_text("{}")
        result, output = self.inventory()
        self.assertIsNone(result)
        self.assertIn("UNVERIFIED receipt=unexpected.json", output)

    def test_symlinked_unknown_json_still_fails_closed(self):
        (self.state / ".agreed-parent.json").write_text("{}")
        (self.state / "unexpected.json").symlink_to(self.state / ".agreed-parent.json")
        result, output = self.inventory()
        self.assertIsNone(result)
        self.assertIn("UNVERIFIED receipt=unexpected.json", output)

if __name__ == "__main__":
    unittest.main(verbosity=2)
