import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import asyncssh
from fastapi import (
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    Request,
)
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from config.settings import METRICS_ENABLED, SSH_LOG_DIR
from core.vm_controller import VMController
from core.pool_manager import PoolManager
from core.metrics import (
    REQUEST_COUNT,
    REQUEST_LATENCY,
    record_vm_created,
    record_vm_deleted,
    record_vm_activity,
    record_ssh_session_change,
    init_static_metrics,
    start_background_collectors,
)
from core.logger import log_event
from core.ansible_auth import AnsibleAuthManager
from schemas.vm_schema import VMCreateSchema


@asynccontextmanager
async def lifespan(app: FastAPI):
    if METRICS_ENABLED:
        init_static_metrics()
        start_background_collectors()
        log_event("[app] Metrics enabled and collectors started")
    yield


app = FastAPI(
    title="Virtual Manager API",
    description=(
        "Manage virtual machines for Code.Hedgehog lab tasks.\n\n"
        "Features:\n"
        "- Multi-hypervisor via libvirt URI (QEMU/KVM, Hyper-V, VMware, Xen, Proxmox)\n"
        "- Prometheus/Grafana metrics\n"
        "- WebSocket SSH tunnel for terminal access\n"
        "- Asciinema-style logging of terminal sessions\n"
        "- Optional Ansible integration with sudo password provided via API"
    ),
    version="2.0.0",
    lifespan=lifespan,
)

vm_controller = VMController()
pool_manager = PoolManager(vm_controller)


class AnsibleAuthSchema(BaseModel):
    password: str


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    endpoint = request.url.path
    method = request.method

    if not METRICS_ENABLED or endpoint == "/metrics":
        return await call_next(request)

    start_time = time.time()
    try:
        response = await call_next(request)
        return response
    finally:
        duration = time.time() - start_time
        REQUEST_COUNT.labels(method=method, endpoint=endpoint).inc()
        REQUEST_LATENCY.labels(endpoint=endpoint).observe(duration)


@app.get("/", tags=["System"])
def root():
    return {
        "message": "Virtual Manager API is running",
        "version": app.version,
    }


@app.post("/vms/create", tags=["VM Management"])
def create_vm(payload: VMCreateSchema):
    try:
        vm_info = vm_controller.create_vm(
            name=payload.name,
            memory_mb=payload.memory_mb,
            vcpus=payload.vcpus,
            owner=payload.owner,
        )
        try:
            vm_controller.configure_vm_with_ansible(payload.name)
            status = "created"
            ansible_error = None
        except HTTPException as e:
            status = "created_with_ansible_error"
            ansible_error = e.detail

        record_vm_created(payload.owner)
        content = {
            "status": status,
            "vm": vm_info,
        }
        if ansible_error:
            content["ansible_error"] = ansible_error
        return JSONResponse(status_code=201, content=content)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/vms/start/{name}", tags=["VM Management"])
def start_vm(name: str, owner: Optional[str] = None):
    try:
        vm_controller.start_vm(name)
        record_vm_activity(owner)
        return {"status": "started", "vm_name": name}
    except HTTPException as e:
        raise e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/vms/stop/{name}", tags=["VM Management"])
def stop_vm(name: str, owner: Optional[str] = None):
    try:
        vm_controller.stop_vm(name)
        record_vm_activity(owner)
        return {"status": "stopped", "vm_name": name}
    except HTTPException as e:
        raise e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/vms/delete/{name}", tags=["VM Management"])
def delete_vm(name: str, owner: Optional[str] = None):
    try:
        vm_controller.delete_vm(name)
        record_vm_deleted(owner)
        return {"status": "deleted", "vm_name": name}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/vms/list", tags=["VM Management"])
def list_vms():
    try:
        vms = vm_controller.list_vms()
        return {"vms": vms}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/pool/status", tags=["Pool"])
def get_pool_status():
    return pool_manager.get_pool_status()


@app.post("/pool/allocate", tags=["Pool"])
def allocate_from_pool():
    name = pool_manager.get_available_vm()
    if not name:
        raise HTTPException(status_code=503, detail="No available VM in pool")
    return {"vm_name": name}


@app.post("/ansible/auth", tags=["Ansible"])
def set_ansible_password(payload: AnsibleAuthSchema):
    AnsibleAuthManager.set_password(payload.password)
    return {"status": "ok", "message": "Ansible sudo password stored in memory"}


@app.post("/ansible/clear", tags=["Ansible"])
def clear_ansible_password():
    AnsibleAuthManager.clear_password()
    return {"status": "ok", "message": "Ansible sudo password cleared"}


@app.get("/metrics", tags=["Monitoring"])
def metrics():
    if not METRICS_ENABLED:
        raise HTTPException(status_code=404, detail="Metrics disabled")
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.websocket("/ws/vm/{name}/status")
async def vm_status_stream(websocket: WebSocket, name: str):
    await websocket.accept()
    log_event(f"[ws-status] Client connected for VM {name}")
    try:
        while True:
            state = vm_controller.get_vm_state(name)
            await websocket.send_text(json.dumps(state))
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        log_event(f"[ws-status] Client disconnected for VM {name}")
    except Exception as e:  # noqa: BLE001
        log_event(f"[ws-status] Error for VM {name}: {e}")
        await websocket.close()


async def _proxy_websocket_to_ssh(
    websocket: WebSocket,
    ssh_process: asyncssh.SSHClientProcess,
    log_file,
):
    async for message in websocket.iter_text():
        timestamp = time.time()
        log_file.write(json.dumps([timestamp, "i", message]) + "\n")
        ssh_process.stdin.write(message)
        await ssh_process.stdin.drain()


async def _proxy_ssh_to_websocket(
    websocket: WebSocket,
    ssh_process: asyncssh.SSHClientProcess,
    log_file,
):
    async for data in ssh_process.stdout:
        timestamp = time.time()
        log_file.write(json.dumps([timestamp, "o", data]) + "\n")
        await websocket.send_text(data)


@app.websocket("/ws/vm/{name}/terminal")
async def vm_terminal(
    websocket: WebSocket,
    name: str,
):
    owner = websocket.query_params.get("owner", None)

    await websocket.accept()
    record_ssh_session_change(owner, name, +1)

    session_id = str(uuid.uuid4())
    log_path = SSH_LOG_DIR / f"{session_id}.cast"

    log_event(f"[ws-ssh] New SSH WebSocket session {session_id} for VM {name}, owner={owner}")

    ssh_target = vm_controller.get_vm_ssh_target(name)
    key_path = ssh_target.get("key_path")

    start_time = time.time()

    with open(log_path, "w", encoding="utf-8") as f:
        header = {
            "version": 2,
            "width": 80,
            "height": 24,
            "timestamp": int(start_time),
            "env": {
                "TERM": "xterm-256color",
                "SHELL": "/bin/bash",
            },
            "vm_name": name,
            "owner": owner,
        }
        f.write(json.dumps(header) + "\n")

        try:
            conn = await asyncssh.connect(
                host=ssh_target["host"],
                port=ssh_target["port"],
                username=ssh_target["username"],
                client_keys=[key_path] if key_path else None,
                known_hosts=None,
            )
            process = await conn.create_process()

            proxy_in = asyncio.create_task(_proxy_websocket_to_ssh(websocket, process, f))
            proxy_out = asyncio.create_task(_proxy_ssh_to_websocket(websocket, process, f))

            await asyncio.wait(
                [proxy_in, proxy_out],
                return_when=asyncio.FIRST_COMPLETED,
            )

        except asyncssh.Error as e:
            error_msg = f"[ws-ssh] SSH error for VM {name}: {e}"
            log_event(error_msg)
            await websocket.send_text(error_msg)
        except WebSocketDisconnect:
            log_event(f"[ws-ssh] WebSocket disconnect for VM {name}")
        except Exception as e:  # noqa: BLE001
            log_event(f"[ws-ssh] Unexpected error for VM {name}: {e}")
        finally:
            record_ssh_session_change(owner, name, -1)
            record_vm_activity(owner)
            try:
                await websocket.close()
            except Exception:  # noqa: BLE001
                pass

            log_event(
                f"[ws-ssh] Session {session_id} closed for VM {name}, "
                f"log={log_path}"
            )
