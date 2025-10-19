import os

# -----------------------------
# Project Directories
# -----------------------------
BASE_DIR = os.path.dirname(os.path.dirname(__file__))  # vm-manager/

# Path to store VM images
VM_STORAGE_PATH = os.path.join(BASE_DIR, "vm-images")

# Base image (for cloning new VMs)
BASE_IMAGE_PATH = os.path.join(VM_STORAGE_PATH, "base.qcow2")

# Backup directory (incremental snapshots)
BACKUP_DIR = os.path.join(VM_STORAGE_PATH, "backups")

# -----------------------------
# Logging Configuration
# -----------------------------
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "vm-manager.log")

# -----------------------------
# VM Defaults
# -----------------------------
DEFAULT_MEMORY_MB = 1024      # Default VM RAM in MB
DEFAULT_VCPU = 1              # Default vCPU count
DEFAULT_DISK_GB = 10          # Default disk size if not using cloning
DEFAULT_NETWORK = "default"   # libvirt network

# -----------------------------
# Hypervisor / libvirt URI
# -----------------------------
# Local KVM
LIBVIRT_URI = "qemu:///system"

# -----------------------------
# VM Pool Config
# -----------------------------
HOT_VM_POOL_SIZE = 3          # Number of pre-created "hot" VMs

# -----------------------------
# Automation / Ansible
# -----------------------------
ANSIBLE_HOSTS_FILE = os.path.expanduser("~/vm-manager/ansible/hosts.ini")
ANSIBLE_PLAYBOOK = os.path.expanduser("~/vm-manager/ansible/playbooks/configure_vm.yml")

# -----------------------------
# Misc
# -----------------------------
DEBUG = True
