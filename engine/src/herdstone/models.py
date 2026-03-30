from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Machine:
    id: str
    name: str
    hostname: str
    user: str
    port: int = 22
    groups: list[str] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)
    identity_file: str | None = None
    harness: str = "ssh"
    status: str = "unknown"
    last_seen: datetime | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class CommandResult:
    machine_id: str
    command: str
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    timestamp: datetime
