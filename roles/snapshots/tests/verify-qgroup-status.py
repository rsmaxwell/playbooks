#!/usr/bin/env python3
"""Source-level mocks: no Btrfs device access, mutations or quota rescans."""
import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

manager = Path(__file__).resolve().parents[1] / 'files' / 'btrfs-snapshot-manager.py'
spec = importlib.util.spec_from_file_location('snapshot_manager_qgroup_test', manager)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def case(stdout, expected, rc=0):
    observed = []
    def fake_run(command, **kw):
        observed.append((command, kw))
        return subprocess.CompletedProcess(command, rc, stdout, '')
    with patch.object(mod.subprocess, 'run', side_effect=fake_run):
        actual = mod.qgroup_status(Path('/media/usb'))
    assert actual == expected, (actual, expected)
    assert observed[0][0] == ['btrfs', 'qgroup', 'show', '/media/usb']
    assert observed[0][1]['timeout'] == 8
    print('PASS:', expected[-1])

hdr = 'Qgroupid    Referenced    Exclusive   Path\n--------    ----------    ---------   ----\n'
case(hdr + '0/1 1.00GiB 1.00GiB /existing\n0/2 0.00B 0.00B <stale>\n',
     ['qgroups_total=2', 'qgroups_stale=1', 'qgroups_under_deletion=0', 'qgroups_status=ok'])
case(hdr + ''.join(f'0/{i} 0.00B 0.00B <stale>\n' for i in range(101)),
     ['qgroups_total=101', 'qgroups_stale=101', 'qgroups_under_deletion=0', 'qgroups_status=warning'])
case(hdr + '0/23 0.00B 0.00B <under deletion>\n',
     ['qgroups_total=1', 'qgroups_stale=0', 'qgroups_under_deletion=1', 'qgroups_status=warning'])
# Ubuntu 22.04 / btrfs-progs 5.16: lowercase header and abbreviated units.
legacy_hdr = ('qgroupid         rfer         excl     max_rfer     max_excl parent  child\n'
              '--------         ----         ----     --------     -------- ------  -----\n')
case(legacy_hdr + '0/5 10.14GiB 338.86MiB none none --- ---\n'
     + '0/275 325.20GiB 592.00KiB 1.00TiB none --- ---\n'
     + '0/276 0.00B 0.00B none none --- ---\n',
     ['qgroups_total=3', 'qgroups_stale=0', 'qgroups_under_deletion=0', 'qgroups_status=ok'])
case(legacy_hdr + '0/20919 0.00B 0.00B none none --- --- <stale>\n'
     + '0/20920 0.00B 0.00B 3.64TiB none --- --- <under deletion>\n',
     ['qgroups_total=2', 'qgroups_stale=1', 'qgroups_under_deletion=1', 'qgroups_status=warning'])
case('qgroupid nonsense header\n-------- -------- ------\n0/5 0.00B 0.00B\n',
     ['qgroups_status=unavailable;reason=unexpected_output'])
case(legacy_hdr + 'INVALID LINE\n',
     ['qgroups_status=unavailable;reason=unexpected_output'])
case('', ['qgroups_status=unavailable;reason=query_failed;exit_code=1'], rc=1)
case('unexpected', ['qgroups_status=unavailable;reason=unexpected_output'])
with patch.object(mod.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['btrfs'],8)):
    assert mod.qgroup_status(Path('/media/usb')) == ['qgroups_status=unavailable;reason=timeout']
print('PASS: bounded timeout is non-fatal')
with patch.object(mod.subprocess, 'run', side_effect=FileNotFoundError()):
    assert mod.qgroup_status(Path('/media/usb')) == ['qgroups_status=unavailable;reason=execution_error']
print('PASS: missing command is non-fatal')
