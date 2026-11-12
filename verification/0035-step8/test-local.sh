#!/usr/bin/env bash
set -eu
python3 "$(dirname "$0")/verify-source-contract.py"
python3 -c 'import yaml,sys; yaml.safe_load(open(sys.argv[1]))' "$(dirname "$0")/verify-acceptance.yaml"
