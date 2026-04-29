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

DAPX-Unified is meant to run **inside a Linux guest** (LXC or VM), not on the Proxmox hypervisor itself. The automated wizard creates that guest for you; if you already have a Debian CT/VM, install from Git as below.

### Option 1: Automated LXC on Proxmox host (recommended)

Run this **on the Proxmox VE shell** (SSH or console). It creates a container, clones the repo into `/opt/dapx-unified`, and runs the installer—same result as Option 2, unattended.

```bash
bash <(curl -s https://raw.githubusercontent.com/grandir66/DA-PXREPL/main/deploy_lxc.sh)
```

Follow the wizard (container ID, hostname, password, network, resources). When it finishes, open `http://<container-ip>:8420`.

### Option 2: Install from Git inside an existing LXC / VM (manual)

Use this when you manage the container yourself (template already installed, networking done). Run **as root inside the guest** (e.g. after `pct enter <CTID>` or SSH):

```bash
apt-get update && apt-get install -y git curl
git clone https://github.com/grandir66/DA-PXREPL.git /opt/dapx-unified
cd /opt/dapx-unified
chmod +x install.sh
NONINTERACTIVE=true ./install.sh --local
```

- **`NONINTERACTIVE=true`**: no prompts (same as the automated deploy script).
- **`--local`**: install from the cloned tree under `/opt/dapx-unified` (no separate download step).

**LXC note:** Tools like `pveversion` are usually **not** installed inside a CT, so the installer may log *“Proxmox VE non rilevato”*. That is normal; DAPX-Unified still manages Proxmox nodes over the API and SSH from the container.

**Interactive install** (prompts for mode and confirmation): `./install.sh` with no arguments, from `/opt/dapx-unified` after cloning.

Other installer flags: `./install.sh --help` (e.g. `--github` for a fresh fetch without manual clone).

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
