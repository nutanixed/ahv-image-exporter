# Nutanix Image Converter

This repository contains a tool to export Nutanix AHV VMs as QCOW2 images.

## Features
- **Web Interface**: Manage exports through a modern Flask-based web UI.
- **CLI Script**: Standalone bash script for command-line usage.
- **Secure**: Credentials managed via `.env` file.
- **Efficient**: Uses `qemu-img` with NFS direct access for high-speed conversion.

---

## Standalone CLI Usage

You can use the `nutanix_image_converter.sh` script independently of the web application.

### Prerequisites
1.  **NFS Whitelist**: Ensure your host's IP is added to the Nutanix Cluster's Filesystem Whitelist (Prism Element -> Settings -> Filesystem Whitelist).
2.  **Dependencies**:
    ```bash
    sudo apt update
    sudo apt install sshpass qemu-utils
    ```

### Setup
1.  Copy `nutanix_image_converter.sh` to your working directory.
2.  Make it executable:
    ```bash
    chmod +x nutanix_image_converter.sh
    ```

### Configuration
Edit the script and update the following variables in the **CONFIGURATION SECTION**:
- `REMOTE_HOST`: Cluster FQDN or IP.
- `REMOTE_USER`: Nutanix user (e.g., `admin`).
- `REMOTE_PASS`: Password.
- `CLUSTER_IP`: CVM or VIP for NFS access.
- `LOCAL_NFS_MOUNT`: Path where images should be saved.

### Running the Script
```bash
./nutanix_image_converter.sh
```
The script will:
1. Connect to the cluster and fetch the VM list.
2. Prompt you to select a VM by number.
3. Automatically find the correct disk path.
4. Start the conversion in the background.

---

## Web Application Usage

### Installation
1.  Install Python dependencies:
    ```bash
    pip install -r requirements.txt
    ```
2.  Configure your environment in `.env`:
    ```ini
    SECRET_KEY="your-secret-key"
    LDAP_SERVER="ldap://your-ldap-server"
    LDAP_ADMIN_DN="cn=admin,dc=example,dc=com"
    LDAP_ADMIN_PASSWORD="password"
    REMOTE_HOST="cluster-ip"
    REMOTE_USER="admin"
    REMOTE_PASS="password"
    CLUSTER_IP="cluster-nfs-ip"
    LOCAL_NFS_MOUNT="/path/to/mount"
    ```

### Running the App
```bash
python app.py
```
Access the UI at `http://localhost:5000`.

---

## Deployment
For detailed production deployment instructions (Systemd, Nginx, etc.), see [DEPLOYMENT.md](./DEPLOYMENT.md).
