import libvirt
from config.settings import HOT_VM_POOL_SIZE
from core.logger import log_event

class PoolManager:
    def __init__(self, vm_controller):
        self.vm_controller = vm_controller
        self.pool_size = HOT_VM_POOL_SIZE
        self.pool = []
        self.init_pool()

    def init_pool(self):
        """
        Initialize hot VM pool safely.
        If VM already exists, it will be stopped and added to the pool.
        """
        for i in range(self.pool_size):
            name = f"hot-vm-{i}"
            try:
                # Check if VM already exists
                try:
                    dom = self.vm_controller.conn.lookupByName(name)
                    log_event(f"Hot VM {name} already exists. Ensuring it's stopped.")
                    if dom.info()[0] != 5:  # 5 = shut off
                        dom.shutdown()
                    self.pool.append(name)
                    log_event(f"Hot VM {name} added to pool")
                    continue  # skip creation
                except libvirt.libvirtError:
                    # VM does not exist, proceed to create
                    pass

                # Create new hot VM
                self.vm_controller.create_vm(name)
                self.vm_controller.stop_vm(name)
                self.pool.append(name)
                log_event(f"Hot VM {name} created and added to pool")

            except Exception as e:
                log_event(f"Failed to initialize hot VM {name}: {str(e)}")

    def get_pool_status(self):
        """
        Return the status of all hot VMs in the pool
        """
        status = []
        for name in self.pool:
            try:
                dom = self.vm_controller.conn.lookupByName(name)
                state = dom.info()[0]
                status.append({"name": name, "state": state})
            except libvirt.libvirtError:
                status.append({"name": name, "state": "missing"})
        return status

    def get_available_vm(self):
        """
        Return the first available hot VM (powered off)
        """
        for name in self.pool:
            try:
                dom = self.vm_controller.conn.lookupByName(name)
                if dom.info()[0] == 5:  # 5 = shut off
                    return name
            except libvirt.libvirtError:
                continue
        return None
