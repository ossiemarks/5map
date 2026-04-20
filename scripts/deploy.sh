#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TF_DIR="$PROJECT_ROOT/terraform"

STATE_BUCKET="fivemap-terraform-state"
LOCK_TABLE="fivemap-terraform-locks"
REGION="${AWS_REGION:-eu-west-2}"

log() { echo "[deploy] $(date '+%H:%M:%S') $1"; }

# Bootstrap S3 state backend if it doesn't exist
bootstrap_state() {
    log "Checking S3 state backend..."
    if ! aws s3api head-bucket --bucket "$STATE_BUCKET" 2>/dev/null; then
        log "Creating state bucket: $STATE_BUCKET"
        aws s3api create-bucket \
            --bucket "$STATE_BUCKET" \
            --region "$REGION" \
            --create-bucket-configuration LocationConstraint="$REGION"

        aws s3api put-bucket-versioning \
            --bucket "$STATE_BUCKET" \
            --versioning-configuration Status=Enabled

        aws s3api put-bucket-encryption \
            --bucket "$STATE_BUCKET" \
            --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

        log "State bucket created"
    fi

    if ! aws dynamodb describe-table --table-name "$LOCK_TABLE" --region "$REGION" 2>/dev/null; then
        log "Creating lock table: $LOCK_TABLE"
        aws dynamodb create-table \
            --table-name "$LOCK_TABLE" \
            --attribute-definitions AttributeName=LockID,AttributeType=S \
            --key-schema AttributeName=LockID,KeyType=HASH \
            --billing-mode PAY_PER_REQUEST \
            --region "$REGION"

        aws dynamodb wait table-exists --table-name "$LOCK_TABLE" --region "$REGION"
        log "Lock table created"
    fi
}

deploy() {
    cd "$TF_DIR"

    log "Running terraform init..."
    terraform init

    log "Running terraform plan..."
    terraform plan -out=tfplan

    echo ""
    log "Review the plan above. Proceed with apply?"
    read -rp "[y/N] " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        log "Aborted."
        rm -f tfplan
        exit 0
    fi

    log "Applying..."
    terraform apply tfplan
    rm -f tfplan

    log "Deploy complete."
    terraform output
}

# Main
case "${1:-deploy}" in
    bootstrap)
        bootstrap_state
        ;;
    deploy)
        bootstrap_state
        deploy
        ;;
    plan)
        cd "$TF_DIR"
        terraform init
        terraform plan
        ;;
    output)
        cd "$TF_DIR"
        terraform output
        ;;
    *)
        echo "Usage: $0 [bootstrap|deploy|plan|output]"
        exit 1
        ;;
esac
