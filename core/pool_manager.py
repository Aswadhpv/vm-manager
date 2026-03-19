import os
import libvirt

from config.settings import DEFAULT_BASE_IMAGE, DEFAULT_MEMORY_MB, DEFAULT_VCPU, VM_STORAGE_PATH, HOT_VM_POOL_SIZE
from core.logger import log_event


class PoolManager:
    """
        Manages a small pool of pre-created VMs.

        Thesis idea:

        - On backend startup, create N VMs (pool-vm-1..N) if they don't exist.
        - Ensure they are powered off (state=shut off) but fully provisioned.
        - When a student requests a VM from the pool, we can allocate one instantly,
          instead of waiting for full clone + provisioning each time.
    """

    def __init__(self, vm_controller):
        self.vm_controller = vm_controller
        self.pool_size = HOT_VM_POOL_SIZE
        self.pool: list[str] = []
        self.init_pool()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_pool_vm_exists_and_stopped(self, name: str) -> None:
        """
                Make sure a pool VM with given name exists and is shut off.

                - If libvirt domain exists:
                    - If running, shut it down.
                    - If shut off, do nothing.
                - If libvirt domain does NOT exist:
                    - If disk file exists, remove it (orphan).
                    - Create a fresh VM via VMController.
                    - Shut it down so it's ready in the pool.
        """
        conn = self.vm_controller.conn
        disk_path = VM_STORAGE_PATH / f"{name}.qcow2"

        try:
            dom = conn.lookupByName(name)
            state = dom.info()[0]
            if state == 1:
                try:
                    dom.shutdown()
                except libvirt.libvirtError:
                    dom.destroy()
        except libvirt.libvirtError:
            if disk_path.exists():
                try:
                    os.remove(disk_path)
                except OSError:
                    pass

            self.vm_controller.create_vm(
                name=name,
                base_image=DEFAULT_BASE_IMAGE,
                memory_mb=DEFAULT_MEMORY_MB,
                vcpus=DEFAULT_VCPU,
                owner="pool",
            )
            self.vm_controller.stop_vm(name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def init_pool(self) -> None:
        """
                Initialize hot VM pool.

                If pool VMs already exist, they are reused and shut off.
                If they don't exist or are broken, they are recreated.
        """
        self.pool = []
        for idx in range(1, self.pool_size + 1):
            name = f"pool-vm-{idx}"
            try:
                self._ensure_pool_vm_exists_and_stopped(name)
                self.pool.append(name)
            except Exception as e:
                log_event(f"[pool] ERROR initializing {name}: {e}")

    def set_pool_capacity(self, new_size: int) -> dict:
        log_event(f"[pool] Updating pool size from {self.pool_size} to {new_size}")

        while len(self.pool) > new_size:
            name = self.pool.pop()
            try:
                self.vm_controller.delete_vm(name)
                log_event(f"[pool] Removed VM {name} to shrink pool.")
            except Exception as e:
                log_event(f"[pool] Failed to delete pool VM {name}: {e}")

        self.pool_size = new_size
        self.init_pool()
        return {"status": "success", "new_size": self.pool_size, "current_pool": self.pool}

    def get_pool_status(self) -> list[dict]:
        """
                Return the status of each pool VM (name + libvirt state).
        """
        status = []
        for name in self.pool:
            try:
                state_code = self.vm_controller.conn.lookupByName(name).info()[0]
                status.append({"name": name, "state_code": state_code})
            except libvirt.libvirtError:
                status.append({"name": name, "state_code": None, "state": "not_found"})
        return status

    def get_available_vm(self) -> str | None:
        """
                Return the first available hot VM.

                Strategy:

                - For each pool name:
                    - If domain missing, recreate it (including disk) and return it.
                    - If domain exists, ensure it's shut off, then return it.
                - Only return None if everything truly fails.
        """
        for name in self.pool:
            try:
                dom = self.vm_controller.conn.lookupByName(name)
            except libvirt.libvirtError:
                try:
                    self._ensure_pool_vm_exists_and_stopped(name)
                    return name
                except Exception:
                    continue

            try:
                if dom.info()[0] != 5:
                    try:
                        dom.shutdown()
                    except libvirt.libvirtError:
                        dom.destroy()
                return name
            except libvirt.libvirtError:
                continue
        return None