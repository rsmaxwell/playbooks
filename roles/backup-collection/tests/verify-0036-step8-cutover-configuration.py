#!/usr/bin/env python3
"""Source-only default-off guardrails for the controlled 0036 cutover."""
from pathlib import Path
r=Path(__file__).resolve().parents[1]
d=(r/'defaults/main.yaml').read_text()
w=(r/'templates/diaries/diaries-pull.sh.j2').read_text()
t=(r/'tasks/diaries_pull.yaml').read_text()
assert 'diaries_pull_fixed_destination_enabled: false' in d
assert 'diaries_pull_fixed_source_guard:' in d
assert 'if (diaries_pull_fixed_destination_enabled | bool) else' in w
assert '--fixed-destination' in w and '--fixed-source-guard' in w
assert 'diaries_pull_fixed_destination_enabled is boolean' in t
assert 'not (diaries_pull_fixed_destination_enabled | bool) or (diaries_pull_install | bool)' in t
assert 'diaries_pull_schedule_enabled: false' in d
print('PASS: Step 8 opt-in fixed destination has default-off installation and schedule guards')
