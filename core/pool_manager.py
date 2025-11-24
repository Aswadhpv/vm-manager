import os
import libvirt

from config.settings import HOT_VM_POOL_SIZE, DEFAULT_MEMORY_MB, DEFAULT_VCPU, VM_STORAGE_PATH
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
            info = dom.info()
            state = info[0]
            # libvirt states: 1=running, 5=shutoff
            if state == 1:
                log_event(f"[pool] Pool VM {name} is running, stopping it")
                try:
                    dom.shutdown()
                except libvirt.libvirtError:
                    # force destroy if graceful shutdown fails
                    dom.destroy()
                log_event(f"[pool] Pool VM {name} is now stopping (will transition to shut off)")
            else:
                log_event(f"[pool] Pool VM {name} already exists with state={state}")
        except libvirt.libvirtError:
            # Domain missing in libvirt
            if disk_path.exists():
                log_event(f"[pool] Orphan disk {disk_path} found for {name}, removing it")
                try:
                    os.remove(disk_path)
                except OSError as e:
                    log_event(f"[pool] Failed to remove orphan disk {disk_path}: {e}")

            log_event(f"[pool] Creating new pool VM {name}")
            vm_info = self.vm_controller.create_vm(
                name=name,
                memory_mb=DEFAULT_MEMORY_MB,
                vcpus=DEFAULT_VCPU,
                owner="pool",
            )
            log_event(f"[pool] Created pool VM {name}: {vm_info}")
            # Ensure it's stopped after creation, so it's ready
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
            except Exception as e:  # noqa: BLE001
                log_event(f"[pool] ERROR initializing pool VM {name}: {e}")

        log_event(f"[pool] Pool initialized with VMs: {self.pool}")

    def get_pool_status(self) -> list[dict]:
        """
        Return the status of each pool VM (name + libvirt state).
        """
        status: list[dict] = []
        conn = self.vm_controller.conn

        for name in self.pool:
            try:
                dom = conn.lookupByName(name)
                info = dom.info()
                state_code = info[0]
                # Basic mapping of state codes
                state_map = {
                    0: "no state",
                    1: "running",
                    2: "blocked",
                    3: "paused",
                    4: "shutting down",
                    5: "shut off",
                    6: "crashed",
                    7: "pmsuspended",
                }
                state_str = state_map.get(state_code, f"unknown({state_code})")
                status.append(
                    {
                        "name": name,
                        "state_code": state_code,
                        "state": state_str,
                    }
                )
            except libvirt.libvirtError:
                status.append(
                    {
                        "name": name,
                        "state_code": None,
                        "state": "not_found",
                    }
                )

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
        conn = self.vm_controller.conn

        for name in self.pool:
            try:
                dom = conn.lookupByName(name)
            except libvirt.libvirtError:
                # VM missing - recreate it and then return it
                log_event(f"[pool] Pool VM {name} missing in libvirt, recreating")
                try:
                    self._ensure_pool_vm_exists_and_stopped(name)
                    return name
                except Exception as e:  # noqa: BLE001
                    log_event(f"[pool] ERROR recreating pool VM {name}: {e}")
                    continue

            try:
                info = dom.info()
                state = info[0]

                # If it's running, we still consider it "usable", but for the
                # thesis idea we prefer to hand out shut off VMs.
                if state != 5:
                    log_event(f"[pool] Pool VM {name} is in state={state}, attempting to shut it off")
                    try:
                        dom.shutdown()
                    except libvirt.libvirtError:
                        dom.destroy()

                log_event(f"[pool] Returning pool VM {name} as available")
                return name
            except libvirt.libvirtError as e:
                log_event(f"[pool] ERROR checking state for {name}: {e}")
                continue

        return None
