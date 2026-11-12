# 0039-DEF Step 3 — read-only qgroup reconciliation and evidence manifest

This source tool is for **observational evidence only**. It uses only `btrfs subvolume list -a`, `btrfs subvolume list -d`, and `btrfs qgroup show -pcre`. It has **no deletion, rescan, quota-configuration, or cleanup capability**. An unmatched classification is **not** permission to remove a qgroup.

## Offline validation on mango

```bash
cd /home/richard/playbooks
python3 roles/snapshots/tests/verify-qgroup-audit.py
python3 -m py_compile roles/snapshots/files/btrfs-qgroup-audit.py
git diff --check
```

## Remote read-only use — run these in mango's SSH terminal

Target known native deletion IDs on `mars`, without remote installation:

```bash
cd /home/richard/playbooks
ssh -T mars 'sudo -n python3 - --filesystem /media/usb --inspect-id 0/20919 --inspect-id 0/20920' \
  < roles/snapshots/files/btrfs-qgroup-audit.py
```

Complete manifest on `mars`, **saved on mango**, not on the remote host:

```bash
cd /home/richard/playbooks
ssh -T mars 'sudo -n python3 - --filesystem /media/usb --full-manifest --inspect-id 0/20919 --inspect-id 0/20920' \
  < roles/snapshots/files/btrfs-qgroup-audit.py \
  > "$HOME/0039-mars-qgroup-manifest.json"
```

Complete manifest on `backup`, **saved on mango**:

```bash
cd /home/richard/playbooks
ssh -T backup 'sudo -n python3 - --filesystem / --full-manifest' \
  < roles/snapshots/files/btrfs-qgroup-audit.py \
  > "$HOME/0039-backup-qgroup-manifest.json"
```

Review outputs with `python3 -m json.tool <filename> > /dev/null`, `sha256sum <filename>`, and `ls -lh <filename>` on mango. These local files are diagnostic artifacts, not part of the Playbooks repository. Keep historical evidence separate from permanent operational source. Because shell redirection opens or truncates the local report before SSH runs, do not treat an empty file or a failed command as accepted evidence; check the command exit status, JSON and expected counts.

## Output rules and limitations

- Normal output is bounded to 20 non-active rows. `--inspect-id 0/ID` adds exact selected rows (or `null` if absent) to the report without widening the sample.
- `--full-manifest` adds **all** parsed qgroup rows (including limits, relationships and annotations), active subvolume IDs and paths, and pending-deletion IDs and paths to JSON stdout. Redirect the complete report to a local file. A full report on backup is much larger than the console summary.
- The `fingerprint_sha256` identifies the captured inventory content and is **not** a filesystem identity, replay token or cleanup authorisation.
- This version does **not yet** capture filesystem UUID, full quota state, active receive/replication state, checkpoint holds, or independently verify snapshot transfer references. Those are mandatory separate safety gates before considering cleanup.
- Double-reading the subvolume inventory catches observed changes but cannot rule out all concurrent mutations. Do not use the output to authorise qgroup deletion.
- The tool rejects unknown formats, malformed relationships, duplicate IDs and changing inventories. When it fails, preserve stderr and collect a small read-only header sample rather than weakening validation.

## Offline full-manifest validation (0039-DEF Step 3)

`files/validate-qgroup-manifest.py` validates **saved** complete JSON manifests
and corresponding filesystem-identity text evidence. It never runs SSH, Btrfs
or any mutating operation; an accepted report always declares
`deletion_authorized: false`. This checks manifest consistency and binds it
to separately captured UUID/mount evidence, **not** an atomic filesystem state
or any replication/checkpoint retention eligibility.

Run the isolated regression from the Playbooks checkout on `mango`:

```bash
python3 roles/snapshots/tests/verify-qgroup-manifest-validator.py
python3 -m py_compile roles/snapshots/files/validate-qgroup-manifest.py
```

For real evidence, run on Windows Cygwin from the **Diaries** repository root,
using the validator source copied from Playbooks to your local checkout (or
stream the local evidence via SSH to `mango` without copying it to `/tmp`).
The validator requires `--manifest`, `--identity`, `--expected-host` and
`--expected-uuid`. Expected filesystem UUIDs from 21 October 2026 evidence:

- `mars`: `72d1d8ea-900e-4fca-837f-1b1febec036c`, filesystem `/media/usb`
- `backup`: `b915f967-7cb4-4c14-b11b-f52209637a22`, filesystem `/`

Both files are in the Diaries defect's
`evidence/Step 03/inventory/<host>/` directory. Capture the validator output
under that same Step 03 evidence area. Never interpret a PASS as permission to
remove any qgroup: replication and protected-checkpoint reviews remain open.
