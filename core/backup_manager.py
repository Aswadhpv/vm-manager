import os
import subprocess
from config.settings import VM_STORAGE_PATH

class BackupManager:
    def __init__(self):
        self.backup_dir = os.path.join(VM_STORAGE_PATH, "backups")
        os.makedirs(self.backup_dir, exist_ok=True)

    def create_snapshot(self, vm_name, snapshot_name=None):
        if snapshot_name is None:
            snapshot_name = f"{vm_name}-snapshot"
        cmd = [
            "virsh", "snapshot-create-as",
            vm_name,
            snapshot_name,
            "--disk-only",
            "--atomic",
            "--no-metadata",
            "--quiesce"
        ]
        subprocess.run(cmd, check=True)
        return snapshot_name

    def list_snapshots(self, vm_name):
        result = subprocess.run(
            ["virsh", "snapshot-list", vm_name, "--name"],
            capture_output=True, text=True
        )
        return result.stdout.splitlines()
