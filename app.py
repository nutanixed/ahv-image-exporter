from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from ldap3 import Server, Connection, ALL
from dotenv import load_dotenv
import subprocess
import os
import re
from datetime import datetime

# Load environment variables
load_dotenv()

app = Flask(__name__)
# Static secret key for persistent sessions across restarts
app.secret_key = os.getenv("SECRET_KEY", "default-secret-key")
app.config['SESSION_COOKIE_NAME'] = 'nutanix_image_exporter'
app.config['PERMANENT_SESSION_LIFETIME'] = 43200 # 12 hours

# LDAP Configuration (from example)
LDAP_SERVER = os.getenv("LDAP_SERVER")
LDAP_ADMIN_DN = os.getenv("LDAP_ADMIN_DN")
LDAP_ADMIN_PASSWORD = os.getenv("LDAP_ADMIN_PASSWORD")
LDAP_USER_SEARCH_BASE = os.getenv("LDAP_USER_SEARCH_BASE")
LDAP_USER_ATTRIBUTE = "uid"

# Nutanix Configuration
# Target for SSH Management Commands
REMOTE_HOST = os.getenv("REMOTE_HOST")
# SSH Credentials for CVM
REMOTE_USER = os.getenv("REMOTE_USER")
REMOTE_PASS = os.getenv("REMOTE_PASS")
# Storage Endpoint for NFS Data Access
CLUSTER_IP = os.getenv("CLUSTER_IP")
# Local Path to Store Images
LOCAL_NFS_MOUNT = os.getenv("LOCAL_NFS_MOUNT")

def check_ldap_auth(username, password):
    if not username or not password:
        return False
    try:
        print(f"DEBUG: Attempting LDAP auth for {username} at {LDAP_SERVER}")
        server = Server(LDAP_SERVER, get_info=ALL)
        
        # Step 1: Bind as Service Account/Admin
        print(f"DEBUG: Step 1 - Binding as admin {LDAP_ADMIN_DN}")
        admin_conn = Connection(server, user=LDAP_ADMIN_DN, password=LDAP_ADMIN_PASSWORD, authentication='SIMPLE')
        if not admin_conn.bind():
            print(f"DEBUG: Admin bind failed: {admin_conn.result}")
            return False
            
        # Step 2: Search for User DN
        print(f"DEBUG: Step 2 - Searching for user {username}")
        search_filter = f"({LDAP_USER_ATTRIBUTE}={username})"
        admin_conn.search(LDAP_USER_SEARCH_BASE, search_filter, attributes=[])
        
        if not admin_conn.entries:
            print(f"DEBUG: User {username} not found in search")
            admin_conn.unbind()
            return False
            
        # Step 3: Extract User DN
        user_dn = admin_conn.entries[0].entry_dn
        print(f"DEBUG: Step 3 - Found user DN: {user_dn}")
        admin_conn.unbind()
        
        # Step 4: Verify User Credentials by Binding as the User
        print(f"DEBUG: Step 4 - Binding as user {user_dn}")
        user_conn = Connection(server, user=user_dn, password=password, authentication='SIMPLE')
        if user_conn.bind():
            print("DEBUG: LDAP Auth Success")
            user_conn.unbind()
            return True
        
        print(f"DEBUG: User bind failed: {user_conn.result}")
        return False
    except Exception as e:
        print(f"LDAP Error: {e}")
        return False

def ssh_run(command):
    # Using bash -l -c to ensure path and aliases are loaded
    cmd = [
        "sshpass", "-p", REMOTE_PASS,
        "ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=quiet",
        f"{REMOTE_USER}@{REMOTE_HOST}", f"bash -l -c '{command}'"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stderr:
        print(f"SSH STDERR: {result.stderr}")
    return result.stdout

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        auth_type = request.form.get('auth_type', 'ldap')
        
        if auth_type == 'ldap':
            if check_ldap_auth(username, password):
                session['user'] = username
                return redirect(url_for('index'))
        else:
            # Check local database/config
            if username == "nutanix" and password == os.getenv("LOCAL_PASS", "nutanix/4u"):
                session['user'] = username
                return redirect(url_for('index'))
        
        flash("Invalid credentials")
        return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/')
def index():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/api/vms')
def get_vms():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        output = ssh_run("acli vm.list")
        if not output:
            print("Error: Empty output from ssh_run(acli vm.list)")
            return jsonify({"vms": [], "error": "SSH command failed or returned empty"}), 500
        
        vms = []
        lines = output.strip().split('\n')
        exclude_patterns = ["CVM", "PCVM", "FSVM", "nkp-", "NTNX-"]
        
        for line in lines[1:]: # Skip header
            parts = line.split()
            if parts:
                vm_name = parts[0]
                # Filter out system and utility VMs (case-sensitive)
                if any(pattern in vm_name for pattern in exclude_patterns):
                    continue
                vms.append(vm_name)
        return jsonify({"vms": vms})
    except Exception as e:
        print(f"Exception in get_vms: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/convert', methods=['POST'])
def convert_vms():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    # New format: { "exports": [ { "vm_name": "...", "custom_name": "..." }, ... ], "global_prefix": "..." }
    data = request.json
    export_list = data.get('exports', [])
    global_prefix = data.get('global_prefix', '').strip()
    
    # Backward compatibility or simple format
    if not export_list:
        vm_names = data.get('vm_names', [])
        if not vm_names:
            single_vm = data.get('vm_name')
            if single_vm:
                vm_names = [single_vm]
        
        custom_name = data.get('custom_name', '')
        export_list = [{"vm_name": name, "custom_name": custom_name} for name in vm_names]

    if not export_list:
        return jsonify({"error": "No VMs provided"}), 400

    started_tasks = []
    errors = []

    for item in export_list:
        vm_name = item.get('vm_name')
        custom_name = item.get('custom_name', '').strip()
        
        try:
            # Determine image name
            name_parts = []
            if global_prefix:
                name_parts.append(re.sub(r'[^a-zA-Z0-9\-_]', '', global_prefix))
            
            if custom_name:
                name_parts.append(re.sub(r'[^a-zA-Z0-9\-_]', '', custom_name))
            else:
                # If no custom name, and it's a batch, use VM name to distinguish
                if len(export_list) > 1 or global_prefix:
                    name_parts.append(vm_name)
                else:
                    # Single export, no prefix, no custom name -> use timestamp
                    name_parts.append(f"{vm_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

            image_name = "_".join(name_parts)
            # Ensure it's not empty
            if not image_name:
                 image_name = f"{vm_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            # Logic from convert_vm.sh to get disk path
            vm_info = ssh_run(f"acli vm.get {vm_name} include_vmdisk_paths=1")
            
            # Improved extraction logic to handle nested braces in acli output
            disk_blocks = []
            start_idx = 0
            while True:
                match = re.search(r'disk_list \{', vm_info[start_idx:])
                if not match:
                    break
                
                block_start = start_idx + match.start()
                brace_count = 0
                current_idx = block_start + len('disk_list ')
                
                found_block = False
                for i in range(current_idx, len(vm_info)):
                    if vm_info[i] == '{':
                        brace_count += 1
                    elif vm_info[i] == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            disk_blocks.append(vm_info[block_start:i+1])
                            start_idx = i + 1
                            found_block = True
                            break
                
                if not found_block:
                    break

            vm_disk_path = None
            for block in disk_blocks:
                if 'cdrom: True' in block:
                    continue
                path_match = re.search(r'vmdisk_nfs_path: "(/[^"]+)"', block)
                size_match = re.search(r'vmdisk_size: (\d+)', block)
                
                if path_match:
                    temp_path = path_match.group(1)
                    size = int(size_match.group(1)) if size_match else 0
                    if size > 1073741824:
                        vm_disk_path = temp_path
                        break
                    if not vm_disk_path:
                        vm_disk_path = temp_path

            if not vm_disk_path:
                errors.append({"vm": vm_name, "error": "Could not retrieve vmdisk_nfs_path"})
                continue

            qemu_source = f"nfs://{CLUSTER_IP}{vm_disk_path}"
            log_dir = f"{LOCAL_NFS_MOUNT}/logs"
            os.makedirs(log_dir, exist_ok=True)
            
            dest_file = f"{LOCAL_NFS_MOUNT}/{image_name}.qcow2"
            log_file = f"{log_dir}/{image_name}.log"

            # Start conversion in background
            cmd = f"nohup qemu-img convert -p -c -O qcow2 \"{qemu_source}\" \"{dest_file}\" > \"{log_file}\" 2>&1 &"
            subprocess.Popen(cmd, shell=True, start_new_session=True)
            
            started_tasks.append({
                "vm": vm_name,
                "image_name": image_name
            })
        except Exception as e:
            errors.append({"vm": vm_name, "error": str(e)})

    return jsonify({
        "message": f"Started {len(started_tasks)} conversions",
        "started": started_tasks,
        "errors": errors
    })

@app.route('/api/rename', methods=['POST'])
def rename_image():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    old_name = request.json.get('old_name')
    new_name = request.json.get('new_name')
    
    if not old_name or not new_name:
        return jsonify({"error": "Missing parameters"}), 400
        
    # Sanitize new name
    new_name = re.sub(r'[^a-zA-Z0-9\-_]', '', new_name.strip())
    if not new_name:
        return jsonify({"error": "Invalid new name"}), 400

    old_image = os.path.join(LOCAL_NFS_MOUNT, f"{old_name}.qcow2")
    new_image = os.path.join(LOCAL_NFS_MOUNT, f"{new_name}.qcow2")
    old_log = os.path.join(LOCAL_NFS_MOUNT, "logs", f"{old_name}.log")
    new_log = os.path.join(LOCAL_NFS_MOUNT, "logs", f"{new_name}.log")

    try:
        if os.path.exists(old_image):
            os.rename(old_image, new_image)
        if os.path.exists(old_log):
            os.rename(old_log, new_log)
        return jsonify({"message": "Renamed successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/delete', methods=['POST'])
def delete_image():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    name = request.json.get('name')
    if not name:
        return jsonify({"error": "Missing image name"}), 400
        
    image_path = os.path.join(LOCAL_NFS_MOUNT, f"{name}.qcow2")
    log_path = os.path.join(LOCAL_NFS_MOUNT, "logs", f"{name}.log")
    
    try:
        # Check if process is running
        ps_check = subprocess.run(["pgrep", "-f", fr"qemu-img.*/{name}\.qcow2$"], capture_output=True)
        if ps_check.returncode == 0:
            # Kill the process if running
            subprocess.run(["pkill", "-f", fr"qemu-img.*/{name}\.qcow2$"])
            
        # Delete files
        if os.path.exists(image_path):
            os.remove(image_path)
        if os.path.exists(log_path):
            os.remove(log_path)
            
        return jsonify({"message": "Deleted successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/cancel', methods=['POST'])
def cancel_export():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    name = request.json.get('name')
    if not name:
        return jsonify({"error": "Missing image name"}), 400
        
    image_path = os.path.join(LOCAL_NFS_MOUNT, f"{name}.qcow2")
    
    try:
        # Check if process is running
        ps_check = subprocess.run(["pgrep", "-f", fr"qemu-img.*/{name}\.qcow2$"], capture_output=True)
        if ps_check.returncode == 0:
            # Kill the process if running
            subprocess.run(["pkill", "-f", fr"qemu-img.*/{name}\.qcow2$"])
            
            # Delete the partial image file
            if os.path.exists(image_path):
                os.remove(image_path)
            
            # Append "CANCELLED" to log
            log_path = os.path.join(LOCAL_NFS_MOUNT, "logs", f"{name}.log")
            if os.path.exists(log_path):
                with open(log_path, 'a') as f:
                    f.write("\nEXPORT CANCELLED BY USER\n")
            
            return jsonify({"message": "Export cancelled successfully"})
        else:
            return jsonify({"error": "Export is not running or already finished"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/tasks')
def get_tasks():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    # List conversion processes and their status
    # We can check for active qemu-img processes and log files
    tasks = []
    log_dir = f"{LOCAL_NFS_MOUNT}/logs"
    if os.path.exists(log_dir):
        for f in os.listdir(log_dir):
            if f.endswith('.log'):
                name = f.replace('.log', '')
                log_path = os.path.join(log_dir, f)
                image_path = os.path.join(LOCAL_NFS_MOUNT, f"{name}.qcow2")
                
                # Check if process is still running
                ps_check = subprocess.run(["pgrep", "-f", fr"qemu-img.*/{name}\.qcow2$"], capture_output=True)
                running = ps_check.returncode == 0
                image_exists = os.path.exists(image_path)
                
                # Get creation time from log file
                created_at = datetime.fromtimestamp(os.path.getmtime(log_path)).strftime('%Y-%m-%d %H:%M:%S')
                
                # Skip if image is deleted AND not running
                if not running and not image_exists:
                    continue
                
                # Get last line of log for progress
                try:
                    # Read only the last few lines to avoid loading huge files into memory
                    with open(log_path, 'rb') as log_file:
                        try:
                            log_file.seek(-2048, os.SEEK_END)
                        except IOError:
                            pass # File smaller than 2KB
                        content = log_file.read().decode('utf-8', errors='ignore').splitlines()
                        
                        last_progress = ""
                        for line in reversed(content):
                            line = line.strip()
                            if "EXPORT CANCELLED BY USER" in line:
                                last_progress = "CANCELLED"
                                break
                            if '(' in line and '/100%)' in line:
                                # Extract percentage like 85.01%
                                match = re.search(r'(\d+(?:\.\d+)?)/100%', line)
                                if match:
                                    last_progress = f"{match.group(1)}%"
                                    break
                        last_line = last_progress if last_progress else ""
                except Exception as e:
                    print(f"Error reading log {log_path}: {e}")
                    last_line = ""
                
                tasks.append({
                    "name": name,
                    "running": running,
                    "status": last_line,
                    "created_at": created_at,
                    "log": log_path
                })
    
    return jsonify({"tasks": tasks})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
