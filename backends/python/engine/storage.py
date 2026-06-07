import asyncio
from dataclasses import dataclass

from .models import Machine
from .ssh import run_ssh_command

# Map inventory groups to OS families
WINDOWS_GROUPS = {"windows_workstations", "hellofresh_windows", "rebeca_windows", "crown_windows"}
UNIX_GROUPS = {
    "linux_workstations",
    "macs",
    "work_linux",
    "fourteen_foods",
    "unraid",
    "raspbian",
    "android",
    "ginamary",
}


@dataclass
class DriveInfo:
    machine_id: str
    filesystem: str
    mount_point: str
    size_bytes: int
    used_bytes: int
    avail_bytes: int
    use_percent: float


def _get_os_family(machine: Machine) -> str:
    """Infer OS family from inventory group membership."""
    for group in machine.groups:
        if group in WINDOWS_GROUPS:
            return "windows"
        if group in UNIX_GROUPS:
            return "unix"
    return "unix"


def _parse_df_output(machine_id: str, stdout: str) -> list[DriveInfo]:
    """Parse POSIX df -Pk output into DriveInfo list."""
    drives: list[DriveInfo] = []
    lines = stdout.strip().splitlines()
    if len(lines) < 2:
        return drives

    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue

        filesystem = parts[0]
        mount_point = " ".join(parts[5:])

        # Skip pseudo/virtual filesystems
        if filesystem in ("tmpfs", "devtmpfs", "overlay", "shm", "none"):
            continue
        if mount_point.startswith(("/dev", "/sys", "/proc", "/run", "/snap")):
            continue

        try:
            size_kb = int(parts[1])
            used_kb = int(parts[2])
            avail_kb = int(parts[3])
            pct_str = parts[4].rstrip("%")
            use_pct = float(pct_str)
        except (ValueError, IndexError):
            continue

        drives.append(
            DriveInfo(
                machine_id=machine_id,
                filesystem=filesystem,
                mount_point=mount_point,
                size_bytes=size_kb * 1024,
                used_bytes=used_kb * 1024,
                avail_bytes=avail_kb * 1024,
                use_percent=use_pct,
            )
        )

    return drives


def _parse_powershell_output(machine_id: str, stdout: str) -> list[DriveInfo]:
    """Parse PowerShell Get-PSDrive JSON output into DriveInfo list."""
    import json

    drives: list[DriveInfo] = []
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return drives

    if isinstance(data, dict):
        data = [data]

    for entry in data:
        name = entry.get("Name", "?")
        used = entry.get("Used", 0) or 0
        free = entry.get("Free", 0) or 0
        size = used + free
        if size == 0:
            continue

        drives.append(
            DriveInfo(
                machine_id=machine_id,
                filesystem=f"{name}:",
                mount_point=f"{name}:\\",
                size_bytes=int(size),
                used_bytes=int(used),
                avail_bytes=int(free),
                use_percent=round((used / size) * 100, 1) if size else 0.0,
            )
        )

    return drives


async def get_storage_one(machine: Machine, timeout: int = 10) -> list[DriveInfo]:
    """Get storage info for a single machine."""
    os_family = _get_os_family(machine)

    if os_family == "windows":
        cmd = 'powershell -Command "Get-PSDrive -PSProvider FileSystem | Select-Object Name,Used,Free | ConvertTo-Json"'
        result = await run_ssh_command(machine, cmd, timeout=timeout)
        if result.exit_code != 0:
            return []
        return _parse_powershell_output(machine.id, result.stdout)
    else:
        result = await run_ssh_command(machine, "df -Pk", timeout=timeout)
        if result.exit_code != 0:
            return []
        return _parse_df_output(machine.id, result.stdout)


async def get_storage_many(machines: list[Machine], timeout: int = 10) -> dict[str, list[DriveInfo]]:
    """Get storage info for multiple machines concurrently.

    Returns a dict mapping machine_id -> list of DriveInfo.
    Machines that fail or are unreachable will have an empty list.
    """
    tasks = [get_storage_one(m, timeout=timeout) for m in machines]
    results = await asyncio.gather(*tasks)
    return {m.id: drives for m, drives in zip(machines, results)}
