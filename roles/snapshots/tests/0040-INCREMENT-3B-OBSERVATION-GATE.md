# 0040-FEAT — Increment 3B: Read-only SSH observation foundation

Status: SOURCE-REGRESSION PASS (locally); MANGO VERIFICATION PENDING.

This increment adds a bounded read-only observation contract. It does **not** install an SSH endpoint, acquire cross-host locks, collect live Btrfs evidence, write agreed-parent state, replace the legacy source-pin release, or authorise pruning. `collect` accepts a fixed argv supplied by its caller; callers must not construct that argv from untrusted input. The observation envelope intentionally cannot authorise any state transition or deletion.

The currently installed replication sender remains unchanged. Future integration must implement an allowlisted authenticated receiver endpoint under writer.lock, durable state exchange under ordered endpoint locks, live UUID and receipt validation, crash-consistent acknowledgement, preservation of old pins until bilateral confirmation, and disposable interrupted-transport tests. Review Ansible --check --diff before deployment. No production application at this gate.

Local regression: agreed-parent state 4/4; protocol 7/7; evidence 7/7; SSH observation 8/8; Python compilation PASS.
