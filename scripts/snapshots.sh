#!/bin/bash
set -euo pipefail

usage() {
    echo "Usage: $0 [mars|backup] [--apply|--help]"
    echo "Default: mars, Ansible check mode (--check --diff)."
    echo "Use --apply for an explicitly authorised real deployment."
}

host="mars"
mode="check"
host_seen=false
mode_seen=false
for arg in "$@"; do
    case "$arg" in
        mars|backup)
            if [[ "$host_seen" == true ]]; then usage >&2; exit 2; fi
            host="$arg"
            host_seen=true
            ;;
        --apply)
            if [[ "$mode_seen" == true ]]; then usage >&2; exit 2; fi
            mode="apply"
            mode_seen=true
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
done

# 0046-FEAT: resolve this checkout from the wrapper location, including symlinks.
script_path="$(readlink -f -- "${BASH_SOURCE[0]}")" || exit 1
playbooks_dir="$(cd -- "$(dirname -- "$script_path")/.." && pwd -P)" || exit 1
inventory_file="$playbooks_dir/../inventory/hosts"
if [[ ! -f "$inventory_file" ]]; then
    printf 'ERROR: staged Ansible inventory not found: %s\n' "$inventory_file" >&2
    exit 1
fi
export ANSIBLE_INVENTORY="$inventory_file"
cd -- "$playbooks_dir" || exit 1
args=(snapshots.yaml --limit "$host" --tags snapshots
      --vault-password-file "$HOME/.vault_pass.txt")
if [[ "$mode" == "check" ]]; then
    args+=(--check --diff)
else
    args+=(--diff)
fi
exec ansible-playbook "${args[@]}"
