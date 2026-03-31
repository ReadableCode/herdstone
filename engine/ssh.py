import asyncio
import time
from datetime import datetime, timezone

from .models import CommandResult, Machine


async def run_ssh_command(machine: Machine, command: str, timeout: int = 10) -> CommandResult:
    """Run a command on a remote machine via SSH subprocess."""
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
