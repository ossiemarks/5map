#!/bin/bash
set -euo pipefail

# Deploy trained models to SageMaker via S3 model registry
# Usage: ./scripts/deploy_sagemaker.sh [version]

REGION="${AWS_DEFAULT_REGION:-eu-west-2}"
BUCKET="fivemap-prod-models"
VERSION="${1:-1}"
MODEL_DIR="./models/trained"
SAGEMAKER_ROLE_ARN=""

log() { echo "[deploy-sagemaker] $(date '+%H:%M:%S') $1"; }

log "Deploying 5map models v${VERSION} to SageMaker (${REGION})"

# Check model artifacts exist
for artifact in env_mapper.pkl device_fp presence_lstm.pt; do
    path="${MODEL_DIR}/${artifact}"
    if [[ -e "$path" ]]; then
        log "Found: ${path}"
    else
        log "ERROR: Missing ${path} - run 'python -m ml.training.train_all' first"
        exit 1
    fi
done

# Ensure S3 bucket exists
log "Checking S3 bucket: ${BUCKET}..."
if ! aws s3api head-bucket --bucket "$BUCKET" --region "$REGION" 2>/dev/null; then
    log "Creating S3 bucket..."
    aws s3api create-bucket \
        --bucket "$BUCKET" \
        --region "$REGION" \
        --create-bucket-configuration LocationConstraint="$REGION"
    aws s3api put-bucket-versioning \
        --bucket "$BUCKET" \
        --versioning-configuration Status=Enabled
fi

# Package and upload models
log "Packaging model artifacts..."
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

# Package all models into a single model.tar.gz for SageMaker
cp "${MODEL_DIR}/env_mapper.pkl" "$TMPDIR/"
cp -r "${MODEL_DIR}/device_fp" "$TMPDIR/"
cp "${MODEL_DIR}/presence_lstm.pt" "$TMPDIR/"

# Include inference handler
cp ml/serving/sagemaker_handler.py "$TMPDIR/inference.py"

tar -czf "${TMPDIR}/model.tar.gz" -C "$TMPDIR" \
    env_mapper.pkl device_fp presence_lstm.pt inference.py

S3_KEY="models/v${VERSION}/model.tar.gz"
log "Uploading to s3://${BUCKET}/${S3_KEY}..."
aws s3 cp "${TMPDIR}/model.tar.gz" "s3://${BUCKET}/${S3_KEY}" --region "$REGION"

# Also upload individual models for registry
for model in env_mapper device_fp presence_lstm; do
    if [[ -d "${MODEL_DIR}/${model}" ]]; then
        tar -czf "${TMPDIR}/${model}.tar.gz" -C "${MODEL_DIR}" "${model}"
    elif [[ -f "${MODEL_DIR}/${model}.pkl" ]]; then
        tar -czf "${TMPDIR}/${model}.tar.gz" -C "${MODEL_DIR}" "${model}.pkl"
    elif [[ -f "${MODEL_DIR}/${model}.pt" ]]; then
        tar -czf "${TMPDIR}/${model}.tar.gz" -C "${MODEL_DIR}" "${model}.pt"
    fi
    aws s3 cp "${TMPDIR}/${model}.tar.gz" "s3://${BUCKET}/models/v${VERSION}/${model}.tar.gz" --region "$REGION"
    log "  Uploaded ${model} v${VERSION}"
done

# Get SageMaker role ARN from Terraform
log "Looking up SageMaker IAM role..."
SAGEMAKER_ROLE_ARN=$(aws iam get-role --role-name fivemap-prod-sagemaker-role --query 'Role.Arn' --output text 2>/dev/null || echo "")
if [[ -z "$SAGEMAKER_ROLE_ARN" ]]; then
    log "WARNING: SageMaker IAM role not found. Create via Terraform first."
    log "Models uploaded to S3 successfully. SageMaker endpoint creation skipped."
    log ""
    log "To create endpoint manually:"
    log "  1. Run: cd terraform && terraform apply"
    log "  2. Then re-run this script"
    exit 0
fi

# Create/update SageMaker model
MODEL_NAME="fivemap-inference-v${VERSION}"
ENDPOINT_NAME="fivemap-prod-endpoint"
ENDPOINT_CONFIG="fivemap-prod-config-v${VERSION}"

log "Creating SageMaker model: ${MODEL_NAME}..."
aws sagemaker create-model \
    --model-name "$MODEL_NAME" \
    --primary-container \
        Image="763104351884.dkr.ecr.${REGION}.amazonaws.com/pytorch-inference:2.1.0-cpu-py310" \
        ModelDataUrl="s3://${BUCKET}/${S3_KEY}" \
    --execution-role-arn "$SAGEMAKER_ROLE_ARN" \
    --region "$REGION" 2>/dev/null || log "Model already exists, continuing..."

# Create endpoint config
log "Creating endpoint config: ${ENDPOINT_CONFIG}..."
aws sagemaker create-endpoint-config \
    --endpoint-config-name "$ENDPOINT_CONFIG" \
    --production-variants \
        VariantName=AllTraffic,ModelName="$MODEL_NAME",InitialInstanceCount=1,InstanceType=ml.t2.medium \
    --region "$REGION" 2>/dev/null || log "Endpoint config already exists, continuing..."

# Create or update endpoint
EXISTING_ENDPOINT=$(aws sagemaker describe-endpoint --endpoint-name "$ENDPOINT_NAME" --region "$REGION" 2>/dev/null | head -1 || echo "")
if [[ -z "$EXISTING_ENDPOINT" ]]; then
    log "Creating SageMaker endpoint: ${ENDPOINT_NAME}..."
    aws sagemaker create-endpoint \
        --endpoint-name "$ENDPOINT_NAME" \
        --endpoint-config-name "$ENDPOINT_CONFIG" \
        --region "$REGION"
    log "Endpoint creating... (takes 5-10 minutes)"
else
    log "Updating SageMaker endpoint: ${ENDPOINT_NAME}..."
    aws sagemaker update-endpoint \
        --endpoint-name "$ENDPOINT_NAME" \
        --endpoint-config-name "$ENDPOINT_CONFIG" \
        --region "$REGION"
    log "Endpoint updating..."
fi

log ""
log "Deployment complete:"
log "  Models: s3://${BUCKET}/models/v${VERSION}/"
log "  Endpoint: ${ENDPOINT_NAME}"
log "  Region: ${REGION}"
log ""
log "Monitor status:"
log "  aws sagemaker describe-endpoint --endpoint-name ${ENDPOINT_NAME} --region ${REGION} --query 'EndpointStatus'"
