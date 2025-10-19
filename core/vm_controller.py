import libvirt
import uuid
import os
import subprocess
from fastapi import HTTPException
from config.settings import (
    BASE_IMAGE_PATH,
    VM_STORAGE_PATH,
    DEFAULT_MEMORY_MB,
    DEFAULT_VCPU,
    ANSIBLE_HOSTS_FILE,
    ANSIBLE_PLAYBOOK
)
from core.logger import log_event
from core.backup_manager import BackupManager


class VMController:
    def __init__(self):
        # Connect to the local KVM hypervisor
        self.conn = libvirt.open("qemu:///system")
        if self.conn is None:
            raise Exception("Failed to connect to qemu:///system")

        # Initialize backup manager
        self.backup_manager = BackupManager()

    def create_vm(self, name, memory_mb=DEFAULT_MEMORY_MB, vcpus=DEFAULT_VCPU):
        """
        Create a new VM from base image
        """
        vm_uuid = str(uuid.uuid4())
        vm_image = os.path.join(VM_STORAGE_PATH, f"{name}.qcow2")

        # Clone from base image with explicit backing format
        cmd = [
            "qemu-img", "create",
            "-f", "qcow2",    # format of new image
            "-F", "qcow2",    # format of base image
            "-b", BASE_IMAGE_PATH,
            vm_image
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            log_event(f"Failed to create VM image {vm_image}: {result.stderr}")
            raise HTTPException(status_code=500, detail=f"Failed to create VM image: {result.stderr}")

        # Define the VM XML
        xml = f"""
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
            </interface>
            <graphics type='vnc' port='-1' autoport='yes'/>
          </devices>
        </domain>
        """

        try:
            dom = self.conn.defineXML(xml)
        except libvirt.libvirtError as e:
            log_event(f"Failed to define VM {name}: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to define VM: {str(e)}")

        if dom is None:
            log_event(f"Failed to define VM {name}")
            raise HTTPException(status_code=500, detail="Failed to define VM")

        log_event(f"VM {name} created successfully with UUID {vm_uuid}")

        # Automatically configure VM with Ansible
        self.configure_vm_ansible(name)

        return {"name": name, "uuid": vm_uuid}

    def start_vm(self, name):
        """
        Start an existing VM
        """
        try:
            dom = self.conn.lookupByName(name)
            dom.create()
            log_event(f"VM {name} started")
        except libvirt.libvirtError as e:
            log_event(f"Failed to start VM {name}: {str(e)}")
            raise HTTPException(status_code=404, detail=f"VM {name} not found or cannot be started: {str(e)}")

        return {"name": name, "status": "started"}

    def stop_vm(self, name):
        """
        Shutdown an existing VM and create a snapshot
        """
        try:
            dom = self.conn.lookupByName(name)
            dom.shutdown()
            log_event(f"VM {name} stopped")

            # Auto-create snapshot after shutdown
            try:
                snapshot_name = self.backup_manager.create_snapshot(name)
                log_event(f"Snapshot {snapshot_name} created for VM {name}")
            except Exception as e:
                log_event(f"Snapshot failed for VM {name}: {str(e)}")

        except libvirt.libvirtError as e:
            log_event(f"Failed to stop VM {name}: {str(e)}")
            raise HTTPException(status_code=404, detail=f"VM {name} not found or cannot be stopped: {str(e)}")

        return {"name": name, "status": "stopped"}

    def delete_vm(self, name):
        """
        Delete an existing VM and its disk image
        """
        try:
            dom = self.conn.lookupByName(name)
            dom.undefine()
            log_event(f"VM {name} undefined")
        except libvirt.libvirtError:
            log_event(f"VM {name} not found in libvirt")
            raise HTTPException(status_code=404, detail=f"VM {name} not found")

        # Delete disk image
        vm_image = os.path.join(VM_STORAGE_PATH, f"{name}.qcow2")
        if os.path.exists(vm_image):
            os.remove(vm_image)
            log_event(f"VM image {vm_image} deleted")
        else:
            log_event(f"VM image {vm_image} not found")
            raise HTTPException(status_code=404, detail=f"VM disk image for {name} not found")

        return {"name": name, "status": "deleted"}

    def list_vms(self):
        """
        List all VMs with their states
        """
        domains = self.conn.listAllDomains()
        vm_list = []
        for dom in domains:
            state, max_mem, mem, vcpus, cpu_time = dom.info()
            vm_list.append({
                "name": dom.name(),
                "uuid": dom.UUIDString(),
                "state": state,
                "memory": mem,
                "vcpus": vcpus
            })
        return vm_list

    def configure_vm_ansible(self, vm_name):
        """
        Run ansible playbook to configure the VM
        """
        cmd = [
            "ansible-playbook",
            "-i", ANSIBLE_HOSTS_FILE,
            ANSIBLE_PLAYBOOK,
            "-e", f"target_host={vm_name}"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            log_event(f"Ansible failed for VM {vm_name}: {result.stderr}")
            raise HTTPException(status_code=500, detail=f"Ansible configuration failed: {result.stderr}")
        else:
            log_event(f"VM {vm_name} configured successfully with Ansible")
