from typing import Optional
from threading import Lock


class AnsibleAuthManager:
    """
    Simple in-memory storage for Ansible sudo/become password.

    - Password is stored only in process memory (not on disk).
    - Not logged anywhere.
    - If no password is set, Ansible will run without become_pass, which
      works on hosts with passwordless sudo.
    """

    _password: Optional[str] = None
    _lock: Lock = Lock()

    @classmethod
    def set_password(cls, password: str) -> None:
        with cls._lock:
            cls._password = password

    @classmethod
    def clear_password(cls) -> None:
        with cls._lock:
            cls._password = None

    @classmethod
    def get_password(cls) -> Optional[str]:
        with cls._lock:
            return cls._password
