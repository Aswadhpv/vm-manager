import os
import subprocess
from config.settings import BACKUP_DIR
from core.logger import log_event


class BackupManager:
    """
    Thin wrapper around virsh snapshots for libvirt-based hypervisors.

    For this thesis project we use simple disk-only snapshots without
    requiring the QEMU guest agent. This avoids errors like:

        "argument unsupported: QEMU guest agent is not configured"

    and still demonstrates integration with libvirt backup mechanisms.
    """

    def __init__(self) -> None:
        self.backup_dir = BACKUP_DIR
        os.makedirs(self.backup_dir, exist_ok=True)

    def create_snapshot(self, vm_name: str, snapshot_name: str | None = None) -> str:
        if snapshot_name is None:
            snapshot_name = f"{vm_name}-snapshot"

        # NOTE: we deliberately do NOT use '--quiesce' here because that
        # requires the QEMU guest agent to be installed and configured
        # inside the VM. For the purposes of this project, a simple disk-only
        # snapshot is sufficient and avoids "argument unsupported" errors.
        cmd = [
            "virsh",
            "snapshot-create-as",
            vm_name,
            snapshot_name,
            "--disk-only",
            "--atomic",
            "--no-metadata",
        ]

        log_event(f"[backup] Creating snapshot {snapshot_name} for VM {vm_name}: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )
            if result.stdout:
                log_event(f"[backup] virsh output for {vm_name}: {result.stdout.strip()}")
        except subprocess.CalledProcessError as e:
            # Log the error but do NOT crash the main VM operation.
            # Snapshots are a best-effort feature here.
            err = e.stderr.strip() if e.stderr else str(e)
            log_event(f"[backup] WARNING: snapshot creation failed for {vm_name}: {err}")
            # still return the requested snapshot name so callers can continue
        return snapshot_name

    def list_snapshots(self, vm_name: str) -> list[str]:
        cmd = ["virsh", "snapshot-list", vm_name, "--name"]
        log_event(f"[backup] Listing snapshots for VM {vm_name}: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )
            snapshots = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            log_event(f"[backup] Found {len(snapshots)} snapshots for VM {vm_name}")
            return snapshots
        except subprocess.CalledProcessError as e:
            err = e.stderr.strip() if e.stderr else str(e)
            log_event(f"[backup] WARNING: failed to list snapshots for {vm_name}: {err}")
            return []
