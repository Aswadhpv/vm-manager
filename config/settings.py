import os
from pathlib import Path

# -----------------------------
# Base paths
# -----------------------------
BASE_DIR = Path(__file__).resolve().parent.parent  # project root: vm-manager/

# -----------------------------
# VM image storage inside the project
# -----------------------------
VM_IMAGES_ROOT = BASE_DIR / "vm-images"
VM_IMAGES_ROOT.mkdir(parents=True, exist_ok=True)

# base image folder
BASE_IMAGE_DIR = VM_IMAGES_ROOT / "base"
BASE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
BASE_IMAGE_PATH = BASE_IMAGE_DIR / "base.qcow2"

# per-VM disks (students + pool)
VM_STORAGE_PATH = VM_IMAGES_ROOT / "instances"
VM_STORAGE_PATH.mkdir(parents=True, exist_ok=True)

# Backup directory (incremental snapshots)
BACKUP_DIR = VM_IMAGES_ROOT / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------------
# Logging
# -----------------------------
LOG_DIR = BASE_DIR / "log"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "vm-manager.log"

# SSH session recordings (asciinema-like .cast files)
SSH_LOG_DIR = LOG_DIR / "ssh-sessions"
SSH_LOG_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------------
# VM defaults
# -----------------------------
DEFAULT_MEMORY_MB = int(os.getenv("VM_DEFAULT_MEMORY_MB", "1024"))
DEFAULT_VCPU = int(os.getenv("VM_DEFAULT_VCPU", "1"))

# Hot VM pool
HOT_VM_POOL_SIZE = int(os.getenv("HOT_VM_POOL_SIZE", "3"))

# -----------------------------
# Hypervisor / libvirt
# -----------------------------
HYPERVISOR_TYPE = os.getenv("HYPERVISOR_TYPE", "qemu").lower()

# common examples:
#   qemu:///system                  (KVM/QEMU on host)
#   xen:///system                   (Xen)
#   vpx:///system                   (VMware vSphere/ESXi)
#   hyperv:///system                (Hyper-V)
#   qemu+ssh://root@proxmox/system  (Proxmox)
LIBVIRT_URI = os.getenv("LIBVIRT_URI", "qemu:///system")

HYPERVISOR_CONFIG = {
    "qemu": {
        "uri": os.getenv("LIBVIRT_QEMU_URI", LIBVIRT_URI),
    },
    "kvm": {
        "uri": os.getenv("LIBVIRT_KVM_URI", LIBVIRT_URI),
    },
    "hyperv": {
        "uri": os.getenv("LIBVIRT_HYPERV_URI", LIBVIRT_URI),
    },
    "vmware": {
        "uri": os.getenv("LIBVIRT_VMWARE_URI", LIBVIRT_URI),
    },
    "xen": {
        "uri": os.getenv("LIBVIRT_XEN_URI", LIBVIRT_URI),
    },
    "proxmox": {
        "uri": os.getenv("LIBVIRT_PROXMOX_URI", LIBVIRT_URI),
    },
}

# -----------------------------
# Automation / Ansible
# -----------------------------
ANSIBLE_HOSTS_FILE = os.getenv(
    "ANSIBLE_HOSTS_FILE",
    str(BASE_DIR / "ansible" / "hosts.ini"),
)

ANSIBLE_PLAYBOOK = os.getenv(
    "ANSIBLE_PLAYBOOK",
    str(BASE_DIR / "ansible" / "playbooks" / "configure_vm.yml"),
)

# -----------------------------
# SSH / terminal access
# -----------------------------
VM_SSH_HOST_TEMPLATE = os.getenv("VM_SSH_HOST_TEMPLATE", "{name}")
VM_SSH_PORT = int(os.getenv("VM_SSH_PORT", "22"))
VM_SSH_USERNAME = os.getenv("VM_SSH_USERNAME", "student")
VM_SSH_KNOWN_HOSTS = os.getenv("VM_SSH_KNOWN_HOSTS", None)

VM_SSH_PRIVATE_KEY = os.getenv(
    "VM_SSH_PRIVATE_KEY",
    str(Path.home() / ".ssh" / "id_rsa"),
)

# -----------------------------
# Metrics / monitoring
# -----------------------------
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "true").lower() == "true"
METRICS_REFRESH_INTERVAL = int(os.getenv("METRICS_REFRESH_INTERVAL", "5"))

# -----------------------------
# Misc
# -----------------------------
DEBUG = os.getenv("DEBUG", "true").lower() == "true"
