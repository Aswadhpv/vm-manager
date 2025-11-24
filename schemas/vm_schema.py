from pydantic import BaseModel, Field


class VMCreateSchema(BaseModel):
    """
    Schema for creating a new VM.

    'owner' is used for per-user metrics (how many VMs this user created/uses).
    In a real integration this would come from your auth layer
    (e.g. JWT or X-User-Id header), but for the thesis it's explicit.
    """

    name: str = Field(..., description="Unique VM name")
    memory_mb: int = Field(512, ge=256, description="RAM in MiB")
    vcpus: int = Field(1, ge=1, description="Number of virtual CPUs")
    owner: str | None = Field(
        default=None,
        description="Logical user identifier (email, student number, etc.)",
    )
