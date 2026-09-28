import asyncio
import socket
import time
from datetime import datetime, timezone

from readable_utils.ssh_tools import build_ssh_argv

from .models import CommandResult, Machine


def _machine_record(machine: Machine) -> dict:
    """A Machine as the inventory-record dict the shared ssh_tools builder takes."""
    return {
        "name": machine.name,
        "hostname": machine.hostname,
        "user": machine.user,
        "port": machine.port if machine.port != 22 else None,
        "identity_file": machine.identity_file,
        "aliases": machine.aliases,
    }


def command_argv(machine: Machine, command: str) -> list[str]:
    """The full argv that runs command on machine.

    All chain semantics live in readable_utils.ssh_tools (shared with the
    status_board repo): local execution when the target is this host, the
    ``-J`` hop through machine.jump_via (skipped when this machine IS the
    jump host), and identity_file/port handling.
    """
    jump = _machine_record(machine.jump_via) if machine.jump_via else None
    return build_ssh_argv(
        _machine_record(machine), command, jump=jump, local_hostname=socket.gethostname()
    )


async def run_ssh_command(machine: Machine, command: str, timeout: int = 10) -> CommandResult:
    """Run a command on a machine. Uses local exec if target is this host, SSH otherwise."""
    argv = command_argv(machine, command)
    start = time.monotonic()

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
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
            stderr="Command timed out",
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
