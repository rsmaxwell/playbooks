#!/bin/bash

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

host="pluto"

ansible-playbook --limit ${host} archiva.yaml --vault-password-file ~/.vault_pass.txt


