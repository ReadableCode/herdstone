import asyncio
import platform
import socket
import time
from datetime import datetime, timezone

from .models import CommandResult, Machine


def _is_local(machine: Machine) -> bool:
    """Check if the target machine is the local host (like ansible_connection=local)."""
    hostname = machine.hostname
    if hostname in ("localhost", "127.0.0.1", "::1"):
        return True

    local_hostname = socket.gethostname().lower()
    if hostname.lower() == local_hostname:
        return True
    # handle FQDN vs short name
    if hostname.lower().split(".")[0] == local_hostname.split(".")[0]:
        return True

    # check if hostname resolves to a local address
    try:
        target_ips = {addr[4][0] for addr in socket.getaddrinfo(hostname, None)}
        local_ips = {addr[4][0] for addr in socket.getaddrinfo(socket.gethostname(), None)}
        local_ips.add("127.0.0.1")
        local_ips.add("::1")
        if target_ips & local_ips:
            return True
    except socket.gaierror:
        pass

    return False


async def _run_local_command(machine: Machine, command: str, timeout: int = 10) -> CommandResult:
    """Run a command locally via shell (no SSH)."""
    start = time.monotonic()
    shell = "cmd" if platform.system().lower() == "windows" else "sh"
    flag = "/c" if shell == "cmd" else "-c"

    try:
        proc = await asyncio.create_subprocess_exec(
            shell, flag, command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return CommandResult(
            machine_id=machine.id,
            command=command,
            stdout="",
            stderr="Local command timed out",
            exit_code=-1,
            duration_ms=elapsed_ms,
            timestamp=datetime.now(timezone.utc),
        )

    elapsed_ms = int((time.monotonic() - start) * 1000)
    return CommandResult(
        machine_id=machine.id,
        command=command,
        stdout=stdout_bytes.decode(errors="replace"),
        stderr=stderr_bytes.decode(errors="replace"),
        exit_code=proc.returncode or 0,
        duration_ms=elapsed_ms,
        timestamp=datetime.now(timezone.utc),
    )


async def run_ssh_command(machine: Machine, command: str, timeout: int = 10) -> CommandResult:
    """Run a command on a machine. Uses local exec if target is this host, SSH otherwise."""
    if _is_local(machine):
        return await _run_local_command(machine, command, timeout=timeout)

    start = time.monotonic()

    ssh_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=accept-new"]
    if machine.port != 22:
        ssh_cmd += ["-p", str(machine.port)]
    if machine.identity_file:
        ssh_cmd += ["-i", machine.identity_file]
    ssh_cmd += [f"{machine.user}@{machine.hostname}", command]

    try:
        proc = await asyncio.create_subprocess_exec(
            *ssh_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return CommandResult(
            machine_id=machine.id,
            command=command,
            stdout="",
            stderr="SSH command timed out",
            exit_code=-1,
            duration_ms=elapsed_ms,
            timestamp=datetime.now(timezone.utc),
        )

    elapsed_ms = int((time.monotonic() - start) * 1000)
    return CommandResult(
        machine_id=machine.id,
        command=command,
        stdout=stdout_bytes.decode(errors="replace"),
        stderr=stderr_bytes.decode(errors="replace"),
        exit_code=proc.returncode or 0,
        duration_ms=elapsed_ms,
        timestamp=datetime.now(timezone.utc),
    )


async def run_ssh_command_many(machines: list[Machine], command: str, timeout: int = 10) -> list[CommandResult]:
    """Run the same command on multiple machines concurrently."""
    tasks = [run_ssh_command(m, command, timeout=timeout) for m in machines]
    return await asyncio.gather(*tasks)
