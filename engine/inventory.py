import re
from pathlib import Path

from .config import get_inventory_path
from .models import Machine


def parse_inventory(path: Path | None = None) -> list[Machine]:
    """Parse an Ansible INI inventory file into a list of Machine objects.

    Only hosts with ssh_alias are included (matching the shell parser behavior).
    """
    if path is None:
        path = get_inventory_path()
    if path is None or not path.is_file():
        return []

    machines: list[Machine] = []
    current_group: str | None = None

    for line in path.read_text().splitlines():
        stripped = line.strip()

        # Skip empty lines and comments
        if not stripped or stripped.startswith("#"):
            continue

        # Group header like [macs] — skip [group:vars] sections
        group_match = re.match(r"^\[([^:\]]+)\]$", stripped)
        if group_match:
            current_group = group_match.group(1)
            continue

        # Skip :vars sections
        if re.match(r"^\[.+:vars\]$", stripped):
            current_group = None
            continue

        # Inside a :vars block, skip variable assignments
        if current_group is None:
            continue

        # Must have ssh_alias to be included
        if "ssh_alias=" not in stripped:
            continue

        parts = stripped.split()
        inv_hostname = parts[0]

        # Parse key=value pairs
        kvs: dict[str, str] = {}
        for part in parts[1:]:
            if "=" in part:
                k, v = part.split("=", 1)
                kvs[k] = v

        alias = kvs.get("ssh_alias", "")
        if not alias:
            continue

        # ssh_user overrides ansible_user
        user = kvs.get("ssh_user", kvs.get("ansible_user", ""))
        hostname = kvs.get("ansible_host", inv_hostname)
        port = int(kvs.get("ansible_port", "22"))

        machine = Machine(
            id=alias,
            name=inv_hostname,
            hostname=hostname,
            user=user,
            port=port,
            groups=[current_group] if current_group else [],
        )
        machines.append(machine)

    return machines
