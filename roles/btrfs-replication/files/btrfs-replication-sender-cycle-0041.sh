#!/bin/sh
# Fixed no-argument sudo entrypoint for the 0041 unprivileged sender service.
set -eu
if [ "$#" -ne 0 ]; then
    echo 'REFUSED: no arguments permitted' >&2
    exit 64
fi
# The existing root-owned replication program owns the whole transactional
# manager lock; its SSH subprocess is delegated to the dedicated non-admin user.
BTRFS_REPLICATION_IDENTITY_MODE=dedicated
export BTRFS_REPLICATION_IDENTITY_MODE
exec /usr/local/bin/btrfs-replication sender cycle
