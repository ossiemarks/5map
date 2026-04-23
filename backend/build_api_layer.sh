#!/bin/bash
# Build Lambda deployment package with ML dependencies
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_ROOT/terraform/.build"
mkdir -p "$BUILD_DIR"

PACKAGE_DIR=$(mktemp -d)
trap "rm -rf $PACKAGE_DIR" EXIT

echo "[build] Installing sklearn + numpy into package..."
pip install --target "$PACKAGE_DIR" numpy scikit-learn -q

echo "[build] Copying handler and ML model..."
cp "$SCRIPT_DIR/handlers/api_handler.py" "$PACKAGE_DIR/"
cp -r "$PROJECT_ROOT/ml" "$PACKAGE_DIR/"

echo "[build] Creating zip..."
cd "$PACKAGE_DIR"
zip -r "$BUILD_DIR/api_handler_ml.zip" . -q

echo "[build] Built: $BUILD_DIR/api_handler_ml.zip"
