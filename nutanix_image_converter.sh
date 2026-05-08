#!/bin/bash

# ==============================================================================
# Nutanix VM to QCOW2 Image Converter
# ==============================================================================
# 
# PREREQUISITES:
# 1. This host must be whitelisted in the Nutanix Cluster NFS whitelist.
#    (Prism Element -> Settings -> Filesystem Whitelist)
# 2. Required packages: sshpass, qemu-utils (for qemu-img)
# 3. Ensure the local mount directory exists and has sufficient space.
#
# USAGE:
# 1. Edit the configuration section below with your cluster details.
# 2. Make the script executable: chmod +x nutanix_image_converter.sh
# 3. Run the script: ./nutanix_image_converter.sh
# ==============================================================================

# --- CONFIGURATION SECTION ---
REMOTE_HOST="<CLUSTER_FQDN_OR_IP>"
REMOTE_USER="admin"
REMOTE_PASS="<PASSWORD>"
CLUSTER_IP="<CVM_OR_VIP>"
LOCAL_NFS_MOUNT="/home/nutanix/ntnx-images"
# ----------------------------

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

# Function to run SSH commands
ssh_run() {
    sshpass -p "$REMOTE_PASS" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=quiet "$REMOTE_USER@$REMOTE_HOST" "source /etc/profile && $1"
}

# 1. Dependency Check
if ! command -v sshpass &> /dev/null; then
    echo -e "${RED}Error: sshpass is not installed.${NC}"
    exit 1
fi

if ! command -v qemu-img &> /dev/null; then
    echo -e "${RED}Error: qemu-img is not installed (package: qemu-utils).${NC}"
    exit 1
fi

# 2. Fetch VM list
echo "Fetching VM list from $REMOTE_HOST..."
VM_LIST=$(ssh_run "acli vm.list")
if [ -z "$VM_LIST" ]; then
    echo -e "${RED}Error: Could not fetch VM list. Check configuration and connectivity.${NC}"
    exit 1
fi

echo -e "${GREEN}Available VMs:${NC}"
echo "$VM_LIST" | awk 'NR>1 {print NR-1") " $1}'
read -p "Select VM number to convert: " VM_NUM

VM_NAME=$(echo "$VM_LIST" | awk -v num="$VM_NUM" 'NR==num+1 {print $1}')
if [ -z "$VM_NAME" ]; then
    echo -e "${RED}Invalid selection.${NC}"
    exit 1
fi

echo "Selected VM: $VM_NAME"

# 3. Get VM disk details
echo "Fetching disk details for $VM_NAME..."
VM_INFO=$(ssh_run "acli vm.get $VM_NAME include_vmdisk_paths=1")

# Extract the disk path (ignoring CD-ROMs and small disks)
VM_DISK_PATH=$(echo "$VM_INFO" | awk '
    /disk_list \{/ { in_disk=1; brace_level=1; is_cdrom=0; temp_path=""; size=0; next }
    in_disk {
        if ($0 ~ /\{/) brace_level++
        if ($0 ~ /\}/) brace_level--
        if ($0 ~ /cdrom: True/) is_cdrom=1
        if ($0 ~ /vmdisk_nfs_path: /) { temp_path=$2; gsub(/"/, "", temp_path) }
        if ($0 ~ /vmdisk_size: /) size=$2
        if (brace_level == 0) {
            if (is_cdrom == 0 && temp_path != "" && size > 1073741824) {
                print temp_path
                exit
            }
            in_disk=0
        }
    }
')

if [ -z "$VM_DISK_PATH" ]; then
    echo -e "${RED}Error: Could not retrieve a valid disk path.${NC}"
    exit 1
fi

QEMU_SOURCE="nfs://$CLUSTER_IP$VM_DISK_PATH"
IMAGE_NAME="${VM_NAME}_$(date +%Y%m%d_%H%M%S)"
DEST_FILE="$LOCAL_NFS_MOUNT/$IMAGE_NAME.qcow2"
LOG_FILE="$LOCAL_NFS_MOUNT/logs/$IMAGE_NAME.log"

mkdir -p "$LOCAL_NFS_MOUNT/logs"

# 4. Perform conversion
echo -e "${GREEN}Starting conversion...${NC}"
echo "Source:      $QEMU_SOURCE"
echo "Destination: $DEST_FILE"

nohup qemu-img convert -p -c -O qcow2 "$QEMU_SOURCE" "$DEST_FILE" > "$LOG_FILE" 2>&1 &

echo ""
echo "Conversion started in background."
echo "To monitor progress, run: tail -f $LOG_FILE"
