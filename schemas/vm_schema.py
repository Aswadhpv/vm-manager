from pydantic import BaseModel, Field

class VMCreateSchema(BaseModel):
    """
        Schema for creating a new VM.

        'owner' is used for per-user metrics (how many VMs this user created/uses).
        In a real integration this would come from your auth layer
        (e.g. JWT or X-User-Id header), but for the thesis it's explicit.
    """

    name: str = Field(..., description="Unique VM name")
    base_image: str = Field(
        default="base.qcow2",
        description="Name of the base image in vm-images/base"
    )
    playbooks: list[str] = Field(
        default=[],
        description="List of playbook filenames to run sequentially"
    )
    memory_mb: int = Field(512, ge=256, description="RAM in MiB")
    vcpus: int = Field(1, ge=1, description="Number of virtual CPUs")
    owner: str | None = Field(
        default=None,
        description="Logical user identifier (email, student number, etc.)",
    )

class PlaybookSchema(BaseModel):
    name: str = Field(..., description="Filename, e.g., setup_docker.yml")
    content: str = Field(..., description="Raw YAML content of the playbook")

class PoolCapacitySchema(BaseModel):
    size: int = Field(..., ge=0, description="New target size for the hot VM pool")