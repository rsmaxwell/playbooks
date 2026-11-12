# Ansible Playbooks Development Instructions

## Purpose

This repository contains the Ansible playbooks used to configure and deploy the user's Ubuntu systems and application stacks.

The playbooks currently manage areas including:

- base/bootstrap configuration;
- Docker installation;
- application deployment;
- shared infrastructure;
- nginx;
- Cloudflare Tunnel integration;
- firewall rules;
- PostgreSQL;
- Mosquitto;
- Jenkins/builder services;
- Archiva;
- Diaries;
- Ledger;
- development tooling;
- Btrfs;
- local backups;
- remote backups;
- filesystem snapshots.

The main Ansible controller is typically an Ubuntu machine and the playbooks are executed against remote Ubuntu hosts.

Changes to this repository can affect live systems.

Treat operational safety, idempotency, variable precedence, secret handling, generated configuration, Docker state, and service restart behaviour as first-class concerns.

Do not treat an Ansible change as complete merely because the YAML parses.

A change should be understandable in terms of:

```text
source playbook/role
        |
        v
Ansible variables and precedence
        |
        v
generated/copied files
        |
        v
systemd / Docker Compose / host configuration
        |
        v
running service
```

When investigating a deployment problem, inspect the entire path.

---

# Current Repository Structure

The current repository contains top-level playbooks such as:

```text
archiva.yaml
bootstrap.yaml
btrfs.yaml
builder.yaml
development.yaml
diaries.yaml
infrastructure.yaml
ledger.yaml
backup-collection.yaml
mosquitto.yaml
postgres.yaml
btrfs-replication.yaml
snapshots.yaml
```

Important roles currently include:

```text
roles/
├── archiva/
├── bootstrap/
├── btrfs/
├── builder/
├── development/
├── diaries/
├── docker/
├── infrastructure/
├── ledger/
├── local-backup/
├── mosquitto/
├── postgres/
├── remote-backup/
└── snapshots/
```

Several application/infrastructure roles depend on the shared Docker role using role metadata.

Examples currently include:

```text
builder
development
diaries
infrastructure
ledger
local-backup
```

Before adding Docker installation logic to one of those roles, check whether the existing `docker` role dependency already provides it.

---

# Repository and Runtime Source of Truth

The source in the current Codex workspace is authoritative for playbook code.

However, deployment behaviour also depends on external inventory and secret data that may live outside this Git repository, commonly under paths such as:

```text
/etc/ansible/hosts
/etc/ansible/group_vars/
/etc/ansible/host_vars/
```

Those external files can override role defaults.

When investigating unexpected values, never inspect only:

```text
roles/<role>/defaults/main.yaml
```

Also inspect the effective inventory variables for the target host/group.

The source-of-truth precedence for diagnosing a deployment is conceptually:

```text
role defaults
    |
inventory/group variables
    |
host variables
    |
play variables
    |
extra variables
    |
effective Ansible value
```

Exact Ansible precedence rules are more detailed than this diagram.

Do not make assumptions about effective values without checking where a variable is defined.

---

# Inventory Variable Safety

Inventory data may contain:

- hostnames;
- application mode selections;
- image tags;
- network names;
- ports;
- passwords;
- encrypted Ansible Vault values;
- Cloudflare tokens;
- JWT secrets;
- database credentials;
- NAS credentials.

Do not copy real secrets into Git-tracked role defaults or templates.

Do not expose decrypted secret values in reports, logs, diffs, or generated examples.

When showing a value from inventory, redact sensitive material.

For example, report:

```text
vault_ledger_db_password: <redacted>
```

rather than the decrypted value.

Encrypted `!vault` blocks are still secrets and should not be casually duplicated into new files.

---

# Ansible Variable Design

Prefer clear ownership of variables.

A useful general model is:

```text
roles/<app>/defaults/main.yaml
    = normal/default behaviour for the application

group_vars
    = intentional environment/group override

host_vars
    = intentional host-specific override

--extra-vars
    = explicit one-run override
```

Do not put ordinary application defaults in `host_vars` merely because a host currently uses them.

Doing so makes the effective deployment harder to understand and causes stale overrides to silently defeat later role-default changes.

Conversely, genuinely host-specific values belong in inventory rather than being hard-coded into a reusable role.

---

# Docker Image Names and Tags

Application image names and default release tags should be easy to understand.

For independently versioned components, prefer explicit variables such as:

```text
diaries_client_image_name
diaries_client_image_tag

diaries_responder_image_name
diaries_responder_image_tag

ledger_client_image_name
ledger_client_image_tag

ledger_server_image_name
ledger_server_image_tag
```

Where a role has a normal production/default release, prefer defining that default in:

```text
roles/<app>/defaults/main.yaml
```

Inventory should override it only when a host/group intentionally differs.

Avoid unnecessary fallback chains such as:

```text
common image tag
    -> component default tag
    -> effective component tag
```

unless the repository genuinely supports and tests all of those deployment modes.

When simplifying tag logic, search all references first.

---

# Diagnosing Stale or Unexpected Docker Images

When a target runs an unexpected image, investigate in this order:

1. role default;
2. group variables;
3. host variables;
4. play variables;
5. command-line `--extra-vars`;
6. rendered/generated `compose.yaml`;
7. `docker compose config`;
8. running container configuration;
9. running image ID;
10. embedded application build/version information.

Do not assume:

```text
edited role default == effective host value
```

An inventory override can have higher precedence.

Do not assume:

```text
correct compose tag == correct running image
```

The stack may not have been recreated or the image may not have been pulled.

Do not assume:

```text
same textual tag == same image contents
```

Mutable tags can point at changed image IDs.

---

# Application Deployment Model

Applications such as Diaries and Ledger are deployed using generated Docker Compose projects under a user's projects directory.

A common model is:

```text
{{ ansible_facts['env']['HOME'] }}/projects/<application>
```

Examples include:

```text
~/projects/diaries
~/projects/ledger
~/projects/infrastructure
```

Roles typically:

1. install prerequisite utilities;
2. copy or template project files;
3. render environment files;
4. render Docker Compose configuration;
5. install scripts;
6. install systemd units;
7. notify handlers;
8. start/restart services.

When changing deployment behaviour, identify which stage owns the affected file.

Do not patch generated files manually on the target as the long-term fix if Ansible owns them.

---

# Generated Files

Files generated by templates should be treated as derived artifacts.

Examples include:

```text
.env
compose.yaml
systemd unit files
nginx location files
shell scripts
service configuration
```

If generated output is wrong:

```text
fix the Ansible source/template
        |
rerun playbook
        |
verify generated output
```

Do not treat a target-side hand edit as the completed fix.

If temporary manual edits are used diagnostically, record them and ensure they are represented in source before completion.

---

# Templates

Jinja templates live primarily under:

```text
roles/<role>/templates/
```

When editing a template:

- inspect all variables it references;
- confirm where each variable is defined;
- consider undefined-variable behaviour;
- preserve quoting appropriate to the destination format;
- consider YAML, shell, nginx, JSON, environment-file, and systemd syntax independently.

Ansible/Jinja quoting that is correct for YAML is not automatically correct for shell or JSON output.

After a template change, inspect the rendered target file.

---

# Role Defaults

Role defaults should:

- be safe;
- be reusable;
- express normal behaviour;
- avoid embedding real secrets;
- use consistent naming;
- be documented where behaviour is not obvious.

Do not place secrets directly in:

```text
roles/<role>/defaults/main.yaml
```

Use vault-backed inventory variables for secrets.

Defaults are intentionally low precedence.

When a user reports that changing a default had no effect, check inventory overrides before changing the role logic.

---

# Role Metadata and Dependencies

Some roles declare dependencies in:

```text
roles/<role>/meta/main.yaml
```

For example, several roles depend on:

```text
role: docker
```

Before adding prerequisite tasks to an application role:

1. inspect `meta/main.yaml`;
2. inspect the dependency role;
3. determine whether the prerequisite is already guaranteed.

Avoid duplicating Docker installation logic across roles.

Role dependencies should remain explicit and minimal.

---

# Utility Package Tasks

Several roles contain:

```text
tasks/utilities.yaml
```

These install utilities such as:

```text
jq
tree
zip
unzip
curl
cifs-utils
smbclient
```

When adding a utility:

- add it only where required;
- consider whether it belongs in a common role;
- preserve idempotency;
- use `state: present`;
- avoid repeatedly running unnecessary package-management operations if a cleaner shared pattern exists.

The repository currently has similar utility tasks across multiple roles.

Prefer consistency when modifying them.

Do not perform a large utility-role refactor as part of an unrelated defect unless explicitly requested.

---

# Privilege Escalation

Use `become: true` only for tasks that genuinely require root privileges.

Examples include:

- apt package installation;
- systemd changes;
- firewall configuration;
- privileged system files;
- Docker installation where required.

Files under the application user's home directory should generally be created with the appropriate user ownership rather than root ownership.

Be aware of changes in Ubuntu/sudo behaviour when upgrading operating systems.

If a `become` task fails on a newer Ubuntu release:

- inspect the actual error;
- check Ansible and Python compatibility;
- check sudo configuration;
- do not blindly replace all privilege escalation mechanisms.

---

# File Ownership and Permissions

Always consider:

```text
owner
group
mode
```

for copied or templated files.

Secrets should generally not be world-readable.

For example, configuration containing:

- database passwords;
- JWT signing secrets;
- MQTT responder passwords;
- Cloudflare tokens;

should normally have restrictive permissions such as:

```text
0600
```

unless the runtime service genuinely requires broader read access.

Executable scripts normally require executable mode.

Generated service and nginx configuration normally do not.

Do not broaden permissions simply to make an error disappear without understanding which user needs access.

---

# Secret Files

Secret-bearing files deserve explicit review.

Potential examples include:

```text
.env
responder configuration
application properties
password files
Cloudflare environment/configuration
Jenkins credentials support files
database configuration
```

When a template contains secret values:

- use restrictive target permissions;
- avoid logging rendered contents;
- avoid `debug: var=` for the secret;
- use `no_log: true` where task output could reveal it;
- consider whether the secret is actually needed in that generated file.

Do not expose Ansible Vault plaintext in Codex responses.

---

# Idempotency

Idempotency is a core requirement.

A clean second run of a playbook should normally produce:

```text
changed=0
```

unless the role deliberately performs a non-idempotent operation.

When a user reports repeated changes, investigate the exact task.

Common causes include:

- `command` or `shell` with `changed_when: true`;
- timestamps in generated files;
- nondeterministic template output;
- permission/ownership mismatch;
- commands that always modify files;
- Docker/network inspection implemented as a changing task;
- scripts copied with changing metadata;
- handlers triggered unnecessarily;
- user-management commands without proper existence checks.

Do not merely add:

```yaml
changed_when: false
```

to silence a real state change.

Use it only when the command genuinely performs a read/check operation.

---

# Check Tasks and Assertions

Several roles contain `check.yaml` or explicit validation tasks.

Use assertions for preconditions that must be true before a destructive or complex deployment.

Good validation examples include:

- allowed frontend mode;
- required shared Docker network exists;
- required shared nginx container exists;
- required directory exists;
- required vault variable is provided;
- mutually incompatible options are rejected.

Fail early with a useful message rather than letting a later template or Docker command fail obscurely.

Validation tasks should normally be idempotent and non-changing.

---

# Handlers

Handlers restart or reload services after changes.

Be cautious with handlers because a harmless configuration change can cause application downtime.

Current patterns include listeners such as:

```text
Restart systemd
Reload systemd
Restart infrastructure stack
Restart diaries stack
Restart ledger stack
```

When editing notifications:

- make sure the handler name/listen target is correct;
- avoid unnecessary full-stack restarts;
- use reload where appropriate and safe;
- ensure systemd is reloaded when unit files change;
- understand whether `state: started` or `state: restarted` is intended.

Do not notify a handler under a listener name that no matching handler consumes.

Check current naming carefully; not all roles use exactly the same listener wording.

---

# systemd and Docker Compose

Several application stacks are managed with systemd units wrapping Docker Compose.

Typical units include:

```text
diaries-compose.service
ledger-compose.service
infrastructure-compose.service
mosquitto-compose.service
postgres-compose.service
archiva-compose.service
```

When a systemd unit template changes:

1. render/copy unit;
2. notify daemon reload;
3. restart/start the correct unit if required;
4. inspect `systemctl status`;
5. inspect Docker containers;
6. inspect service logs.

Do not assume `docker compose up` performed manually is equivalent to the deployed systemd-managed state.

---

# Start, Stop, Status and Log Scripts

Roles generate operational shell scripts.

Typical script names include:

```text
start.sh
stop.sh
status.sh
logs.sh
shell-prompt-*.sh
```

These scripts are part of the supported operating model and should be kept coherent across applications.

When modifying one application's scripts, compare the equivalent pattern in other applications where helpful.

Avoid copy/paste errors involving:

- wrong project name;
- wrong container name;
- wrong service name;
- wrong compose path;
- wrong nginx file;
- wrong shared network;
- wrong log file.

Scripts should return useful exit status and diagnostic output.

---

# Shared vs Standalone Frontend Architecture

Diaries and Ledger support two frontend topologies:

```text
standalone
shared
```

## Standalone

The application stack owns its own frontend/nginx service and related host exposure.

Conceptually:

```text
application compose stack
    ├── client
    ├── server/responder
    ├── database/mqtt as applicable
    └── nginx
```

Depending on the application, standalone mode may also own:

- host HTTP exposure;
- Cloudflare Tunnel;
- firewall changes.

## Shared

The application does not own its own public nginx.

Instead, application browser-facing containers join an external infrastructure Docker network.

The infrastructure nginx routes application paths to the containers.

Conceptually:

```text
infrastructure stack
    └── shared nginx
           |
           +--> Diaries
           |
           +--> Ledger
           |
           +--> other applications
```

When changing frontend topology, always consider both modes.

Do not fix shared mode by breaking standalone mode, or vice versa.

---

# Shared Docker Network

Shared frontend mode requires an external Docker network, currently configured through application defaults such as:

```text
diaries_shared_network_name
ledger_shared_network_name
```

These may fall back to a shared variable such as:

```text
shared_network_name
```

Shared mode should validate that the network exists before deploying the application.

Do not silently create a differently named network inside the application role if infrastructure is intended to own it.

The infrastructure stack should remain the owner of shared frontend infrastructure.

---

# Shared nginx Location File Pattern

The current established pattern is:

```text
infrastructure/nginx/config/files/<app>.conf
```

contains the persistent source file.

While the application is running, a symlink exists under:

```text
infrastructure/nginx/config/conf.d/locations/<app>.conf
```

The application's `start.sh` activates the route by creating the symlink.

The application's `stop.sh` removes the active symlink before stopping containers.

Conceptually:

```text
config/files/app.conf
        |
        | symlink while app active
        v
config/conf.d/locations/app.conf
```

This is deliberate.

It allows shared nginx to continue starting successfully when an application stack is stopped.

Do not regress to installing application configuration permanently/directly into:

```text
config/conf.d/locations/
```

if the referenced upstream containers may be absent.

---

# Shared nginx Changes

When changing shared nginx integration:

1. verify the source file is installed under `config/files`;
2. verify the active path is a symlink;
3. verify the symlink target is correct both on host and inside nginx bind mounts;
4. run `nginx -t`;
5. reload nginx only after successful validation;
6. test application route;
7. stop application;
8. verify shared nginx remains valid;
9. restart application;
10. verify route is restored.

Never reload nginx after a failed `nginx -t`.

---

# Transitioning Between Shared and Standalone Modes

Roles contain cleanup logic for stale configuration when changing modes.

For example, standalone-mode tasks may remove:

- stale active shared nginx symlink;
- stale shared source file.

If the shared nginx container is running, the role may then:

- validate nginx;
- reload nginx.

Preserve this transition behaviour when modifying frontend mode logic.

A host should not retain stale routing from a previous mode.

---

# Infrastructure Role

The `infrastructure` role manages shared infrastructure concerns.

Current areas include:

```text
compose
copy
firewall
nginx
tunnel
utilities
```

It owns shared frontend facilities used by shared-mode application deployments.

Before changing application roles to manage something shared, check whether it belongs in infrastructure instead.

Examples likely owned by infrastructure include:

- shared nginx;
- shared external Docker network;
- shared Cloudflare frontend/tunnel;
- common ingress policy.

Keep ownership boundaries clear.

---

# nginx Resolver Configuration

Shared nginx may require Docker DNS resolver configuration.

When changing resolver settings:

- understand whether the configuration belongs globally or in an application location;
- avoid duplicating resolver directives unnecessarily;
- verify nginx syntax;
- consider startup behaviour when upstream containers are absent.

Prefer common resolver configuration in the shared nginx site/global configuration when multiple applications use it.

---

# Ledger Role

The Ledger role deploys the Ledger application.

Important areas currently include:

```text
roles/ledger/defaults/main.yaml
roles/ledger/tasks/check.yaml
roles/ledger/tasks/copy.yaml
roles/ledger/tasks/firewall.yaml
roles/ledger/tasks/shared-frontend.yaml
roles/ledger/tasks/standalone-frontend.yaml
roles/ledger/tasks/utilities.yaml
roles/ledger/templates/.env.j2
roles/ledger/templates/compose.yaml.j2
roles/ledger/templates/compose/ledger-compose.service.j2
roles/ledger/templates/scripts/
```

Ledger supports:

- independent client/server image tags;
- standalone/shared frontend;
- optional Cloudflare Tunnel;
- optional Internet exposure;
- configurable logging;
- optional request/response payload logging;
- database credentials;
- bootstrap administrator;
- JWT secret.

When changing Ledger deployment variables, cross-check the Ledger application repository documentation where available.

---

# Ledger Logging

The Ledger role currently exposes logging-related variables including concepts such as:

```text
ledger_log_level_root
ledger_log_level_application
ledger_log_level_spring_web
ledger_log_payloads_enabled
ledger_log_payload_max_bytes
ledger_log_payload_excluded_paths
ledger_log_payload_redacted_fields
```

When modifying logging:

- keep normal production defaults sensible;
- avoid exposing credentials;
- preserve explicit redaction;
- avoid excessive health-check noise;
- ensure logs remain useful for client API requests.

Payload logging is security-sensitive.

Do not enable sensitive payload capture accidentally.

---

# Ledger Internet Exposure and Firewall

Ledger standalone mode may optionally support Internet exposure.

Variables distinguish concepts such as:

```text
ledger_internet_exposed
ledger_direct_http_enabled
ledger_cloudflare_tunnel_enabled
```

Treat these choices separately.

Do not assume:

```text
Cloudflare enabled == direct HTTP should be exposed
```

or:

```text
Internet exposed == firewall should open every service
```

Follow least privilege.

Firewall changes should be scoped to the intended application exposure.

Shared mode leaves ingress responsibility to the infrastructure stack.

---

# Diaries Role

The Diaries role deploys the Diaries application.

Important areas currently include:

```text
roles/diaries/defaults/main.yaml
roles/diaries/tasks/compose.yaml
roles/diaries/tasks/copy.yaml
roles/diaries/tasks/pwfile.yaml
roles/diaries/tasks/shared-frontend.yaml
roles/diaries/tasks/standalone-frontend.yaml
roles/diaries/tasks/tools.yaml
roles/diaries/tasks/utilities.yaml
roles/diaries/templates/.env.j2
roles/diaries/templates/compose.yaml.j2
roles/diaries/templates/scripts/
```

Diaries includes:

- Angular client;
- Java responder;
- Mosquitto;
- PostgreSQL;
- diary image/static file access;
- NAS-related configuration;
- standalone/shared frontend;
- MQTT password-file generation.

When diagnosing a Diaries deployment problem, consider application-level client/responder/MQTT behaviour as well as the Ansible-generated configuration.

---

# Diaries MQTT Password File

The Diaries role contains explicit password-file generation tasks.

Password file handling is security-sensitive.

When changing it:

- preserve hashing requirements;
- preserve file permissions;
- avoid logging plaintext passwords;
- verify idempotency;
- verify users referenced by health checks/client/responder match ACL/configuration expectations.

Do not replace generated password handling with a committed plaintext password file.

---

# Diary Image/NAS Deployment Configuration

Diaries relies on external diary image content, which may be hosted on a NAS.

When changing volume mounts or NAS paths:

- distinguish host path from container path;
- verify CIFS/NFS/remote filesystem assumptions;
- verify `cifs-utils`/`smbclient` prerequisites where used;
- avoid destructive operations on the external image store;
- verify the target host can resolve/reach the NAS;
- verify permissions;
- verify the application URL mapping.

Do not delete or migrate external diary images unless explicitly requested.

---

# Builder Role

The `builder` role manages CI/build infrastructure such as Jenkins-related configuration.

Important areas include:

```text
roles/builder/tasks/
roles/builder/templates/compose/
roles/builder/templates/files/
roles/builder/templates/groovy/
roles/builder/templates/images/
roles/builder/templates/scripts/
```

The role depends on Docker.

It manages configuration for tools such as:

- Jenkins;
- Gradle;
- Maven;
- repository access;
- CI job creation;
- Jenkins credentials helper scripts.

Be cautious with Jenkins credentials.

Do not log secrets or generated credential contents.

When changing Jenkins image/version configuration, identify whether the image is managed by:

- a Compose template;
- `.env`;
- a generated config file;
- inventory;
- another build pipeline.

---

# Archiva Role

The Archiva role manages an Archiva service.

Important areas include:

```text
roles/archiva/defaults/main.yaml
roles/archiva/tasks/
roles/archiva/templates/.env.j2
roles/archiva/templates/compose.yaml.j2
roles/archiva/templates/compose/archiva-compose.service.j2
roles/archiva/templates/scripts/
```

Where Archiva participates in shared nginx routing, follow the same safe location-file pattern as the other shared services.

Avoid introducing one-off route activation behaviour that differs unnecessarily from Diaries/Ledger/Jenkins.

---

# Development Role

The development role manages development tooling.

Current tasks include areas such as:

```text
Gradle
Maven
utilities
job XML/generation tools
Compose
```

Before updating development tool versions:

- check compatibility with current project builds;
- inspect where version values are defined;
- avoid installing multiple competing versions unintentionally.

The development host is infrastructure for development, not an application runtime host.

---

# Docker Role

The Docker role is shared by multiple roles.

Changes to it can affect many hosts.

Treat modifications to:

- Docker repository setup;
- GPG keys;
- apt source configuration;
- package versions;
- Docker service configuration;

as high-impact.

When replacing an obsolete Docker apt repository configuration:

- remove obsolete repository files if necessary;
- avoid leaving duplicate apt sources;
- verify `apt update`;
- verify installed Docker version;
- verify existing containers survive expected service restarts.

Do not casually purge Docker data directories.

---

# Ubuntu Version Compatibility

Targets may run different supported Ubuntu releases.

Do not assume every host is on the same release.

When modifying apt repository setup or package names:

- check Ubuntu codename/release;
- avoid hard-coded obsolete repository distribution names;
- verify third-party repositories support the target release;
- consider changed package availability.

Newer Ubuntu releases can change behaviour around:

- sudo;
- apt source format;
- Python;
- systemd;
- Docker packages;
- networking.

When a playbook targets multiple Ubuntu generations, use facts and conditional logic where necessary.

---

# Apt Repository Management

When adding third-party repositories:

- use current vendor-supported methods;
- avoid deprecated `apt-key`;
- manage keyring files explicitly;
- use signed-by where appropriate;
- remove superseded repository definitions;
- ensure repeated runs do not duplicate sources.

If `apt update` reports conflicting source definitions, fix the repository ownership rather than suppressing the warning.

---

# PostgreSQL Role

The standalone `postgres` role manages a PostgreSQL Compose service.

Important areas include:

```text
roles/postgres/defaults/main.yaml
roles/postgres/tasks/
roles/postgres/templates/.env.j2
roles/postgres/templates/compose.yaml.j2
roles/postgres/templates/compose/postgres-compose.service.j2
```

Database state is persistent and potentially valuable.

Do not remove volumes or reset databases without explicit permission.

When modifying ports, credentials, or volume paths, consider existing stored data and application consumers.

---

# Mosquitto Role

The standalone `mosquitto` role manages a Mosquitto service.

Important areas include:

```text
roles/mosquitto/defaults/main.yaml
roles/mosquitto/tasks/
roles/mosquitto/templates/.env.j2
roles/mosquitto/templates/compose.yaml.j2
roles/mosquitto/templates/config/mosquitto.conf.j2
roles/mosquitto/templates/scripts/
```

When modifying MQTT ports/listeners:

- distinguish MQTT TCP from WebSockets;
- verify firewall exposure;
- verify credentials;
- verify ACL behaviour;
- verify health checks.

Do not weaken broker authentication/ACLs merely to resolve an application error without understanding the permissions required.

---

# Bootstrap Role

The bootstrap role can affect fundamental host access.

It may manage areas such as:

- initial user setup;
- sudoers;
- SSH service behaviour.

Changes here are high-risk because a mistake can lock out remote administration.

Before modifying SSH/sudo bootstrap logic:

- preserve an existing administrative access path;
- validate syntax before replacing configuration;
- avoid restarting SSH before configuration validity is known;
- understand current Ubuntu sudo behaviour.

Do not remove the currently working login method until the replacement is verified.

---

# Backup and Snapshot Roles

Roles include:

```text
local-backup
remote-backup
snapshots
btrfs
```

These can affect backup integrity and storage layout.

Treat operations involving:

- Btrfs subvolumes;
- snapshots;
- backup destinations;
- remote backup data;
- deletion/retention;

as potentially destructive.

Do not delete snapshots, backup trees, or Btrfs subvolumes without explicit approval.

When changing backup scripts:

- preserve source/destination semantics;
- verify dry-run/check capability where practical;
- verify retention logic;
- preserve permissions;
- avoid recursive backup loops.

---

# Local Backup Host

The local backup playbook currently targets a host such as:

```text
mars
```

Do not assume the backup host is disposable.

It may simultaneously be undergoing operating-system maintenance/upgrades while still serving as a required backup machine.

Preserve backup functionality unless the requested change explicitly schedules an interruption.

---

# Host Naming

The environment uses named machines for distinct functions.

Examples encountered in this project may include:

```text
mango
pluto
acorn
mars
bob
saturn
jupiter
```

Do not infer roles purely from hostnames.

Use inventory groups and current playbook targeting.

A machine may change function over time.

---

# Controller vs Target

Distinguish clearly between:

```text
Ansible controller
```

and:

```text
managed target host
```

Commands such as:

```text
ansible-playbook
ansible-inventory
ansible-vault
```

normally run on the controller.

Commands such as:

```text
docker compose
systemctl
journalctl
```

may need to run on the target.

When giving or executing commands, state which machine/context they apply to if ambiguity matters.

---

# Working Remotely Through Codex

This Playbooks project may be opened as a remote Codex project over SSH.

The remote workspace is the real playbooks source tree.

Do not assume the Windows PC has a synchronized copy.

Before making changes:

```text
pwd
git status
git branch --show-current
```

Confirm the repository path and branch.

Do not edit `/etc/ansible` inventory files unless the task explicitly requires it.

The Git repository and `/etc/ansible` inventory are separate configuration domains.

---

# Git Safety

Codex may freely inspect Git using read-only operations such as:

```text
git status
git diff
git log
git branch
git show
git grep
git ls-files
```

Do not perform destructive or history-changing operations unless explicitly requested:

```text
git commit
git push
git pull --rebase
git merge
git rebase
git reset --hard
git clean -fd
git checkout -- .
git restore .
git branch -D
```

Before editing a file with uncommitted changes, inspect its diff and preserve the user's work.

Do not overwrite local changes with GitHub versions.

The current working tree may contain uncommitted changes and can be newer than GitHub.

---

# Ansible Vault

Use Ansible Vault for secrets where the repository/inventory design requires it.

Do not decrypt secrets merely for convenience.

When the user explicitly needs to inspect a vault-encrypted value, use appropriate `ansible-vault`/Ansible commands and avoid exposing the result beyond what is required.

Do not commit decrypted vault material.

Do not generate replacement vault ciphertext unless the user explicitly requests a secret change.

---

# Testing Playbook Syntax

For any significant YAML/playbook change, run an appropriate syntax check before declaring completion.

For example:

```text
ansible-playbook --syntax-check <playbook>.yaml
```

Use the same inventory/configuration context normally used by this repository where needed.

Syntax checking alone is insufficient for correctness, but it is a minimum useful check.

---

# Ansible Linting

If `ansible-lint` is installed/configured for the repository, use it for changed roles/playbooks.

Do not introduce a new linting toolchain as part of an unrelated task without agreement.

If linting is unavailable, do not claim it passed.

---

# Dry Runs / Check Mode

Where practical and safe, consider:

```text
ansible-playbook --check --diff
```

before a live deployment.

However, not all tasks behave meaningfully in check mode, especially:

- command/shell tasks;
- Docker inspection;
- service operations;
- runtime validation.

Do not treat a successful check-mode run as proof that the live run will succeed.

Conversely, do not modify working tasks merely to force full check-mode support unless that is a goal.

---

# Diff Output and Secrets

`--diff` can reveal secrets when templates containing credentials are changed.

Before recommending or running:

```text
--diff
```

consider whether secret-bearing files will be displayed.

Use `no_log` or omit diff output where necessary.

Never paste secret-bearing diffs into reports.

---

# Safe Playbook Validation Sequence

For a normal role change, prefer this sequence:

```text
1. git status
2. inspect relevant role/defaults/templates
3. search variable usages
4. ansible-playbook --syntax-check
5. optional targeted --check where meaningful
6. run target playbook
7. inspect recap
8. inspect generated files
9. inspect service status
10. test application/service
11. rerun playbook
12. confirm idempotency
13. inspect git diff
```

For high-risk changes, add backup/rollback preparation before the live run.

---

# Idempotency Verification

After a successful deployment, a second run is particularly valuable.

Review the recap.

Unexpected changes on every run should be investigated.

For a stable host, a good target is:

```text
changed=0
failed=0
```

unless specific tasks are deliberately always-changing.

If one task always reports changed, determine whether:

- it actually mutates state;
- it should use a proper Ansible module;
- it needs `creates`, `removes`, or conditional logic;
- it is only a read command needing `changed_when: false`.

---

# Prefer Ansible Modules Over shell/command

Use purpose-built modules when practical:

```text
ansible.builtin.file
ansible.builtin.template
ansible.builtin.copy
ansible.builtin.apt
ansible.builtin.systemd
ansible.builtin.user
ansible.builtin.get_url
ansible.builtin.stat
ansible.builtin.assert
```

Prefer these to `shell`/`command` for state management because modules provide:

- idempotency;
- clearer intent;
- check-mode support;
- structured failure behaviour.

Use `command` or `shell` when the operation genuinely requires it.

Avoid `shell` when `command` is sufficient.

---

# Shell Safety in Templates

Generated shell scripts should generally:

- use a suitable shebang;
- quote variables;
- fail clearly;
- avoid accidental glob expansion;
- avoid deleting broad paths;
- distinguish absent resources from real failures.

If a script performs destructive work, require explicit arguments/confirmation where appropriate.

Do not use unquoted user-controlled paths in `rm`, `cp`, `mv`, or Docker commands.

---

# Docker Compose Template Validation

After changing `compose.yaml.j2`:

1. render it via Ansible on an appropriate target or controlled template process;
2. inspect the generated YAML;
3. run:

```text
docker compose config
```

4. check image names/tags;
5. check volumes;
6. check networks;
7. check ports;
8. check health checks;
9. check environment variables.

Do not assume valid Jinja produces valid Docker Compose.

---

# `.env` Template Validation

Environment files often feed Docker Compose and may contain secrets.

Check:

- variable spelling;
- duplicate keys;
- quoting;
- blank values;
- component-specific names;
- host vs container ports;
- secret permissions.

Do not rename an environment variable in one template without searching the corresponding Compose template and application.

---

# Host Port vs Container Port

Keep host and container port concepts distinct.

Prefer variable names that make direction clear, for example:

```text
*_HOST_PORT
```

for host exposure where appropriate.

A common source of bugs is using one variable name for:

- internal container port in one mode;
- external host port in another.

When standardizing names, update all consuming templates/scripts/documentation together.

---

# Docker Networks

Distinguish:

- internal Compose networks;
- externally owned shared networks.

For `external: true` networks:

- validate they exist;
- do not expect Compose to create them;
- document which role owns them.

Avoid hard-coding network names in multiple templates if a shared variable already exists.

---

# Cloudflare Tunnel

Some deployments optionally use Cloudflare Tunnel.

Treat tunnel ownership consistently with frontend topology:

```text
standalone app mode
    application may own application-specific tunnel

shared frontend mode
    infrastructure owns shared tunnel/frontend
```

Do not create duplicate tunnels for the same public hostname/path.

Cloudflare tokens are secrets.

Do not expose them in logs or committed files.

---

# Firewall Changes

Firewall tasks can make hosts unreachable.

Before changing ingress rules:

- identify the management/SSH access path;
- preserve required SSH;
- understand whether the host is LAN-only, Internet-exposed, or behind Cloudflare;
- open only required ports;
- avoid broad source ranges unless intended.

Do not apply a generic “production firewall” to every host without considering its role.

After firewall changes, verify remote access remains possible.

---

# nginx Validation

For any nginx configuration change:

```text
nginx -t
```

must succeed before reload/restart.

When nginx runs inside Docker, use the appropriate container command.

Do not restart/reload nginx blindly after writing configuration.

For shared nginx, confirm unrelated applications remain routable.

---

# Service Restart Minimisation

Ansible should change only what is necessary.

Examples:

- changing an application `.env` may require application restart;
- changing nginx route may require nginx reload;
- changing a systemd unit requires daemon-reload;
- installing `jq` does not require restarting application stacks.

Avoid coupling unrelated tasks to broad restart handlers.

---

# Production Data Safety

Application stacks may contain persistent production data.

Do not run or template operations that implicitly delete:

```text
PostgreSQL volumes
application database directories
NAS mounts/content
backup data
MQTT persistent state
```

without explicit approval.

Be especially cautious with:

```text
docker compose down -v
docker volume rm
rm -rf
```

These should not appear casually in deployment handlers or normal stop scripts.

---

# Backup Before Risky Changes

Before:

- database migration/reset;
- filesystem layout changes;
- major Docker volume changes;
- backup system changes;
- Btrfs restructuring;
- OS upgrade preparation;

identify a recovery path.

Do not claim a backup exists without checking.

---

# User Management

User-management tasks must be idempotent.

When creating/modifying users:

- use `ansible.builtin.user` where possible;
- manage groups explicitly;
- avoid commands that change passwords/metadata every run;
- preserve authorized SSH keys;
- avoid locking out the current administrative user.

If a user task changes every playbook run, inspect which attribute differs rather than suppressing change reporting.

---

# SSH Key Handling

Public keys may be read from the controller for deployment.

The public key is safe to place in:

```text
authorized_keys
```

Private SSH identity files must never be copied to managed hosts or committed to this repository unless a highly specific, reviewed use case requires it.

Do not expose private key contents.

---

# Jenkins / Builder Credentials

Builder-related roles may manage Jenkins credential scripts or configuration.

Credential automation must:

- avoid printing secrets;
- avoid committing plaintext credentials;
- distinguish test scripts from production credential updates;
- validate Jenkins availability.

Do not broaden credentials across jobs/users unnecessarily.

---

# Documentation and Comments

The repository README is currently minimal, so role/task comments are important.

When implementing non-obvious behaviour, add concise comments explaining:

- ownership;
- why a pattern exists;
- variable precedence;
- shared/standalone topology;
- why a cleanup task is required.

Avoid comments that merely restate the YAML.

If a workaround is historical and no longer required, verify and remove it rather than preserving misleading comments indefinitely.

---

# Naming Conventions

Prefer consistent names:

```text
role:task-group | Description
```

where the repository already follows this pattern.

Examples include:

```text
diaries:utilities | Install prerequisite packages
ledger:shared-frontend | Check the shared Docker network exists
```

Keep variable prefixes application-specific:

```text
diaries_...
ledger_...
infrastructure_...
```

Avoid generic variable names that can collide between roles unless they are intentionally shared.

---

# Tags

Roles may tag imported task groups, for example:

```text
utils
tools
copy
frontend
compose
check
firewall
```

When adding a task group:

- assign useful tags if the role uses them;
- ensure running a tag in isolation does not create an invalid partial state where possible;
- do not rely on tags to bypass essential validation unexpectedly.

Remember that users may intentionally run only part of a role during diagnostics.

---

# Fail Fast

Prefer clear validation over obscure downstream errors.

For example, if shared mode requires infrastructure, assert that:

- network exists;
- nginx container exists;
- config directories exist.

If a required vault variable is absent, fail with an explicit message.

If a mode variable accepts only known values, assert it.

Do not let an undefined/invalid setting surface later as a Docker error if Ansible can explain it earlier.

---

# Avoid Hidden Coupling

If one role relies on another role having been run previously, make that relationship clear through:

- role dependencies;
- validation;
- shared variables;
- documentation.

Do not rely on undocumented files that just happen to exist on one target.

Shared frontend mode is a good example: application roles should explicitly verify required infrastructure.

---

# Application/Playbook Coordination

When an issue involves an application such as Diaries or Ledger, consider both repositories.

For example:

```text
Ansible template says variable X
        |
application image expects variable Y
```

is a cross-repository defect.

Similarly:

```text
nginx route configured correctly
        |
application base path differs
```

must be resolved across both sides.

Do not change the playbook to compensate for an application bug without identifying the contract.

---

# Diaries Coordination

For Diaries deployment issues, consider:

- Angular client configuration;
- Java responder configuration;
- MQTT credentials/ACL;
- retained topic behaviour;
- PostgreSQL;
- diary image/NAS path;
- Docker volumes;
- nginx route;
- image versions.

A browser symptom may not be a playbook-only problem.

---

# Ledger Coordination

For Ledger deployment issues, consider:

- Angular client base path;
- Spring Boot API path;
- JWT/security;
- PostgreSQL/Flyway;
- nginx `/ledger/` and `/ledger/api/` routing;
- CORS;
- logging environment variables;
- client/server image versions.

Do not fix deployment routing by making the client/server inconsistent.

---

# Production vs Development Configuration

Production playbooks should not accidentally consume local-development defaults.

Keep production values explicit where needed.

Likewise, do not embed production hostnames/secrets into application source merely to make deployment easier.

The playbooks are the right place for deployment topology; application repositories are the right place for application defaults/contracts.

---

# Review Workflow for a Reported Deployment Bug

When the user reports a deployment issue:

1. identify the target host;
2. identify the playbook and role;
3. identify expected behaviour;
4. inspect current Git source;
5. inspect role defaults;
6. inspect target group_vars/host_vars;
7. inspect Ansible output;
8. inspect generated target files;
9. inspect systemd unit;
10. inspect Docker Compose effective configuration;
11. inspect running containers/images;
12. inspect relevant logs;
13. identify root cause;
14. implement the smallest coherent source fix;
15. syntax-check;
16. deploy;
17. verify runtime;
18. rerun for idempotency.

Do not jump from “old image is running” directly to changing Compose without checking variable precedence.

---

# Evidence Classification

When reporting an investigation, distinguish:

```text
Observed
Inferred
Confirmed root cause
Proposed fix
Validated
```

For example:

```text
Observed:
generated compose.yaml contains build-20

Observed:
role default says build-21

Observed:
host_vars/pluto.yaml defines build-20

Confirmed root cause:
host variable overrides role default
```

This is preferable to speculative conclusions.

---

# Safe Change Scope

Prefer small changes.

Do not:

- refactor every role;
- standardize every variable;
- rename all handlers;
- restructure the entire repository;

while fixing one deployment defect unless explicitly requested.

If a broader cleanup is worthwhile, report it as follow-up work.

---

# Cross-Role Consistency

Where several application roles implement the same operational concept, prefer consistent patterns.

Examples:

- utilities;
- systemd Compose units;
- start/stop scripts;
- shared nginx location activation;
- image tag defaults;
- status scripts;
- shell-prompt scripts.

Consistency reduces operational errors.

However, do not force sameness where applications have genuinely different requirements.

---

# Shared Location Pattern for Jenkins and Archiva

Where Jenkins/Archiva use the shared nginx infrastructure, prefer the same safe source-file/symlink pattern established for Diaries and Ledger.

The purpose is to prevent shared nginx from containing active upstream routes for services that are intentionally stopped.

When updating these roles, verify stop/start behaviour as well as initial deployment.

---

# File Copy vs Template

Use `copy` for static content.

Use `template` when Ansible variables or host-specific values are required.

Do not put Jinja expressions in a file managed with `copy` and expect rendering.

Conversely, avoid templating a static binary or large file unnecessarily.

---

# Target Paths

Avoid scattering literal absolute paths.

Where a role already defines:

```text
projects_dir
<app>_project_dir
```

reuse them.

This makes roles easier to deploy for different users/home directories.

Be mindful that:

```text
ansible_facts['env']['HOME']
```

reflects the remote user's environment/facts and can differ depending on privilege context.

---

# Ownership of `projects_dir`

Application project directories typically belong to the normal Ansible login user.

Do not create them as root unless explicitly required.

If `become` is used to create/copy into user project trees, specify ownership correctly.

Root-owned files inside a user's project directory can break operational scripts.

---

# Service Account vs Login User

Do not assume every process runs as `ansible_user`.

Check Compose/systemd configuration.

For file permissions, identify the actual runtime UID/GID where necessary.

This is especially relevant for:

- PostgreSQL volumes;
- nginx bind mounts;
- Mosquitto files;
- Jenkins;
- NAS mounts.

---

# Docker Volume Mounts

When modifying volume mounts:

- distinguish bind mount vs named volume;
- verify host source exists;
- verify permissions;
- verify container destination;
- understand whether mount hides image-baked content;
- preserve persistent data paths.

A wrong host path can silently produce an empty directory inside a container.

Do not create a new empty mount that masks expected application content.

---

# Health Checks

Health checks should verify useful service readiness without excessive noise.

When changing them:

- test the actual dependency;
- use least-privileged credentials;
- avoid overly aggressive intervals;
- suppress routine log noise where practical;
- preserve diagnostic usefulness.

Do not disable health checks solely because their log entries are inconvenient.

---

# Status and Diagnostics

After deployment, useful checks can include:

```text
systemctl status <unit>
docker compose ps
docker inspect
docker logs
nginx -t
curl
journalctl
```

Use the generated operational scripts where available.

Prefer targeted diagnostics over broad system changes.

---

# System Reboots

Do not reboot a managed host automatically unless the playbook/task explicitly owns that behaviour and the user expects it.

For package/kernel changes that require a reboot, report it.

On infrastructure hosts running multiple services, reboot impact can be substantial.

---

# Operating System Upgrades

Do not combine application-role changes with an OS distribution upgrade unless explicitly requested.

For upgrade preparation:

- verify backups;
- verify SSH access;
- verify boot configuration;
- verify Ansible compatibility;
- verify third-party repositories;
- verify Docker;
- verify application restart after reboot.

Keep OS lifecycle work separate from ordinary role maintenance.

---

# Source Bundle Hygiene

When creating source bundles for review:

- exclude `.git`;
- exclude build outputs;
- exclude caches;
- exclude large binaries unless needed;
- exclude secrets/local inventory where appropriate.

Do not remove source templates/scripts required to understand deployments.

---

# Before Making Changes

Before editing Playbooks source:

1. confirm the remote repository path;
2. run `git status`;
3. inspect uncommitted changes;
4. identify the relevant playbook;
5. identify the relevant role;
6. inspect role defaults;
7. inspect role metadata/dependencies;
8. inspect target inventory/group_vars/host_vars if required;
9. search all references to variables/files being changed;
10. inspect related handlers;
11. consider idempotency;
12. consider secrets;
13. consider service restart impact;
14. consider shared vs standalone mode where relevant;
15. consider other applications sharing infrastructure.

Do not overwrite uncommitted work.

---

# Before Declaring a Change Complete

Before saying a Playbooks change is complete:

1. list files changed;
2. explain why each changed;
3. run syntax check;
4. run linting if available/relevant;
5. inspect rendered/generated files where applicable;
6. deploy to the intended test/target host if requested;
7. inspect Ansible recap;
8. inspect service/systemd state;
9. inspect Docker state;
10. test the affected application/service;
11. rerun playbook to evaluate idempotency;
12. inspect `git diff`;
13. ensure no secrets are exposed;
14. identify any manual verification still needed;
15. document rollback/recovery concerns for risky changes.

Do not commit or push unless explicitly requested.

---

# Reporting Results

For a deployment defect, report:

```text
Target host
Playbook/role
Symptom
Evidence
Effective variable values relevant to the issue
Root cause
Files changed
Deployment/validation performed
Idempotency result
Remaining concerns
```

For a feature/change, report:

```text
Summary
Roles/playbooks affected
Files changed
Variable/interface changes
Generated target files affected
Restart/reload implications
Security/secret implications
Validation performed
Idempotency result
Manual follow-up
```

Redact secrets.

---

# High-Risk Operations Requiring Explicit Approval

Do not perform the following without explicit user approval:

```text
delete production database/volume
restore a database over current data
docker compose down -v
docker volume rm
docker system prune
delete NAS content
delete backup data
delete Btrfs subvolumes/snapshots
change SSH access in a way that may lock out the user
disable firewall/SSH safeguards
reset Git working tree
git clean
git reset --hard
force-push
decrypt and expose vault secrets
bulk-remove host/group variables
reboot a production/shared host
```

If a risky operation is needed, explain why and state the rollback/recovery plan.

---

# Important Playbooks Principles

## Ansible source owns managed files

Do not permanently fix target-generated files by hand.

## Inventory overrides matter

Role defaults are intentionally low precedence.

## Idempotency is a requirement

A second run should normally be clean.

## Shared infrastructure has shared consequences

A change to shared nginx/network/tunnel can affect multiple applications.

## Validate before reload/restart

Especially nginx, systemd, SSH, firewall, and Docker Compose.

## Preserve secrets

Vaults, passwords, tokens, private keys, and generated secret files must not leak.

## Avoid destructive convenience commands

Persistent Docker volumes, databases, NAS content, and backups are valuable.

## Consider the complete deployment path

A runtime problem may originate in:

```text
role defaults
    |
inventory override
    |
Jinja template
    |
generated .env/compose/config
    |
systemd
    |
Docker network/volume/image
    |
nginx/firewall/tunnel
    |
application
```

Investigate the relevant layers rather than changing the first file that appears related.

## Keep application and deployment contracts consistent

When Playbooks configure Diaries or Ledger, check the corresponding application expectations.

## Preserve working local changes

The current remote workspace can be newer than GitHub.

## Make the smallest coherent fix

Broader cleanup should be separate unless required for correctness.
