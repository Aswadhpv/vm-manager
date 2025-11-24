import threading
import time
from typing import Optional

import psutil
from prometheus_client import Counter, Gauge, Histogram

from config.settings import (
    METRICS_REFRESH_INTERVAL,
    HYPERVISOR_TYPE,
)
from core.logger import log_event

# -----------------------------
# HTTP / API level metrics
# -----------------------------
REQUEST_COUNT = Counter(
    "vm_manager_requests_total",
    "Total HTTP requests to vm-manager",
    ["method", "endpoint"],
)

REQUEST_LATENCY = Histogram(
    "vm_manager_request_latency_seconds",
    "Latency of HTTP requests to vm-manager",
    ["endpoint"],
)


# -----------------------------
# VM / user metrics
# -----------------------------
VM_CREATED_TOTAL = Counter(
    "vm_created_total",
    "Total number of VMs created",
    ["owner"],
)

VM_ACTIVE = Gauge(
    "vm_active_total",
    "Number of active (running) VMs",
)

VM_PER_USER = Gauge(
    "vm_per_user",
    "Number of VMs currently existing per user",
    ["owner"],
)

VM_LAST_ACTIVITY = Gauge(
    "vm_last_activity_timestamp",
    "UNIX timestamp of the last VM operation for a given user",
    ["owner"],
)

SSH_SESSIONS_ACTIVE = Gauge(
    "vm_ssh_sessions_active",
    "Number of active SSH WebSocket sessions",
    ["owner", "vm_name"],
)

# -----------------------------
# Host / capacity metrics
# -----------------------------
HOST_CPU_USAGE = Gauge(
    "vm_manager_host_cpu_usage_percent",
    "Host CPU usage in percent",
)

HOST_MEMORY_USAGE = Gauge(
    "vm_manager_host_memory_usage_percent",
    "Host memory usage in percent",
)

HOST_DISK_USAGE = Gauge(
    "vm_manager_host_disk_usage_percent",
    "Host disk usage (root filesystem) in percent",
)

HYPERVISOR_INFO = Gauge(
    "vm_manager_hypervisor_type",
    "Label gauge exposing configured hypervisor type (for Grafana filters)",
    ["type"],
)


def init_static_metrics() -> None:
    # Set a value 1.0 for the configured hypervisor type, 0.0 for others
    for hv in ["qemu", "kvm", "hyperv", "vmware", "xen", "proxmox"]:
        value = 1.0 if hv == HYPERVISOR_TYPE else 0.0
        HYPERVISOR_INFO.labels(type=hv).set(value)


def record_vm_created(owner: Optional[str]) -> None:
    owner_label = owner or "anonymous"
    VM_CREATED_TOTAL.labels(owner=owner_label).inc()
    VM_PER_USER.labels(owner=owner_label).inc()
    VM_LAST_ACTIVITY.labels(owner=owner_label).set(time.time())


def record_vm_deleted(owner: Optional[str]) -> None:
    owner_label = owner or "anonymous"
    VM_PER_USER.labels(owner=owner_label).dec()
    VM_LAST_ACTIVITY.labels(owner=owner_label).set(time.time())


def record_vm_activity(owner: Optional[str]) -> None:
    owner_label = owner or "anonymous"
    VM_LAST_ACTIVITY.labels(owner=owner_label).set(time.time())


def record_ssh_session_change(owner: Optional[str], vm_name: str, delta: int) -> None:
    owner_label = owner or "anonymous"
    current = SSH_SESSIONS_ACTIVE.labels(owner=owner_label, vm_name=vm_name)._value.get()
    SSH_SESSIONS_ACTIVE.labels(owner=owner_label, vm_name=vm_name).set(max(current + delta, 0))


def start_background_collectors() -> None:
    """
    Collect host-level capacity metrics periodically using psutil.
    This is enough for Grafana dashboards for CPU/memory/disk.
    """

    def loop() -> None:
        log_event("[metrics] Starting background host metrics collector")
        while True:
            try:
                HOST_CPU_USAGE.set(psutil.cpu_percent(interval=1))
                HOST_MEMORY_USAGE.set(psutil.virtual_memory().percent)
                HOST_DISK_USAGE.set(psutil.disk_usage("/").percent)
            except Exception as e:  # noqa: BLE001
                log_event(f"[metrics] Collector error: {e}")
            time.sleep(METRICS_REFRESH_INTERVAL)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
