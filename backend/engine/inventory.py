import json
from pathlib import Path

from .config import get_inventory_paths
from .models import Machine, Service


def parse_inventory(path: Path | None = None) -> list[Machine]:
    """Load the hosts.json inventory/inventories into a list of Machine objects.

    With an explicit path, only that file loads. Otherwise every discovered
    inventory loads and the herds merge — first definition of a name wins, so
    the search-path order in config.py is the precedence order. Each
    machine's ``jump`` token (name/alias of another machine to hop through)
    is resolved against the merged herd into ``jump_via``.
    """
    paths = [path] if path is not None else get_inventory_paths()
    machines: list[Machine] = []
    seen_names: set[str] = set()
    for inventory_path in paths:
        if not inventory_path.is_file():
            continue
        for machine in _parse_file(inventory_path):
            if machine.name.lower() in seen_names:
                continue
            seen_names.add(machine.name.lower())
            machines.append(machine)
    for machine in machines:
        if machine.jump:
            matches = find_machine(machines, machine.jump)
            machine.jump_via = matches[0] if matches else None
    return machines


def _parse_file(path: Path) -> list[Machine]:
    """Parse one hosts.json file into Machine objects (no jump resolution)."""
    data = json.loads(path.read_text())
    machines: list[Machine] = []

    for entry in data.get("hosts", []):
        name = entry.get("name", "")
        if not name:
            continue

        services = [
            Service(
                type=s.get("type", ""),
                name=s.get("name", ""),
                port=int(s.get("port", 0)),
                scheme=s.get("scheme", "http"),
                base_url=s.get("base_url", ""),
                api_key_env=s.get("api_key_env", ""),
                quality_profile=s.get("quality_profile", ""),
                root_folder=s.get("root_folder", ""),
            )
            for s in entry.get("services", [])
        ]

        machines.append(
            Machine(
                id=entry.get("id", name),
                name=name,
                hostname=entry.get("hostname", name),
                user=entry.get("user", ""),
                port=int(entry.get("port", 22)),
                os=entry.get("os", "other"),
                harness=entry.get("harness", "ssh" if entry.get("user") else "none"),
                groups=list(entry.get("groups", [])),
                aliases=list(entry.get("aliases", [])),
                tags=dict(entry.get("tags", {})),
                identity_file=entry.get("identity_file"),
                jump=entry.get("jump", ""),
                services=services,
            )
        )

    return machines


def find_machine(machines: list[Machine], target: str) -> list[Machine]:
    """Match a target string against machine id, name, or aliases (case-insensitive)."""
    t = target.lower()
    return [m for m in machines if t in (m.id.lower(), m.name.lower()) or t in (a.lower() for a in m.aliases)]
