#!/usr/bin/env python3
"""0041 source-only adversarial contract tests. No keys, SSH, root or Btrfs writes."""
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]

def load(module, name):
    loader=importlib.machinery.SourceFileLoader(name,str(ROOT/'files'/module))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    obj=importlib.util.module_from_spec(spec)
    loader.exec_module(obj)
    return obj

sender=load('btrfs-simplified-replication.py','rep0041')
dispatch=load('btrfs-replication-ssh-dispatch-0041.py','dispatch0041')
gate=load('btrfs-replication-receiver-gate-0041.py','gate0041')
A='20261112-030019Z'
B='20261113-030001Z'
U1='11111111-1111-1111-1111-111111111111'
U2='22222222-2222-2222-2222-222222222222'

class Contracts(unittest.TestCase):
    def test_legacy_transport_not_changed(self):
        with patch.dict(os.environ,{},clear=True):
            args=sender.ssh_command('status')
        self.assertEqual(args[:6],['sudo','-n','-u','richard','ssh','-o'])
        self.assertEqual(args[-1], 'sudo -n /usr/local/bin/btrfs-simplified-replication receiver status')
        self.assertEqual(args[-2], 'richard@10.254.22.1')

    def test_dedicated_transport_is_strict(self):
        with patch.dict(os.environ,{'BTRFS_REPLICATION_IDENTITY_MODE':'dedicated'}):
            args=sender.ssh_command('receive','--snapshot',B,'--uuid',U2,
                                    '--parent',A,'--parent-uuid',U1)
        self.assertEqual(args[:6],['sudo','-n','-u','btrfs-send','ssh','-F'])
        self.assertIn('StrictHostKeyChecking=yes',args)
        self.assertIn('IdentitiesOnly=yes',args)
        self.assertIn('UserKnownHostsFile=/etc/btrfs-replication-0041/known_hosts',args)
        self.assertEqual(args[5:7],['-F','/dev/null'])
        self.assertEqual(args[-2],'btrfs-receive@10.254.22.1')
        self.assertNotIn('sudo', shlex.split(args[-1]))
        self.assertEqual(dispatch.parse_ssh_command(args[-1]), {
            'op':'receive','snapshot':B,'uuid':U2,'parent':A,'parent_uuid':U1})

    def test_unknown_mode_refuses_instead_of_silent_fallback(self):
        with patch.dict(os.environ,{'BTRFS_REPLICATION_IDENTITY_MODE':'unrecognized'}):
            with self.assertRaises(sender.Refuse): sender.ssh_command('status')

    def test_allowed_status_and_advance(self):
        cases=(
            ('btrfs-replication receiver status',{'op':'status','snapshot':None}),
            ('btrfs-replication receiver status --snapshot '+B,{'op':'status','snapshot':B}),
            (f'btrfs-replication receiver advance --snapshot {B} --uuid {U2} --parent {A} --parent-uuid {U1}',
             {'op':'advance','snapshot':B,'uuid':U2,'parent':A,'parent_uuid':U1}),
        )
        for command,wanted in cases:
            with self.subTest(command=command):
                req=dispatch.parse_ssh_command(command)
                self.assertEqual(req,wanted)
                argv=gate.parse_request(json.dumps(req).encode())
                self.assertEqual(argv[:2],['receiver',req['op']])

    def test_adversarial_commands_refused(self):
        wrong=(
            '', 'ls', 'bash -i', 'sudo -n id', 'btrfs-replication receiver bootstrap',
            'btrfs-replication receiver receive',
            'btrfs-replication receiver status ; id',
            'btrfs-replication receiver status --snapshot ../../etc/passwd',
            'btrfs-replication receiver status --snapshot '+B+' --extra yes',
            'btrfs-replication receiver status\nwhoami',
            f'btrfs-replication receiver advance --snapshot {A} --uuid {U2} --parent {B} --parent-uuid {U1}',
            f'btrfs-replication receiver receive --snapshot {B} --uuid {U2} --parent {A} --parent-uuid {U1} --parent-uuid {U1}',
        )
        for case in wrong:
            with self.subTest(case=case):
                with self.assertRaises(dispatch.Reject): dispatch.parse_ssh_command(case)

    def test_root_gate_rejects_bypass(self):
        bad=(
            b'{"op":"bootstrap","snapshot":null}',
            b'{"op":"status","snapshot":null,"extra":"ok"}',
            b'{"op":"status","snapshot":null,"snapshot":null}',
            b'{"op":"receive","snapshot":"../../bad","uuid":"bad","parent":"bad","parent_uuid":"bad"}',
            b'{"op":"status","snapshot":"20260101-000000Z","path":"/etc/shadow"}',
            b'{"op":"advance","snapshot":"20261112-030019Z","uuid":"'+U2.encode()+b'","parent":"20261113-030001Z","parent_uuid":"'+U1.encode()+b'"}',
        )
        for case in bad:
            with self.subTest(case=case):
                with self.assertRaises(gate.Reject): gate.parse_request(case)

    def test_header_read_does_not_consume_binary_stream(self):
        request={'op':'receive','snapshot':B,'uuid':U2,'parent':A,'parent_uuid':U1}
        header=json.dumps(request).encode()+b'\n'
        stream=b'\x00\xff\x80\n\rBTRFS binary\x00\x11'*17
        readfd,writefd=os.pipe()
        try:
            os.write(writefd,header+stream)
            os.close(writefd);writefd=-1
            self.assertEqual(gate.parse_request(gate.read_header(readfd))[1], 'receive')
            data=b''
            while len(data)<len(stream):
                fragment=os.read(readfd,len(stream)-len(data))
                self.assertTrue(fragment)
                data+=fragment
            self.assertEqual(data,stream)
        finally:
            os.close(readfd)
            if writefd>=0:os.close(writefd)

    def test_sudoers_and_provisioning_do_not_grant_all(self):
        sudo=(ROOT/'templates/btrfs-0041-service-sudoers.j2').read_text()
        self.assertNotIn('NOPASSWD:ALL', sudo)
        self.assertNotIn('NOPASSWD: ALL',sudo)
        self.assertEqual(sudo.count('""'),2)
        for name in ('sender-cycle','receiver-gate'):
            self.assertIn(name+'-0041 ""',sudo)
        tasks=(ROOT/'tasks/service-identities-0041.yaml').read_text()
        self.assertIn('sole root-managed forced-command',tasks)
        self.assertIn('restrict,command=',tasks)
        self.assertIn('no_log: true',tasks)
        self.assertNotIn('state: started',tasks)
        self.assertNotIn('daemon_reload:',tasks)
        self.assertIn('btrfs-native-push-0041-candidate.service',tasks)
        defaults=(ROOT/'defaults/main.yaml').read_text()
        self.assertIn('btrfs_0041_additive_enabled: false',defaults)

if __name__=='__main__':
    unittest.main(verbosity=2)
