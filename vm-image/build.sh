#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IMAGE_NAME="5map-edge"
DISK_SIZE="20G"
RAM="2048"
CPUS="2"

echo "=== 5map Edge Node VM Builder ==="

# Check for cloud image
if [ ! -f /tmp/debian12-cloud.qcow2 ]; then
    echo "Downloading Debian 12 cloud image..."
    wget -q --show-progress -O /tmp/debian12-cloud.qcow2 \
        "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2"
fi

# Create working copy and resize
echo "Creating VM disk ($DISK_SIZE)..."
cp /tmp/debian12-cloud.qcow2 "$SCRIPT_DIR/${IMAGE_NAME}.qcow2"
qemu-img resize "$SCRIPT_DIR/${IMAGE_NAME}.qcow2" "$DISK_SIZE"

# Create cloud-init ISO
echo "Building cloud-init ISO..."
genisoimage -output "$SCRIPT_DIR/cloud-init.iso" \
    -volid cidata -joliet -rock \
    "$SCRIPT_DIR/user-data" "$SCRIPT_DIR/meta-data" 2>/dev/null || \
mkisofs -output "$SCRIPT_DIR/cloud-init.iso" \
    -volid cidata -joliet -rock \
    "$SCRIPT_DIR/user-data" "$SCRIPT_DIR/meta-data" 2>/dev/null || \
xorriso -as mkisofs -output "$SCRIPT_DIR/cloud-init.iso" \
    -volid cidata -joliet -rock \
    "$SCRIPT_DIR/user-data" "$SCRIPT_DIR/meta-data"

echo ""
echo "=== VM Image Built ==="
echo "QCOW2: $SCRIPT_DIR/${IMAGE_NAME}.qcow2"
echo "Cloud-init: $SCRIPT_DIR/cloud-init.iso"
echo ""
echo "To run with QEMU/KVM:"
echo "  qemu-system-x86_64 -enable-kvm -m ${RAM} -smp ${CPUS} \\"
echo "    -drive file=$SCRIPT_DIR/${IMAGE_NAME}.qcow2,format=qcow2 \\"
echo "    -cdrom $SCRIPT_DIR/cloud-init.iso \\"
echo "    -net nic -net user,hostfwd=tcp::8080-:8080,hostfwd=tcp::2222-:22 \\"
echo "    -nographic"
echo ""
echo "To convert for VirtualBox:"
echo "  qemu-img convert -f qcow2 -O vdi $SCRIPT_DIR/${IMAGE_NAME}.qcow2 $SCRIPT_DIR/${IMAGE_NAME}.vdi"
echo "  Then import the VDI in VirtualBox."
echo ""
echo "SSH access:"
echo "  ssh -p 2222 ossiem@localhost"
echo "  Password: ossiem"
echo ""
echo "Dashboard: http://localhost:8080"
