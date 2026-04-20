#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TF_DIR="$(dirname "$SCRIPT_DIR")/terraform"

log() { echo "[teardown] $(date '+%H:%M:%S') $1"; }

cd "$TF_DIR"

log "This will DESTROY all AWS resources for 5map."
log "Resources to be destroyed:"
terraform state list 2>/dev/null || {
    log "No terraform state found. Nothing to destroy."
    exit 0
}

echo ""
read -rp "Are you sure? Type 'yes' to confirm: " confirm
if [[ "$confirm" != "yes" ]]; then
    log "Aborted."
    exit 0
fi

log "Destroying..."
terraform destroy -auto-approve

log "Teardown complete."
