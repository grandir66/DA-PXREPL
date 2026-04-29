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

*   **Typical deploy**: a **Proxmox VE** host where you can create an LXC (the installer wizard runs here once).
*   **Guest OS**: Debian 11/12 inside the container (created by `deploy_lxc.sh` or your template).
*   **Filesystem**: ZFS on managed nodes (recommended for full feature set).
*   **Dependencies**: Python 3.9+, SSH.

## 🛠️ Installation

**Standard setup:** run DAPX-Unified **inside a dedicated LXC** created on your Proxmox host. Use the deployment wizard **on the hypervisor**—it **generates the container** (template, disk, network), clones this repo, and runs the installer inside it. Do not install on the Proxmox host itself.

### Recommended: generate LXC and install (Proxmox shell)

On the **Proxmox VE node** (SSH or console):

```bash
bash <(curl -s https://raw.githubusercontent.com/grandir66/DA-PXREPL/main/deploy_lxc.sh)
```

The wizard asks for CT ID, hostname, root password, bridge/VLAN/IP, CPU/RAM/disk. It creates and starts the container, then installs from Git into `/opt/dapx-unified`. When done, open `http://<container-ip>:8420`.

### Advanced: Git install in an existing Debian CT/VM

Only if you **already** have a suitable guest and prefer not to use the wizard above. As **root inside that CT/VM**:

```bash
apt-get update && apt-get install -y git curl
git clone https://github.com/grandir66/DA-PXREPL.git /opt/dapx-unified
cd /opt/dapx-unified
chmod +x install.sh
NONINTERACTIVE=true ./install.sh --local
```

- **`NONINTERACTIVE=true`**: no prompts (same behaviour as the generated-container deploy).
- **`--local`**: install from the cloned tree.

**Inside LXC:** `pveversion` is usually absent, so you may see *“Proxmox VE non rilevato”*—that is normal for a CT.

Interactive install after clone: `./install.sh` with no arguments. More flags: `./install.sh --help`.

### Access the Interface
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
