# Deployment Guide: Nutanix Image Exporter

This guide provides detailed instructions for deploying the Nutanix Image Exporter web application as a production-grade service.

## 1. System Requirements
- Ubuntu 22.04 LTS (Recommended) or similar Linux distribution.
- Python 3.10+.
- `sshpass` and `qemu-utils` installed.
- Access to a Nutanix Cluster with NFS whitelist enabled for this host.

## 2. Preparation
### Install Dependencies
```bash
sudo apt update
sudo apt install -y python3-pip python3-venv sshpass qemu-utils curl
```

### Clone the Repository
```bash
git clone https://github.com/nutanixed/web-images.git
cd web-images
```

### Setup Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install flask ldap3 python-dotenv gunicorn
```

## 3. Configuration
Create a `.env` file in the project root:
```ini
SECRET_KEY="<RANDOM_STRING>"
LDAP_SERVER="ldap://<LDAP_SERVER_IP>:389"
LDAP_ADMIN_DN="cn=admin,dc=example,dc=com"
LDAP_ADMIN_PASSWORD="<LDAP_PASSWORD>"
LDAP_USER_SEARCH_BASE="ou=People,dc=example,dc=com"

REMOTE_HOST="<NUTANIX_CLUSTER_IP_OR_FQDN>"
REMOTE_USER="admin"
REMOTE_PASS="<NUTANIX_PASSWORD>"
CLUSTER_IP="<NUTANIX_NFS_IP>"
LOCAL_NFS_MOUNT="/home/nutanix/ntnx-images"
```

## 4. Production Deployment with Systemd
To ensure the application starts automatically on boot and restarts if it fails, use a systemd service unit.

### Create the Service File
```bash
sudo nano /etc/systemd/system/web-images.service
```

### Add the following content:
*(Adjust paths to match your installation)*
```ini
[Unit]
Description=Gunicorn instance to serve Nutanix Image Exporter
After=network.target

[Service]
User=nutanix
Group=nutanix
WorkingDirectory=/home/nutanix/web-images
Environment="PATH=/home/nutanix/web-images/.venv/bin"
ExecStart=/home/nutanix/web-images/.venv/bin/gunicorn --workers 4 --bind 0.0.0.0:5000 --timeout 300 app:app

[Install]
WantedBy=multi-user.target
```

### Enable and Start the Service
```bash
sudo systemctl daemon-reload
sudo systemctl enable web-images
sudo systemctl start web-images
```

### Check Status
```bash
sudo systemctl status web-images
```

## 5. Reverse Proxy with Nginx (Optional but Recommended)
For production environments, it is recommended to use Nginx as a reverse proxy.

### Install Nginx
```bash
sudo apt install -y nginx
```

### Configure Nginx
```bash
sudo nano /etc/nginx/sites-available/web-images
```

```nginx
server {
    listen 80;
    server_name image-exporter.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Enable the Site
```bash
sudo ln -s /etc/nginx/sites-available/web-images /etc/nginx/sites-enabled
sudo nginx -t
sudo systemctl restart nginx
```

## 6. Maintenance
### Monitoring Logs
```bash
# Systemd logs
journalctl -u web-images -f

# Nginx logs
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log
```

### Restarting the App
```bash
sudo systemctl restart web-images
```
