from pydantic import BaseModel

class VMCreateSchema(BaseModel):
    name: str
    memory_mb: int = 512
    vcpus: int = 1
