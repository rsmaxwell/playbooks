#!/usr/bin/env python3
"""0040 Step 12.3: source-level recovery gates using existing transition code.

Simulation evidence only. No production promotion or pruning authority.
"""
import importlib.util
from pathlib import Path
import unittest

FILES = Path(__file__).resolve().parents[1] / "files"

def load(name):
    path = FILES / ("btrfs-agreed-parent-" + name + ".py")
    spec = importlib.util.spec_from_file_location("test_recovery_" + name.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

sim = load("transaction-sim")
state = load("state")
A = {"timestamp": "20261030-030033Z", "uuid": "d901ddd2-66c7-0b42-b26c-ab6886273b7a"}
B = {"timestamp": "20261030-170009Z", "uuid": "a9b78fb9-4da6-cf4f-b242-13909f574193"}

class Recovery(unittest.TestCase):
    def test_all_lost_acknowledgement_boundaries(self):
        for boundary in ("prepare-receiver", "prepare-source", "replicate-candidate",
                         "promote-receiver", "promote-source"):
            with self.subTest(boundary=boundary):
                run = sim.Simulation(A, B)
                while run.choose() != boundary:
                    run.step()
                with self.assertRaises(sim.Interrupted):
                    run.step(interrupt_after=boundary)
                # Never silently rerun a transfer after an uncertain completion.
                if boundary == "replicate-candidate":
                    self.assertEqual(run.choose(), "promote-receiver")
                source, receiver = run.finish()
                self.assertEqual(source, receiver)
                self.assertEqual(source["established"], B)
                self.assertEqual(source["previous"], A)
                self.assertNotIn("acknowledge-previous", run.actions)

    def test_old_parent_is_pinned_at_every_stage(self):
        run = sim.Simulation(A, B)
        for _ in range(7):
            self.assertIn(A["timestamp"], state.protected(run.source) |
                          state.protected(run.receiver))
            if run.choose() == "await-cross-endpoint-acknowledgement":
                break
            run.step()
        else:
            self.fail("did not converge")

    def test_receiver_promoted_first(self):
        run = sim.Simulation(A, B)
        actions = []
        for _ in range(7):
            operation = run.step()
            actions.append(operation)
            if operation == "await-cross-endpoint-acknowledgement":
                break
        self.assertLess(actions.index("promote-receiver"), actions.index("promote-source"))

    def test_never_acknowledge_previous_automatically(self):
        run = sim.Simulation(A, B)
        source, receiver = run.finish()
        self.assertEqual(source["previous"], A)
        self.assertEqual(receiver["previous"], A)
        self.assertEqual(run.choose(), "await-cross-endpoint-acknowledgement")

if __name__ == "__main__":
    unittest.main(verbosity=2)
