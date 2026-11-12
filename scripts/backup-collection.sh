#!/bin/bash
set -euo pipefail

usage() {
    echo "Usage: $0 [--apply|--help]"
    echo "Default: Ansible check mode (--check); --apply performs a real deployment. Neither mode prints rendered diffs."
}

mode="check"
case "${1:-}" in
    "") ;;
    --apply) mode="apply" ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
esac
if (( $# > 1 )); then
    usage >&2
    exit 2
fi

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

args=(
    backup-collection.yaml
    --limit mars
    --vault-password-file "$HOME/.vault_pass.txt"
)
if [[ "$mode" == "check" ]]; then
    args+=(--check)
fi

ansible-playbook "${args[@]}"
