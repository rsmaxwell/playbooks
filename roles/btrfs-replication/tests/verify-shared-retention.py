#!/usr/bin/env python3
"""0040 Step 12.3: consistency, default, temporary override and isolation checks."""
from pathlib import Path
import json
import re
import sys
import yaml
from jinja2 import Environment, FileSystemLoader

role = Path(__file__).resolve().parents[1]
defaults = yaml.safe_load((role / 'defaults/main.yaml').read_text())
policy = defaults['btrfs_receiver_retention']
expected = {'hourly': 48, 'daily': 14, 'weekly': 12, 'monthly': 24,
            'yearly': 5, 'minimum_age_minutes': 30}
assert policy == expected, ('Unexpected default receiver policy', policy)
env = Environment(loader=FileSystemLoader(str(role / 'templates')))
env.filters['to_json'] = json.dumps
templates = ('btrfs-receiver-manager.json.j2', 'btrfs-receiver-retention.json.j2')
for hourly in (48, 24):
    override = dict(policy, hourly=hourly)
    results = [json.loads(env.get_template(name).render(btrfs_receiver_retention=override))
               for name in templates]
    assert results[0]['retention'] == results[1]['retention'] == override
    assert all(result['receiver_prune_enabled'] is False for result in results)
    assert results[0]['mode'] == results[1]['mode'] == 'receiver'
    assert results[0]['checkpoint_holds']['required'] is True
    assert results[1]['schema'] == 1
for name in templates:
    text = (role / 'templates' / name).read_text()
    assert text.count('btrfs_receiver_retention | to_json') == 1
    assert not re.search(r'"hourly"\s*:\s*48', text)
print('PASS: receiver policies share one variable; defaults, 24-hour test and guards verified')
