# Virtual Machine (VM) Manager (DevOps Final Thesis Project)

## Project Overview 
This project implements a **Virtual Machine Manager** for the Code.Hedgehog platform, allowing students to work on Linux-based virtual machines without needing a powerful local PC or manual VM configuration. The system provides a REST API for creating, managing, and deleting VMs on demand, and includes a **hot VM pool** to reduce provisioning delays.

### Key features:

* Create, start, stop, delete, and list VMs via REST API.
* Hot VM pool for instant VM availability.
* Automatic VM configuration using **Ansible**.
* Incremental backup support via a snapshot system.
* Logging of all VM operations.

---

## Technology Stack

| Component                  | Technology                                      |
| -------------------------- | ----------------------------------------------- |
| Backend API                | Python 3.12, FastAPI                            |
| Virtualization             | KVM/QEMU, libvirt                               |
| VM Image Management        | QCOW2 images                                    |
| Automation & Configuration | Ansible                                         |
| Logging                    | Python logging module                           |
| API Documentation          | Swagger (OpenAPI)                               |
| Environment Management     | Virtualenv                                      |
| IDE                        | JetBrains PyCharm / WebStorm                    |
| Deployment                 | Docker Compose (optional for future deployment) |

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

---

## Running the Project

1. **Start the FastAPI server**

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

* The API will be available at: `http://localhost:8000`
* Swagger UI for API testing: `http://localhost:8000/docs`

2. **VM Management Endpoints**

| Endpoint             | Method | Description                       |
| -------------------- | ------ | --------------------------------- |
| `/vms/create`        | POST   | Create a VM by name               |
| `/vms/start/{name}`  | POST   | Start an existing VM              |
| `/vms/stop/{name}`   | POST   | Stop a VM and create snapshot     |
| `/vms/delete/{name}` | DELETE | Delete VM and remove disk         |
| `/vms/list`          | GET    | List all VMs with state           |
| `/pool/status`       | GET    | Get status of hot VM pool         |
| `/pool/allocate`     | POST   | Get an available hot VM from pool |

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

---

## Future Improvements

* Integration with Docker Compose for isolated environments.
* Add more sophisticated monitoring (CPU, memory usage).
* CI/CD pipelines for automatic VM deployment.
* Support for multiple hypervisors and cloud providers (e.g., OpenStack, Yandex Cloud).

---

## License

MIT License

---