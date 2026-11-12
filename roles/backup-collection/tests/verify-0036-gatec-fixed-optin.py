from pathlib import Path
p=Path(__file__).resolve().parents[3]
base=(p/'roles/backup-collection/defaults/main.yaml').read_text()
template=(p/'roles/backup-collection/templates/diaries/diaries-pull.sh.j2').read_text()
tasks=(p/'roles/backup-collection/tasks/diaries_pull.yaml').read_text()
assert 'diaries_pull_fixed_destination_enabled: false' in base
assert '--fixed-destination' in template and '--fixed-source-guard' in template
assert 'diaries_pull_fixed_destination_enabled is boolean' in tasks
assert 'if (diaries_pull_fixed_destination_enabled | bool) else' in template
print('PASS: Gate C fixed receiver remains explicit opt-in and default-off')
