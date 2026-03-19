import os
from fastapi import HTTPException
from config.settings import PLAYBOOKS_DIR
from core.logger import log_event

class PlaybookManager:
    def list_playbooks(self) -> list[str]:
        if not PLAYBOOKS_DIR.exists():
            return []
        return [f for f in os.listdir(PLAYBOOKS_DIR) if f.endswith((".yml", ".yaml"))]

    def get_playbook(self, name: str) -> str:
        path = PLAYBOOKS_DIR / name
        if not path.exists():
            raise HTTPException(status_code=404, detail="Playbook not found")
        return path.read_text()

    def create_playbook(self, name: str, content: str) -> dict:
        path = PLAYBOOKS_DIR / name
        if path.exists():
            raise HTTPException(status_code=400, detail="Playbook already exists")
        path.write_text(content)
        log_event(f"[ansible] Created new playbook: {name}")
        return {"status": "created", "name": name}

    def update_playbook(self, name: str, content: str) -> dict:
        path = PLAYBOOKS_DIR / name
        if not path.exists():
            raise HTTPException(status_code=404, detail="Playbook not found")
        path.write_text(content)
        log_event(f"[ansible] Updated playbook: {name}")
        return {"status": "updated", "name": name}

    def delete_playbook(self, name: str) -> dict:
        path = PLAYBOOKS_DIR / name
        if not path.exists():
            raise HTTPException(status_code=404, detail="Playbook not found")
        path.unlink()
        log_event(f"[ansible] Deleted playbook: {name}")
        return {"status": "deleted", "name": name}