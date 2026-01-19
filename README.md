# DAPX-Unified Replication Manager

**DAPX-Unified** is a centralized web-based management system for backup and replication in Proxmox VE infrastructures. It unifies specific technologies like ZFS (Sanoid/Syncoid), BTRFS, and Proxmox Backup Server (PBS) into a single, easy-to-use interface.

## 🚀 Key Features

*   **Unified Dashboard**: Monitor the status of all your nodes, storage, and replication jobs in real-time.
*   **Proxmox Integration**: Native authentication using Proxmox VE credentials (`root@pam`, etc.).
*   **Multi-Protocol Support**:
    *   **ZFS**: Advanced management of snapshots and replication via `Sanoid` and `Syncoid`.
    *   **PBS**: Integration with Proxmox Backup Server for backup and recovery management.
    *   **BTRFS**: Support for `btrfs send/receive` replication (experimental).
*   **Job Management**:
    *   **Sync Jobs**: Schedule and monitor replication between nodes.
    *   **Backup & Recovery**: Manage PBS backup jobs and perform restores directly from the UI.
    *   **Migration**: Tools to assist in moving workloads between nodes.
*   **Host Protection**: Automated backup of host configurations (`/etc`, network, etc.).
*   **Cluster Monitor**: 
    *   Unified view of Node Health and Resources.
    *   **Network Metrics**: Real-time traffic visualization (RX/TX) for Nodes and VMs.
*   **Security & Logs**: Centralized logging, SSH key management for inter-node communication.

## 📋 Prerequisites

*   **OS**: Debian 11/12 or Proxmox VE 7/8.
*   **Filesystem**: ZFS (recommended for full feature set).
*   **Dependencies**: Python 3.9+, SSH.

## 🛠️ Installation

### Option 1: Automated Deployment on Proxmox (Recommended)

This method automatically creates a dedicated LXC container on your Proxmox host and installs DAPX-Unified inside it. This keeps your Proxmox host clean.

1.  **Access your Proxmox VE Shell** (Web UI Console or SSH).
2.  **Run the deployment script**:

```bash
bash <(curl -s https://raw.githubusercontent.com/grandir66/DA-PXREPL/main/deploy_lxc.sh)
```

3.  **Follow the wizard**:
    *   **Container ID**: Choose a free ID (e.g., 100).
    *   **Hostname**: Give it a name (e.g., `dapx-unified`).
    *   **Password**: Set a root password for the container.
    *   **Network**: Define Bridge, VLAN (optional), and IP (DHCP or Static).
    *   **Resources**: Allocate CPU, RAM, and Disk.

The script will create the container, download the application, and set everything up. Once finished, it will show you the URL to access the dashboard.

### Option 2: Manual Installation (Advanced)
If you prefer to install it manually (on a bare metal Debian server or an existing VM/CT):
Execute the installation script as root. This will set up the Python environment, install system dependencies (like `sanoid`, `lz4`, `pv`), configure the systemd service, and build the frontend.

```bash
sudo ./install.sh
```

Follow the on-screen instructions. The script will:
*   Check for required dependencies (Python, ZFS, etc.).
*   Create a virtual environment and install Python requirements.
*   Install and configure `Sanoid` if missing.
*   Set up a systemd service (`dapx-unified`).
*   Generate SSH keys for inter-node communication.

### 3. Access the Interface
Once installed, the web interface is available at:

```
http://<YOUR-SERVER-IP>:8420
```

*   **Port**: 8420 (default)
*   **Credentials**: Use your Proxmox VE credentials (e.g., `root` / `password`).

## 📂 Project Structure

*   **/backend**: FastAPI (Python) application handling core logic, API, and system interactions.
*   **/frontend**: Vue 3 + TypeScript application providing the modern web interface.
*   **install.sh**: Automated deployment script.
*   **update.sh**: Utility to pull changes and update the installation.

## 🔄 Updates

To update an existing installation to the latest version:

```bash
cd /opt/dapx-unified
./update.sh
```

## ⚠️ Important Notes

*   **SSH Keys**: The installer generates an SSH key for the `root` user (or the service user). You must install this public key (`/root/.ssh/id_rsa.pub`) on all target Proxmox nodes you wish to manage.
*   **ZFS Datasets**: Ensure your target ZFS datasets are created and accessible before configuring replication jobs.

---
*Developed for internal use and advanced Proxmox administration.*
