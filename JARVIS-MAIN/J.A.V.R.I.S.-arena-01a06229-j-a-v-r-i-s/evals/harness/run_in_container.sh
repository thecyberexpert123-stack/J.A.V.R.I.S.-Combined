#!/bin/sh
# Runs inside a distro container (repo mounted at /repo, cwd=/repo, root user).
# Usage: sh evals/harness/run_in_container.sh <distro-name>
set -eu
NAME="${1:?usage: run_in_container.sh <distro-name>}"
sh evals/harness/bootstrap.sh
export PYTHONPATH="$PWD/src"
export JARVIS_STATE_DIR="${JARVIS_STATE_DIR:-/tmp/jarvis-eval-state}"
python3 -m jarvis --json status > /tmp/jarvis-status.json
echo "container fingerprint: $(head -c 200 /tmp/jarvis-status.json)"
exec python3 evals/harness/m1_eval.py \
    --catalog evals/catalog/m1.json \
    --distro-name "$NAME" \
    --results "evals/results/$NAME.json"
