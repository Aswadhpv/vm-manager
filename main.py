from fastapi import FastAPI, HTTPException
from core.vm_controller import VMController
from core.pool_manager import PoolManager
from schemas.vm_schema import VMCreateSchema

app = FastAPI(
    title="Virtual Manager API",
    description="Manage virtual machines for Code.Hedgehog lab tasks",
    version="1.0.0"
)

vm_controller = VMController()
pool_manager = PoolManager(vm_controller)

@app.get("/")
def root():
    return {"message": "Virtual Manager API is running"}

@app.post("/vms/create")
def create_vm(vm: VMCreateSchema):
    try:
        vm_id = vm_controller.create_vm(vm.name, vm.memory_mb, vm.vcpus)
        return {"status": "success", "vm_name": vm.name, "uuid": vm_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/vms/start/{name}")
def start_vm(name: str):
    try:
        vm_controller.start_vm(name)
        return {"status": "started", "vm_name": name}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/vms/stop/{name}")
def stop_vm(name: str):
    try:
        vm_controller.stop_vm(name)
        return {"status": "stopped", "vm_name": name}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/vms/delete/{name}")
def delete_vm(name: str):
    try:
        vm_controller.delete_vm(name)
        return {"status": "deleted", "vm_name": name}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/vms/list")
def list_vms():
    try:
        vms = vm_controller.list_vms()
        return {"vms": vms}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/vms/pool")
def get_pool():
    return pool_manager.get_pool_status()
