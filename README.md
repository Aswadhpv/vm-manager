# Virtual Machine (VM) Manager (DevOps Final Thesis Project)

## Project Overview 
This project implements a **Virtual Machine Manager** for the Code.Hedgehog platform, allowing students to work on Linux-based virtual machines without needing a powerful local PC or manual VM configuration. The system provides a REST API for creating, managing, and deleting VMs on demand, and includes a **hot VM pool** to reduce provisioning delays. And in this project is capable of managing virtual machines across multiple hypervisors through **libvirt**, supporting VM lifecycle management, VM pooling, SSH-over-WebSocket terminal access, student usage metrics, Ansible configuration, and Prometheus/Grafana monitoring.

### Key features:

* Create, start, stop, delete, and list VMs via REST API.
* Hot VM pool for instant VM availability.
* Automatic VM configuration using **Ansible**.
* Incremental backup support via a snapshot system.
* Logging of all VM operations.

## ✅ 1. Multi-Hypervisor Support (Hybrid)
The system supports any hypervisor accessible via **libvirt**, including:
- **QEMU/KVM** (tested)
- **Microsoft Hyper‑V**
- **VMware (vSphere, Fusion, Workstation)**
- **Xen**
- **Proxmox VE**
- **Direct KVM**

Hypervisor selection is configured via:
```
config/settings.py → LIBVIRT_URI
```

---

## ✅ 2. VM Lifecycle Management
Implemented full VM control:
- Create VM
- Start VM  
  - Returns error **409** if VM is already running  
- Stop VM  
  - Graceful shutdown → forced shutdown if needed  
  - If the VM is already stopped → 200 OK (no-op)
- Delete VM
- List VMs (libvirt-backed)
- VM state WebSocket stream:  
  `/ws/vm/{name}/status`

---
## ✅ 3. VM Image Pool (Hot Pool for Fast Provisioning)
To reduce wait time (like AWS/GCP do), the system maintains a pool of pre‑warmed VMs:

- Automatically created on backend startup  
- Ensures each pool VM is **shut off and ready**
- Self‑heals if pool VMs are manually removed
- Endpoint:
  - `/pool/status`
  - `/pool/allocate`

This aligns with the thesis argument:

> Cloud creation = slow (~1 minute),  
> hot pool = instant VM delivery.

---

## ✅ 4. SSH Tunnel via WebSocket (xterm.js Compatible)
Implemented full SSH forwarding:
- Browser connects via WebSocket:
  ```
  /ws/vm/{name}/terminal
  ```
- Backend establishes SSH connection to VM
- Input/output proxy to xterm.js
- Terminal session logged in **asciinema v2 format**:
  ```
  logs/ssh/{session_id}.cast
  ```

---

## ✅ 5. Asciinema-Style Logging
Each SSH terminal session is fully logged in asciinema-compatible JSON lines:
- Timestamp
- Input/output marker
- Raw terminal data

Useful for:
- Student behavior analysis
- Playback of sessions
- Debugging labs

---

## ✅ 6. Prometheus + Grafana Monitoring
The system exposes:
- HTTP request metrics
- VM activity metrics
- SSH session metrics
- Resource usage collectors

Endpoint:
```
/metrics
```

Prometheus → Grafana → Dashboard ready.

---

## ✅ 7. Ansible Integration with Sudo Password API
Some hosts need `sudo` during provisioning; others have passwordless sudo.

Implemented:
```
POST /ansible/auth   → stores sudo password in RAM
POST /ansible/clear  → clears it
```

Then, during VM create:
- If password present → passed to Ansible as `ansible_become_pass`
- If not → Ansible runs normally

Ansible Playbook:
```
ansible/playbooks/configure_vm.yml
```

Includes:
- Package install
- UFW configuration
- Lab file deployment

---

## Technology Stack

| Component                  | Technology                                            |
| -------------------------- |-------------------------------------------------------|
| Backend API                | Python 3.12, FastAPI                                  |
| Virtualization             | KVM/QEMU, libvirt, Microsoft Hyper V, Proxmox VE, Xen |
| VM Image Management        | QCOW2 images                                          |
| Automation & Configuration | Ansible                                               |
| Logging                    | Python logging module                                 |
| API Documentation          | Swagger (OpenAPI)                                     |
| Environment Management     | Virtualenv                                            |
| IDE                        | JetBrains PyCharm / WebStorm                          |
| Deployment                 | Docker Compose (optional for future deployment)       |

---

## Prerequisites

* Linux OS (Ubuntu/Debian recommended for KVM support)
* Python 3.12+
* libvirt, qemu, qemu-img installed
* Ansible installed
* Root privileges for managing VMs

Install essential packages:

```bash
sudo apt update
sudo apt install -y qemu-kvm libvirt-daemon-system libvirt-clients virtinst python3-venv python3-pip ansible
sudo systemctl enable --now libvirtd
```

---

## Project Setup

1. **Clone the repository**

```bash
git clone <your-repo-url>
cd vm-manager
```

2. **Create a Python virtual environment and activate it**

```bash
python3 -m venv venv
source venv/bin/activate
```

3. **Install dependencies**

```bash
pip install -r requirements.txt
```

4. **Configure project settings**
   Edit `config/settings.py`:

```python
BASE_IMAGE_PATH = "/home/<user>/vm-manager/vm-images/base.qcow2"
VM_STORAGE_PATH = "/home/<user>/vm-manager/vm-images"
DEFAULT_MEMORY_MB = 1024
DEFAULT_VCPU = 1
HOT_VM_POOL_SIZE = 3
ANSIBLE_HOSTS_FILE = "/home/<user>/vm-manager/ansible/hosts.ini"
ANSIBLE_PLAYBOOK = "/home/<user>/vm-manager/ansible/configure_vm.yml"
```

* Make sure your **base.qcow2** image exists in `vm-images/`
* If not then you can download from `wget https://cloud-images.ubuntu.com/focal/current/focal-server-cloudimg-amd64.img -O base.qcow2`
* if its in different format you can covert to QCOW2 if needed `qemu-img convert -O qcow2 focal-server-cloudimg-amd64.img base.qcow2`
* Configure Ansible hosts and playbook accordingly

5. **If your host requires sudo for Ansible**
```
POST /ansible/auth
{
  "password": "your_sudo_password"
}
```

6. **Create a VM**
```
POST /vms/create
```

7. **Access terminal via**
```
/ws/vm/{name}/terminal
```

---

## Running the Project

1. **Start the FastAPI server**

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

* The API will be available at: `http://localhost:8000`
* Swagger UI for API testing: `http://localhost:8000/docs`

2. **VM Management Endpoints**

| Endpoint             | Method | Description                                         |
|----------------------|--------|-----------------------------------------------------|
| `/vms/create`        | POST   | Create a VM by name                                 |
| `/vms/start/{name}`  | POST   | Start an existing VM                                |
| `/vms/stop/{name}`   | POST   | Stop a VM and create snapshot                       |
| `/vms/delete/{name}` | DELETE | Delete VM and remove disk                           |
| `/vms/list`          | GET    | List all VMs with state                             |
| `/pool/status`       | GET    | Get status of hot VM pool                           |
| `/pool/allocate`     | POST   | Get an available hot VM from pool                   |
| `/metrics`           | GET    | Get Monitoring metrics                              |
| `/ansible/auth`      | POST   | Post the auth password or sudo password if user has |
| `/ansible/clear`     | POST   | Recover the auth password if user forget            |

---

## Running Ansible Configuration

Once a VM is created, it will be automatically configured via Ansible:

```bash
ansible-playbook -i ansible/hosts.ini ansible/configure_vm.yml -e target_host=<vm_name>
```

This can be customized per project requirements (install software, configure network, etc.).

---

## Notes

* **Hot VM Pool**:

  * Maintains a fixed number of pre-created, shut-off VMs.
  * Reduces provisioning time for new students.

* **Snapshots & Backups**:

  * VM snapshots are automatically created when stopping a VM.
  * Incremental backups save only user-made changes.

* **Error Handling**:

  * All API responses return HTTP status codes properly.
  * Internal errors are logged via `core.logger`.

* **VM creation takes 45–90 seconds due to**:
  * Base image cloning
  * Libvirt boot time
  * Ansible provisioning  
  This matches cloud VM behavior.

* **Hot pool provides **near‑instant VM allocation****.

* **SSH-over-WebSocket design allows secure browser-based terminals (xterm.js)**.

* **Asciinema logging enables reproducibility and analytics**.

* **System works on **any hypervisor** supported by libvirt**:
  * This demonstrates hybrid architecture.

---

## Future Improvements

* Integration with Docker Compose for isolated environments.
* Add more sophisticated monitoring (CPU, memory usage).
* CI/CD pipelines for automatic VM deployment.
* Support for multiple hypervisors and cloud providers (e.g., OpenStack, Yandex Cloud).

---

## 🎓 Conclusion

This system demonstrates:
- Hybrid multi-hypervisor orchestration
- Automated provisioning with Ansible
- Real-time terminal environment for students
- Metrics-backed observability
- VM hot-pool optimization
- Secure SSH tunneling via WebSocket
- Full session replay logging

Perfect for academic labs, cloud education, or scalable VM teaching platforms.

---

## License

MIT License

---