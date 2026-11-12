#!/bin/bash
set -euo pipefail

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

# 1st argument — target host
# 2nd argument — common/default Ledger image tag
# 3rd argument — optional server image-tag override
# 4th argument — optional client image-tag override

host="${1:-pluto}"
ledger_version="${2:-integration}"
server_image_tag="${3:-}"
client_image_tag="${4:-}"

extra_vars=(
  -e "ledger_version=${ledger_version}"
)

if [[ -n "${server_image_tag}" ]]; then
  extra_vars+=(
    -e "ledger_server_image_tag=${server_image_tag}"
  )
fi

if [[ -n "${client_image_tag}" ]]; then
    extra_vars+=(
        -e "ledger_client_image_tag=${client_image_tag}"
    )
fi

ansible-playbook ledger.yaml \
  --limit "${host}" \
  --vault-password-file ~/.vault_pass.txt \
  "${extra_vars[@]}"
