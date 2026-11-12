#!/usr/bin/python3
"""Disposable tests for dormant agreed-parent persistence (no Btrfs or SSH)."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "files" / "btrfs-agreed-parent-state.py"
spec = importlib.util.spec_from_file_location("agreed_parent", MODULE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
A = {"timestamp": "20261030-120000Z", "uuid": "11111111-1111-1111-1111-111111111111"}
B = {"timestamp": "20261030-130000Z", "uuid": "22222222-2222-2222-2222-222222222222"}
C = {"timestamp": "20261030-140000Z", "uuid": "33333333-3333-3333-3333-333333333333"}


class Regression(unittest.TestCase):
    def test_successful_two_phase_transition(self):
        state = m.initial(A)
        self.assertEqual(m.protected(state), {A["timestamp"]: A["uuid"]})
        state = m.prepare(state, B)
        self.assertEqual(set(m.protected(state)), {A["timestamp"], B["timestamp"]})
        state = m.promote(state)
        self.assertEqual(set(m.protected(state)), {A["timestamp"], B["timestamp"]})
        with self.assertRaises(m.StateError):
            m.prepare(state, C)
        state = m.acknowledge_previous(state)
        self.assertEqual(set(m.protected(state)), {B["timestamp"]})
        self.assertEqual(m.prepare(state, C)["pending"], C)

    def test_interrupted_transition_survives_reload(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "state.json"
            state = m.initial(A)
            m.save(path, state)
            state = m.prepare(m.load(path), B)
            m.save(path, state)
            self.assertEqual(set(m.protected(m.load(path))), {A["timestamp"], B["timestamp"]})
            m.save(path, m.promote(m.load(path)))
            self.assertEqual(set(m.protected(m.load(path))), {A["timestamp"], B["timestamp"]})
            m.save(path, m.acknowledge_previous(m.load(path)))
            self.assertEqual(set(m.protected(m.load(path))), {B["timestamp"]})

    def test_invalid_state_fails_closed(self):
        for malformed in ({}, {"schema": True, "established": A, "pending": None, "previous": None},
                          {"schema": 1, "established": A, "pending": A, "previous": None},
                          {"schema": 1, "established": A, "pending": B, "previous": C}):
            with self.subTest(malformed=malformed), self.assertRaises(m.StateError):
                m.validate(malformed)
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / "state.json"
            with self.assertRaises(m.StateError):
                m.load(p)
            p.write_text('{broken')
            with self.assertRaises(m.StateError):
                m.load(p)
            p.unlink()
            p.symlink_to(Path(root) / "missing")
            with self.assertRaises(m.StateError):
                m.save(p, m.initial(A))

    def test_refuse_transition_without_confirmation(self):
        state = m.prepare(m.initial(A), B)
        with self.assertRaises(m.StateError):
            m.acknowledge_previous(state)
        with self.assertRaises(m.StateError):
            m.prepare(state, C)
        with self.assertRaises(m.StateError):
            m.promote(m.initial(A))


if __name__ == "__main__":
    unittest.main(verbosity=2)
