import os
import shutil
import subprocess
import time
import uuid
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import libvirt
from fastapi import HTTPException

from config.settings import (
    BASE_IMAGE_DIR,
    VM_STORAGE_PATH,
    CLOUD_INIT_DIR,
    DEFAULT_MEMORY_MB,
    DEFAULT_VCPU,
    ANSIBLE_HOSTS_FILE,
    PLAYBOOKS_DIR,
    LIBVIRT_URI,
    HYPERVISOR_TYPE,
    VM_SSH_HOST_TEMPLATE,
    VM_SSH_PORT,
    VM_SSH_USERNAME,
    VM_SSH_PRIVATE_KEY,
)
from core.logger import log_event
from core.backup_manager import BackupManager
from core.ansible_auth import AnsibleAuthManager


def _libvirt_error_handler(ctx, error):
    """
    Custom libvirt error handler to suppress noisy stderr messages like:
    'Domain not found: no domain with matching name ...'
    """
    pass


class VMController:
    """
    Core VM lifecycle operations, abstracted over libvirt.

    By switching LIBVIRT_URI (and HYPERVISOR_TYPE) in config/settings.py,
    this controller can talk to:

        * QEMU / KVM
        * Hyper-V (via libvirt hyperv driver)
        * VMware (via vpx driver)
        * Xen
        * Proxmox (KVM, exposed via libvirt)
    """

    def __init__(self) -> None:
        # Register global libvirt error handler to avoid noisy stderr prints
        libvirt.registerErrorHandler(_libvirt_error_handler, None)
        try:
            uri = LIBVIRT_URI
            self.conn = libvirt.open(uri)
            if self.conn is None:
                raise HTTPException(status_code=500, detail=f"Failed to connect: {uri}")
            log_event(f"[vm] Connected via libvirt URI={uri}, type={HYPERVISOR_TYPE}")
        except libvirt.libvirtError as e:
            raise HTTPException(status_code=500, detail=f"libvirt connection error: {e}") from e

        self.backup_manager = BackupManager()

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    def vm_exists(self, name: str) -> bool:
        try:
            self.conn.lookupByName(name)
            return True
        except libvirt.libvirtError:
            return False

    def _clone_base_image(self, name: str, base_image_name: str) -> str:
        source_image_path = BASE_IMAGE_DIR / base_image_name
        if not source_image_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Base image '{base_image_name}' not found at {source_image_path}",
            )

        vm_image_path = VM_STORAGE_PATH / f"{name}.qcow2"
        if vm_image_path.exists():
            raise HTTPException(
                status_code=400,
                detail=f"VM image already exists for {name} at {vm_image_path}",
            )

        try:
            log_event(f"[vm] Copying base image {base_image_name} to {vm_image_path}")
            shutil.copy2(source_image_path, vm_image_path)
        except Exception as e:
            log_event(f"[vm] Failed to copy base image for VM {name}: {e}")
            raise HTTPException(status_code=500, detail=f"Image copy failed: {e}")

        return str(vm_image_path)

    def _generate_cloud_init_iso(self, name: str) -> str:
        """Generates a cloud-init CIDATA ISO using cloud-localds."""
        iso_path = CLOUD_INIT_DIR / f"{name}-cidata.iso"

        with tempfile.TemporaryDirectory() as tmpdir:
            meta_data_path = Path(tmpdir) / "meta-data"
            user_data_path = Path(tmpdir) / "user-data"

            meta_data_path.write_text(f"instance-id: {name}\nlocal-hostname: {name}\n")

            # Explicit user-data to bypass strict OS security defaults and allow SSH passwords
            user_data = f"""#cloud-config
hostname: {name}
manage_etc_hosts: true

# This forces the SSH service to accept passwords
ssh_pwauth: true

users:
  - name: {VM_SSH_USERNAME}
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: users, admin
    home: /home/{VM_SSH_USERNAME}
    shell: /bin/bash
    lock_passwd: false

chpasswd:
  list: |
    {VM_SSH_USERNAME}:student
  expire: False
"""
            user_data_path.write_text(user_data)

            try:
                subprocess.run(
                    ["cloud-localds", str(iso_path), str(user_data_path), str(meta_data_path)],
                    check=True, capture_output=True
                )
                log_event(f"[cloud-init] Generated CIDATA ISO at {iso_path}")
            except subprocess.CalledProcessError as e:
                log_event(f"[cloud-init] Error generating ISO: {e.stderr}")
                raise HTTPException(status_code=500, detail="Failed to create cloud-init ISO")

        return str(iso_path)

    @staticmethod
    def _generate_domain_xml(
            name: str, vm_uuid: str, vm_image: str, cloud_init_iso: str, memory_mb: int, vcpus: int
    ) -> str:
        """
        Minimal domain XML definition suitable for QEMU/KVM style hypervisors.
        """

        return f"""
        <domain type='kvm'>
          <name>{name}</name>
          <uuid>{vm_uuid}</uuid>
          <memory unit='MiB'>{memory_mb}</memory>
          <vcpu>{vcpus}</vcpu>
          <os>
            <type arch='x86_64'>hvm</type>
            <boot dev='hd'/>
          </os>
          <devices>
            <disk type='file' device='disk'>
              <driver name='qemu' type='qcow2'/>
              <source file='{vm_image}'/>
              <target dev='vda' bus='virtio'/>
            </disk>
            <disk type='file' device='cdrom'>
              <driver name='qemu' type='raw'/>
              <source file='{cloud_init_iso}'/>
              <target dev='sda' bus='sata'/>
              <readonly/>
            </disk>
            <interface type='network'>
              <source network='default'/>
              <model type='virtio'/>
            </interface>
            <graphics type='vnc' port='-1' autoport='yes'/>
            <console type='pty'/>
          </devices>
        </domain>
        """

    def _get_domain(self, name: str):
        try:
            return self.conn.lookupByName(name)
        except libvirt.libvirtError:
            raise HTTPException(status_code=404, detail=f"VM '{name}' not found")

    def get_vm_ip(self, name: str) -> Optional[str]:
        """Queries Libvirt's DHCP server for the VM's assigned IP."""
        try:
            dom = self._get_domain(name)
            if dom.isActive():
                # We use a try-except block to handle different versions of libvirt-python
                try:
                    # The official constant (Addresses, Src)
                    source = libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE
                except AttributeError:
                    # Fallback to the raw integer value (1) if the constant is missing
                    source = 1

                    # Ask libvirt for network leases (waits for DHCP)
                ifaces = dom.interfaceAddresses(source, 0)
                for (iface, val) in ifaces.items():
                    if val.get('addrs'):
                        for addr in val['addrs']:
                            if addr['type'] == libvirt.VIR_IP_ADDR_TYPE_IPV4:
                                return addr['addr']
        except libvirt.libvirtError:
            pass
        return None

    # ------------------------------------------------------------------
    # Public VM operations
    # ------------------------------------------------------------------

    def create_vm(
            self,
            name: str,
            base_image: str,
            memory_mb: Optional[int] = None,
            vcpus: Optional[int] = None,
            owner: Optional[str] = None,
    ) -> Dict[str, Any]:
        if self.vm_exists(name):
            raise HTTPException(status_code=400, detail=f"VM '{name}' already exists")

        memory_mb = memory_mb or DEFAULT_MEMORY_MB
        vcpus = vcpus or DEFAULT_VCPU

        vm_image = self._clone_base_image(name, base_image)
        cloud_init_iso = self._generate_cloud_init_iso(name)
        vm_uuid = str(uuid.uuid4())

        domain_xml = self._generate_domain_xml(
            name=name,
            vm_uuid=vm_uuid,
            vm_image=vm_image,
            cloud_init_iso=cloud_init_iso,
            memory_mb=memory_mb,
            vcpus=vcpus,
        )

        try:
            dom = self.conn.defineXML(domain_xml)
            if dom is None:
                raise HTTPException(status_code=500, detail="Failed to define libvirt domain")
            dom.create()
            log_event(f"[vm] Created VM '{name}' (owner={owner}, image={base_image})")
            return {
                "name": name,
                "uuid": vm_uuid,
                "image": vm_image,
                "base_image": base_image,
                "memory_mb": memory_mb,
                "vcpus": vcpus,
                "owner": owner,
                "ip": None # Will populate once the VM boots and requests a DHCP lease
            }
        except libvirt.libvirtError as e:
            raise HTTPException(status_code=500, detail=f"libvirt error: {e}") from e

    def start_vm(self, name: str) -> None:
        """
        Start VM.

        - If the VM is already running -> raise 409 with a clear message.
        - If paused -> resume.
        - If shut off / crashed / no state -> start.
        """
        dom = self._get_domain(name)
        try:
            info = dom.info()
            state = info[0]

            # libvirt states:
            # 0: no state, 1: running, 2: blocked, 3: paused, 4: shutting down,
            # 5: shut off, 6: crashed, 7: pmsuspended
            if state == libvirt.VIR_DOMAIN_RUNNING:
                raise HTTPException(status_code=409, detail=f"VM '{name}' is already running")
            if state == libvirt.VIR_DOMAIN_PAUSED:
                dom.resume()
                return
            dom.create()
        except libvirt.libvirtError as e:
            raise HTTPException(status_code=500, detail=f"Failed to start VM: {e}") from e

    def stop_vm(self, name: str) -> None:
        """
        Stop a VM.

        Strategy:
        - If VM is already shut off -> no-op, treat as success.
        - Otherwise:
            1) Best-effort snapshot
            2) Try graceful shutdown (ACPI)
            3) Wait a bit for it to actually stop
            4) If still running, force poweroff with destroy()
        """
        dom = self._get_domain(name)
        # Check current state first
        try:
            info = dom.info()
            state = info[0]
        except libvirt.libvirtError as e:
            raise HTTPException(status_code=500, detail=f"Failed to inspect VM: {e}") from e

        if state == libvirt.VIR_DOMAIN_SHUTOFF:
            # Already stopped -> this is fine, no error
            log_event(f"[vm] stop_vm called for '{name}' but it is already shut off – no-op")
            return

        # Try snapshot only if VM is actually active-ish
        try:
            self.backup_manager.create_snapshot(vm_name=name)
        except Exception as e:
            log_event(f"[vm] Snapshot failed for '{name}': {e}")

        # 1) Ask libvirt for graceful shutdown
        try:
            dom.shutdown()
        except libvirt.libvirtError:
            pass

        # 2) Poll a bit to see if it actually turned off
        timeout_sec = 15
        waited = 0
        while waited < timeout_sec:
            try:
                curr_state = dom.info()[0]
            except libvirt.libvirtError:
                break
            if curr_state == libvirt.VIR_DOMAIN_SHUTOFF:
                return
            time.sleep(1)
            waited += 1

        try:
            dom.destroy()
        except libvirt.libvirtError as e:
            raise HTTPException(status_code=500, detail=f"Failed to force stop VM: {e}") from e

    def delete_vm(self, name: str) -> None:
        dom = self._get_domain(name)
        try:
            if dom.isActive():
                dom.destroy()
        except libvirt.libvirtError:
            pass

        try:
            # 1. Undefine the domain from libvirt
            dom.undefineFlags(libvirt.VIR_DOMAIN_UNDEFINE_MANAGED_SAVE)

            # 2. Smart cleanup: Delete base disk AND any snapshot overlays
            import glob
            disk_pattern = str(VM_STORAGE_PATH / f"{name}*")
            for file_path in glob.glob(disk_pattern):
                try:
                    os.remove(file_path)
                    log_event(f"[vm] Deleted disk/snapshot file: {file_path}")
                except OSError as e:
                    log_event(f"[vm] Failed to delete file {file_path}: {e}")

            # 3. Clean up the cloud-init ISO
            iso_path = str(CLOUD_INIT_DIR / f"{name}-cidata.iso")
            if os.path.exists(iso_path):
                os.remove(iso_path)
                log_event(f"[vm] Deleted cloud-init ISO: {iso_path}")

            log_event(f"[vm] Completely deleted VM '{name}' and all attached storage")
        except libvirt.libvirtError as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete VM '{name}': {e}") from e

    def list_vms(self) -> List[Dict[str, Any]]:
        domains = self.conn.listAllDomains()
        vms = []
        for dom in domains:
            try:
                info = dom.info()
                name = dom.name()
                vms.append({
                    "name": name,
                    "id": dom.ID(),
                    "state": info[0],
                    "max_memory": info[1],
                    "memory": info[2],
                    "vcpus": info[3],
                    "ip": self.get_vm_ip(name)  # Automatically fetches the IP
                })
            except libvirt.libvirtError:
                continue
        return vms

    # ------------------------------------------------------------------
    # VM configuration (Ansible)
    # ------------------------------------------------------------------

    def configure_vm_with_ansible(self, vm_name: str, playbooks: list[str]) -> None:
        """
        Run ansible playbook to configure the VM.

        - Uses in-memory stored sudo/become password if provided via
          AnsibleAuthManager.
        - If no password is provided, it runs as usual, which works on
          hosts with passwordless sudo.
        """
        if not playbooks:
            log_event(f"[ansible] No playbooks specified for {vm_name}. Skipping.")
            return

        env = os.environ.copy()
        become_password = AnsibleAuthManager.get_password()

        for pb_name in playbooks:
            pb_path = PLAYBOOKS_DIR / pb_name
            if not pb_path.exists():
                raise HTTPException(status_code=404, detail=f"Playbook {pb_name} not found")

            cmd = [
                "ansible-playbook",
                "-i", ANSIBLE_HOSTS_FILE,
                str(pb_path),
                "-e", f"target_host={vm_name}",
            ]

            extra = []
            if become_password:
                env["ANSIBLE_BECOME_PASSWORD"] = become_password
                extra.extend(["-e", f"ansible_become_pass={become_password}"])

            full_cmd = cmd + extra
            log_event(f"[ansible] Running playbook {pb_name} on {vm_name}")

            try:
                result = subprocess.run(full_cmd, capture_output=True, text=True, env=env)
            except FileNotFoundError as e:
                raise HTTPException(status_code=500, detail=f"Ansible failed: {e}")

            if result.returncode != 0:
                err = result.stderr.strip() or result.stdout.strip()
                log_event(f"[ansible] FAILED {pb_name} on {vm_name}: {err}")
                raise HTTPException(status_code=500, detail=f"Ansible failed on {pb_name}: {err}")

        log_event(f"[ansible] All playbooks completed successfully for {vm_name}")

    # ------------------------------------------------------------------
    # SSH helper – used by WebSocket tunnel
    # ------------------------------------------------------------------

    def get_vm_ssh_target(self, name: str) -> dict:
        host = VM_SSH_HOST_TEMPLATE.format(name=name)
        return {
            "host": host,
            "port": VM_SSH_PORT,
            "username": VM_SSH_USERNAME,
            "key_path": VM_SSH_PRIVATE_KEY,
        }

    def get_vm_state(self, name: str) -> dict:
        dom = self._get_domain(name)
        info = dom.info()
        return {"name": name, "state": info[0], "memory": info[2], "vcpus": info[3]}