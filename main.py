import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import asyncssh
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from config.settings import METRICS_ENABLED, SSH_LOG_DIR
from core.vm_controller import VMController
from core.pool_manager import PoolManager
from core.playbook_manager import PlaybookManager
from core.metrics import (
    REQUEST_COUNT, REQUEST_LATENCY, record_vm_created, record_vm_deleted,
    record_vm_activity, record_ssh_session_change, init_static_metrics, start_background_collectors,
)
from core.logger import log_event
from core.ansible_auth import AnsibleAuthManager
from schemas.vm_schema import VMCreateSchema, PlaybookSchema, PoolCapacitySchema


@asynccontextmanager
async def lifespan(app: FastAPI):
    if METRICS_ENABLED:
        init_static_metrics()
        start_background_collectors()
        log_event("[app] Metrics enabled and collectors started")
    yield


app = FastAPI(
    title="Virtual Manager API",
    description="Manage virtual machines with dynamic base images, cloud-init, and Ansible integration.",
    version="2.1.0",
    lifespan=lifespan,
)

vm_controller = VMController()
pool_manager = PoolManager(vm_controller)
playbook_manager = PlaybookManager()


class AnsibleAuthSchema(BaseModel):
    password: str


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    if not METRICS_ENABLED or request.url.path == "/metrics":
        return await call_next(request)
    start_time = time.time()
    try:
        return await call_next(request)
    finally:
        REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path).inc()
        REQUEST_LATENCY.labels(endpoint=request.url.path).observe(time.time() - start_time)


@app.get("/", tags=["System"])
def root():
    return {"message": "Virtual Manager API is running", "version": app.version}


@app.post("/vms/create", tags=["VM Management"])
def create_vm(payload: VMCreateSchema):
    try:
        vm_info = vm_controller.create_vm(
            name=payload.name,
            base_image=payload.base_image,
            memory_mb=payload.memory_mb,
            vcpus=payload.vcpus,
            owner=payload.owner,
        )
        try:
            vm_controller.configure_vm_with_ansible(payload.name, payload.playbooks)
            status = "created"
            ansible_error = None
        except HTTPException as e:
            status = "created_with_ansible_error"
            ansible_error = e.detail

        record_vm_created(payload.owner)
        content = {"status": status, "vm": vm_info}
        if ansible_error: content["ansible_error"] = ansible_error
        return JSONResponse(status_code=201, content=content)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/vms/start/{name}", tags=["VM Management"])
def start_vm(name: str, owner: Optional[str] = None):
    try:
        vm_controller.start_vm(name)
        record_vm_activity(owner)
        return {"status": "started", "vm_name": name}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/vms/stop/{name}", tags=["VM Management"])
def stop_vm(name: str, owner: Optional[str] = None):
    try:
        vm_controller.stop_vm(name)
        record_vm_activity(owner)
        return {"status": "stopped", "vm_name": name}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/vms/delete/{name}", tags=["VM Management"])
def delete_vm(name: str, owner: Optional[str] = None):
    try:
        vm_controller.delete_vm(name)
        record_vm_deleted(owner)
        return {"status": "deleted", "vm_name": name}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/vms/list", tags=["VM Management"])
def list_vms():
    return {"vms": vm_controller.list_vms()}


@app.get("/pool/status", tags=["Pool"])
def get_pool_status():
    return pool_manager.get_pool_status()


@app.post("/pool/allocate", tags=["Pool"])
def allocate_from_pool():
    name = pool_manager.get_available_vm()
    if not name: raise HTTPException(status_code=503, detail="No VM in pool")
    return {"vm_name": name}


@app.put("/pool/capacity", tags=["Pool"])
def set_pool_capacity(payload: PoolCapacitySchema):
    return pool_manager.set_pool_capacity(payload.size)


@app.get("/playbooks", tags=["Ansible Playbooks"])
def list_playbooks():
    return {"playbooks": playbook_manager.list_playbooks()}


@app.get("/playbooks/{name}", tags=["Ansible Playbooks"])
def get_playbook(name: str):
    return {"name": name, "content": playbook_manager.get_playbook(name)}


@app.post("/playbooks", tags=["Ansible Playbooks"])
def create_playbook(payload: PlaybookSchema):
    return playbook_manager.create_playbook(payload.name, payload.content)


@app.put("/playbooks/{name}", tags=["Ansible Playbooks"])
def update_playbook(name: str, payload: PlaybookSchema):
    if name != payload.name:
        raise HTTPException(status_code=400, detail="Name in URL must match payload")
    return playbook_manager.update_playbook(payload.name, payload.content)


@app.delete("/playbooks/{name}", tags=["Ansible Playbooks"])
def delete_playbook(name: str):
    return playbook_manager.delete_playbook(name)


@app.post("/ansible/auth", tags=["Ansible"])
def set_ansible_password(payload: AnsibleAuthSchema):
    AnsibleAuthManager.set_password(payload.password)
    return {"status": "ok"}


@app.post("/ansible/clear", tags=["Ansible"])
def clear_ansible_password():
    AnsibleAuthManager.clear_password()
    return {"status": "ok"}


@app.get("/metrics", tags=["Monitoring"])
def metrics():
    if not METRICS_ENABLED: raise HTTPException(status_code=404)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.websocket("/ws/vm/{name}/status")
async def vm_status_stream(websocket: WebSocket, name: str):
    await websocket.accept()
    try:
        while True:
            await websocket.send_text(json.dumps(vm_controller.get_vm_state(name)))
            await asyncio.sleep(1.0)
    except Exception:
        await websocket.close()


async def _proxy_websocket_to_ssh(websocket: WebSocket, ssh_process, log_file):
    async for message in websocket.iter_text():
        log_file.write(json.dumps([time.time(), "i", message]) + "\n")
        ssh_process.stdin.write(message)
        await ssh_process.stdin.drain()


async def _proxy_ssh_to_websocket(websocket: WebSocket, ssh_process, log_file):
    async for data in ssh_process.stdout:
        log_file.write(json.dumps([time.time(), "o", data]) + "\n")
        await websocket.send_text(data)


@app.websocket("/ws/vm/{name}/terminal")
async def vm_terminal(websocket: WebSocket, name: str):
    # Retrieve owner and the newly added IP from the query parameters
    owner = websocket.query_params.get("owner", None)
    ip = websocket.query_params.get("ip", None)

    await websocket.accept()
    record_ssh_session_change(owner, name, +1)

    session_id = str(uuid.uuid4())
    log_path = SSH_LOG_DIR / f"{session_id}.cast"
    ssh_target = vm_controller.get_vm_ssh_target(name)

    # Use the manually provided IP if it exists, otherwise fall back to Libvirt target
    target_host = ip if ip else ssh_target["host"]
    print(f"DEBUG: Attempting SSH connection to {target_host} on port {ssh_target['port']}")

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "version": 2, "width": 80, "height": 24, "timestamp": int(time.time()),
            "env": {"TERM": "xterm-256color", "SHELL": "/bin/bash"},
            "vm_name": name, "owner": owner
        }) + "\n")
        try:
            # Safely check if the SSH key actually exists on the hard drive
            import os
            key_path = ssh_target.get("key_path")
            valid_keys = [key_path] if key_path and os.path.exists(key_path) else None

            # Connect using the overridden target_host
            conn = await asyncssh.connect(
                host=target_host,
                port=ssh_target["port"],
                username=ssh_target["username"],
                password="student",
                client_keys=valid_keys,
                known_hosts=None
            )
            process = await conn.create_process()
            await asyncio.wait([
                asyncio.create_task(_proxy_websocket_to_ssh(websocket, process, f)),
                asyncio.create_task(_proxy_ssh_to_websocket(websocket, process, f))
            ], return_when=asyncio.FIRST_COMPLETED)
        except Exception as e:
            await websocket.send_text(f"SSH Error: {e}")
            print(f"DEBUG SSH Error: {e}")
        finally:
            record_ssh_session_change(owner, name, -1)
            record_vm_activity(owner)
            try:
                await websocket.close()
            except Exception:
                pass