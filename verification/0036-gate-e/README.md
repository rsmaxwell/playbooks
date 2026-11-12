# 0036 Gate E — read-only retirement inventory

Run on `mango`, from `~/playbooks`:

```bash
bash verification/0036-gate-e/collect-gate-e-readonly.sh "$HOME/0036-gate-e-inventory-$(date -u +%Y%m%dT%H%M%SZ)"
```

SSH aliases for `pluto`, `mars`, `backup` must work non-interactively. Check every rc in collection.txt; a zero rc does **not** prove safe deletion or historical-restore compatibility. The inspection is read-only and intentionally does not use `sudo`; inaccessible paths must be reviewed separately by an authorised operator. `grep` inventory may include service names, not values/secrets. Do not publish full `.env` or vault files.

Next collect **independent Git SHAs from deployed Playbooks on mango**, legacy-generation size/ownership and whether any old publisher is still executing, and an explicit deletion/rollback-window decision. This package does **not** authorise deletion or deploy renamed runtime paths.
