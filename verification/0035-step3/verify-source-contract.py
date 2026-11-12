#!/usr/bin/env python3
from pathlib import Path
p=Path(__file__).resolve().parents[2]
r=(p/'roles/btrfs-replication/files/btrfs-native-push-receiver.py').read_text()
e=(p/'roles/btrfs-replication/files/btrfs-native-endpoint.py').read_text()
c=(Path(__file__).parent/'capture-backup.yaml').read_text()
checks={'separate receive root':"ROOT = Path('/@data/mars-received/@data')" in r,'receipts outside received roots':"STATE = Path('/@data/mars-received/.replication-state')" in r,'received UUID check':"received_uuid') == value['source_uuid']" in r,'readonly validation':"observed.get('flags') == 'readonly'" in r,'accepted parent requirement':'Parent is not a verified accepted receiver' in r,'shared receiver writer lock':'fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)' in r,'unaccepted failures preserved':'UNACCEPTED' in r,'no auto-delete':'no auto delete' in e,'read-only capture': 'changed_when: false' in c and 'ansible.builtin.shell' in c and 'btrfs subvolume delete' not in c}
for name,ok in checks.items(): print(('PASS' if ok else 'FAIL')+': '+name)
raise SystemExit(0 if all(checks.values()) else 1)
