import os
import shutil
import subprocess
import time
import uuid
from typing import Any, Dict, List, Optional

import libvirt
from fastapi import HTTPException

from config.settings import (
    BASE_IMAGE_PATH,
    VM_STORAGE_PATH,
    DEFAULT_MEMORY_MB,
    DEFAULT_VCPU,
    ANSIBLE_HOSTS_FILE,
    ANSIBLE_PLAYBOOK,
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
    # You could add selective logging here if you want.
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
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to connect to hypervisor via libvirt URI: {uri}",
                )
            log_event(f"[vm] Connected to hypervisor via libvirt URI={uri}, type={HYPERVISOR_TYPE}")
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

    def _clone_base_image(self, name: str) -> str:
        """
        Create a QCOW2 image for a VM by copying base.qcow2 inside the
        project `vm-images/` directory.
        """
        if not BASE_IMAGE_PATH.exists():
            raise HTTPException(
                status_code=500,
                detail=f"Base image not found at {BASE_IMAGE_PATH}",
            )

        vm_image_path = VM_STORAGE_PATH / f"{name}.qcow2"
        if vm_image_path.exists():
            raise HTTPException(
                status_code=400,
                detail=f"VM image already exists for {name} at {vm_image_path}",
            )

        try:
            log_event(f"[vm] Copying base image from {BASE_IMAGE_PATH} to {vm_image_path}")
            shutil.copy2(BASE_IMAGE_PATH, vm_image_path)
        except Exception as e:  # noqa: BLE001
            log_event(f"[vm] Failed to copy base image for VM {name}: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to copy base image for VM '{name}': {e}",
            )

        return str(vm_image_path)

    @staticmethod
    def _generate_domain_xml(
        name: str,
        vm_uuid: str,
        vm_image: str,
        memory_mb: int,
        vcpus: int,
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

    # ------------------------------------------------------------------
    # Public VM operations
    # ------------------------------------------------------------------
    def create_vm(
        self,
        name: str,
        memory_mb: Optional[int] = None,
        vcpus: Optional[int] = None,
        owner: Optional[str] = None,
    ) -> Dict[str, Any]:
        if self.vm_exists(name):
            raise HTTPException(status_code=400, detail=f"VM '{name}' already exists")

        memory_mb = memory_mb or DEFAULT_MEMORY_MB
        vcpus = vcpus or DEFAULT_VCPU

        vm_image = self._clone_base_image(name)
        vm_uuid = str(uuid.uuid4())
        domain_xml = self._generate_domain_xml(
            name=name,
            vm_uuid=vm_uuid,
            vm_image=vm_image,
            memory_mb=memory_mb,
            vcpus=vcpus,
        )

        try:
            dom = self.conn.defineXML(domain_xml)
            if dom is None:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to define libvirt domain from XML",
                )
            dom.create()
            log_event(
                f"[vm] Created VM '{name}' (owner={owner}, memory={memory_mb}MiB, "
                f"vcpus={vcpus}, hypervisor={HYPERVISOR_TYPE})"
            )
            return {
                "name": name,
                "uuid": vm_uuid,
                "image": vm_image,
                "memory_mb": memory_mb,
                "vcpus": vcpus,
                "owner": owner,
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
                raise HTTPException(
                    status_code=409,
                    detail=f"VM '{name}' is already running",
                )

            if state == libvirt.VIR_DOMAIN_PAUSED:
                log_event(f"[vm] Resuming paused VM '{name}'")
                dom.resume()
                return

            log_event(f"[vm] Starting VM '{name}' from state={state}")
            dom.create()

        except libvirt.libvirtError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to start VM '{name}': {e}",
            ) from e

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
            raise HTTPException(
                status_code=500,
                detail=f"Failed to inspect VM '{name}': {e}",
            ) from e

        if state == libvirt.VIR_DOMAIN_SHUTOFF:
            # Already stopped -> this is fine, no error
            log_event(f"[vm] stop_vm called for '{name}' but it is already shut off – no-op")
            return

        # Try snapshot only if VM is actually active-ish
        try:
            self.backup_manager.create_snapshot(vm_name=name)
        except Exception as e:  # noqa: BLE001
            log_event(f"[vm] Snapshot on stop failed for '{name}': {e}")

        # 1) Ask libvirt for graceful shutdown
        try:
            log_event(f"[vm] Graceful shutdown requested for VM '{name}' from state={state}")
            dom.shutdown()
        except libvirt.libvirtError as e:
            log_event(f"[vm] Graceful shutdown failed for '{name}': {e}; will try forced destroy")
            # Fall through to forced destroy below

        # 2) Poll a bit to see if it actually turned off
        timeout_sec = 15
        interval = 1
        waited = 0

        while waited < timeout_sec:
            try:
                info = dom.info()
                curr_state = info[0]
            except libvirt.libvirtError as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to inspect VM '{name}' during shutdown: {e}",
                ) from e

            if curr_state == libvirt.VIR_DOMAIN_SHUTOFF:
                log_event(f"[vm] VM '{name}' gracefully shut off after {waited}s")
                return

            time.sleep(interval)
            waited += interval

        # 3) If we get here, graceful shutdown did not complete in time -> force destroy
        log_event(
            f"[vm] VM '{name}' did not shut down within {timeout_sec}s "
            f"(last state={curr_state}); attempting forced destroy()"
        )

        try:
            dom.destroy()
            log_event(f"[vm] VM '{name}' forcefully powered off via destroy()")
            return
        except libvirt.libvirtError as e:
            # Only here we truly give up and return 500
            raise HTTPException(
                status_code=500,
                detail=f"Failed to force stop VM '{name}': {e}",
            ) from e

    def delete_vm(self, name: str) -> None:
        dom = self._get_domain(name)

        # Ensure VM is off
        try:
            if dom.isActive():
                dom.destroy()
        except libvirt.libvirtError:
            pass

        # Undefine domain and remove disk
        try:
            disk_path = str(VM_STORAGE_PATH / f"{name}.qcow2")
            dom.undefineFlags(libvirt.VIR_DOMAIN_UNDEFINE_MANAGED_SAVE)
            if os.path.exists(disk_path):
                os.remove(disk_path)
            log_event(f"[vm] Deleted VM '{name}', disk={disk_path}")
        except libvirt.libvirtError as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete VM '{name}': {e}") from e

    def list_vms(self) -> List[Dict[str, Any]]:
        domains = self.conn.listAllDomains()
        vms: List[Dict[str, Any]] = []
        for dom in domains:
            try:
                info = dom.info()
                vms.append(
                    {
                        "name": dom.name(),
                        "id": dom.ID(),
                        "state": info[0],
                        "max_memory": info[1],
                        "memory": info[2],
                        "vcpus": info[3],
                        "cpu_time": info[4],
                    }
                )
            except libvirt.libvirtError:
                continue
        return vms

    # ------------------------------------------------------------------
    # VM configuration (Ansible)
    # ------------------------------------------------------------------
    def configure_vm_with_ansible(self, vm_name: str) -> None:
        """
        Run ansible playbook to configure the VM.

        - Uses in-memory stored sudo/become password if provided via
          AnsibleAuthManager.
        - If no password is provided, it runs as usual, which works on
          hosts with passwordless sudo.
        """
        cmd = [
            "ansible-playbook",
            "-i",
            ANSIBLE_HOSTS_FILE,
            ANSIBLE_PLAYBOOK,
            "-e",
            f"target_host={vm_name}",
        ]

        env = os.environ.copy()

        become_password = AnsibleAuthManager.get_password()
        extra: list[str] = []

        # If user provided password via /ansible/auth, pass it to Ansible
        if become_password:
            env["ANSIBLE_BECOME_PASSWORD"] = become_password
            extra.extend(
                [
                    "-e",
                    f"ansible_become_pass={become_password}",
                ]
            )

        full_cmd = cmd + extra
        log_event(f"[ansible] Running playbook for VM {vm_name}: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                env=env,
            )
        except FileNotFoundError as e:
            msg = f"ansible-playbook not found: {e}"
            log_event(f"[ansible] {msg}")
            raise HTTPException(
                status_code=500,
                detail=f"Ansible configuration failed: {msg}",
            )

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            combined = "\n".join(part for part in [stderr, stdout] if part) or "unknown error"
            log_event(f"[ansible] FAILED for VM {vm_name}: {combined}")
            raise HTTPException(
                status_code=500,
                detail=f"Ansible configuration failed: {combined}",
            )

        log_event(f"[ansible] VM {vm_name} configured successfully")

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
        return {
            "name": name,
            "state": info[0],
            "max_memory": info[1],
            "memory": info[2],
            "vcpus": info[3],
            "cpu_time": info[4],
        }
