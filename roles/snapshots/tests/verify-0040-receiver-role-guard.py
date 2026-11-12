#!/usr/bin/env python3
"""Static regression for the early receiver-role safety boundary."""
from pathlib import Path
import yaml

root = Path(__file__).resolve().parents[3]
tasks = yaml.safe_load((root / 'roles/snapshots/tasks/main.yaml').read_text())
assert isinstance(tasks, list) and len(tasks) > 1
first = tasks[0]
assert 'ansible.builtin.assert' in first
check = first['ansible.builtin.assert']['that']
assert any('remote_backup' in str(value) and 'inventory_hostname not in' in str(value) for value in check)
assert 'always' in first['tags'], 'Guard must run even during tagged snapshots deployment'
assert 'REFUSED:' in first['ansible.builtin.assert']['fail_msg']
for task in tasks[1:]:
    assert task.get('name') != first['name'], 'Guard must occur exactly once'
playbook = yaml.safe_load((root / 'snapshots.yaml').read_text())
assert any('remote_backup' == p.get('hosts') for p in playbook)
print('PASS: generic snapshot role rejects receiver group before all mutating tasks, including tagged runs')
