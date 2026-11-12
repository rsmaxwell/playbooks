#!/usr/bin/env python3
"""Verify source flag values survive templating without coercion (no deployment)."""
import json
from pathlib import Path
import yaml
from jinja2 import Environment, StrictUndefined

root = Path(__file__).resolve().parents[1]
template = (root / 'templates/btrfs-snapshot-manager.json.j2').read_text()
tasks = yaml.safe_load((root / 'tasks/main.yaml').read_text())
assert all(f'source.{flag} | default(true) | to_json' in template for flag in ('required','creation','prune'))
assert not any(f'source.{flag} | default(true) | bool' in template for flag in ('required','creation','prune'))
validation = next(task for task in tasks if task.get('name') == 'snapshots | Validate per-source snapshot flags')
conditions = validation['ansible.builtin.assert']['that']
for flag in ('required','creation','prune'):
    assert f'item.{flag} is not defined or item.{flag} is boolean' in conditions

def render(flags):
    env = Environment(undefined=StrictUndefined, autoescape=False)
    env.filters['to_json'] = json.dumps
    variables = dict(
        btrfs_snapshot_root_effective='/test/@snapshots',
        btrfs_snapshot_manager_lock_path='/test/lock',
        btrfs_snapshot_writer_lock_path='/test/writer',
        btrfs_snapshot_sources=[dict(name='root', path='/test', **flags),
                                dict(name='@data', path='/test/@data', required=True, creation=True, prune=True)],
        btrfs_snapshot_require_verified_diaries=False,
        btrfs_snapshot_diaries_source_name='@data',
        btrfs_snapshot_diaries_relative_path='',
        btrfs_snapshot_diaries_marker_relative_path='',
        btrfs_snapshot_manifest_tool_path='/test/manifest',
        inventory_hostname='mars',
        btrfs_snapshot_retention_hourly=48,
        btrfs_snapshot_retention_daily=14,
        btrfs_snapshot_retention_weekly=12,
        btrfs_snapshot_retention_monthly=24,
        btrfs_snapshot_retention_yearly=5,
        btrfs_snapshot_minimum_age_minutes=30,
    )
    # This render isolates the three flags and related JSON fields. Actual boolean
    # filters elsewhere in the template are provided for its existing behavior.
    env.filters['bool'] = bool
    return json.loads(env.from_string(template).render(**variables))['sources'][0]

assert all(render({})[k] is True for k in ('required','creation','prune'))
assert render(dict(required=False, creation=False, prune=False))['prune'] is False
for flag in ('required','creation','prune'):
    assert render({flag: 'false'})[flag] == 'false', flag
    assert render({flag: 0})[flag] == 0, flag
print('PASS: per-source flags preserve native JSON types; Ansible assertion validates booleans')
