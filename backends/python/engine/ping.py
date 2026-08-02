import asyncio
import platform
import time
from datetime import datetime, timezone

from .models import CommandResult, Machine


async def _icmp_ping(machine: Machine, count: int, timeout: int) -> CommandResult:
    """Ping a machine once using the system ping command."""
    start = time.monotonic()
    is_windows = platform.system().lower() == "windows"
    timeout_arg = str(timeout * 1000) if is_windows else str(timeout)
    cmd = [
        "ping",
        "-n" if is_windows else "-c",
        str(count),
        "-w" if is_windows else "-W",
        timeout_arg,
        machine.hostname,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    elapsed_ms = int((time.monotonic() - start) * 1000)

    return CommandResult(
        machine_id=machine.id,
        command=" ".join(cmd),
        stdout=stdout_bytes.decode(errors="replace"),
        stderr=stderr_bytes.decode(errors="replace"),
        exit_code=proc.returncode or 0,
        duration_ms=elapsed_ms,
        timestamp=datetime.now(timezone.utc),
    )


async def _tcp_probe(machine: Machine, timeout: int) -> CommandResult:
    """Reachability via a TCP connect to the machine's ssh port.

    Windows blocks inbound ICMP by default while sshd answers fine, so for
    ssh-harness hosts an open ssh port is just as good a liveness signal as
    an echo reply. Nothing is sent on the connection; it is closed as soon
    as the handshake completes.
    """
    start = time.monotonic()
    command = f"tcp connect {machine.hostname}:{machine.port}"
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(machine.hostname, machine.port), timeout=timeout
        )
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass  # the port answered; a messy close is still "online"
        stdout, stderr, exit_code = f"port {machine.port} open", "", 0
    except (OSError, asyncio.TimeoutError) as error:
        stdout, stderr, exit_code = "", str(error) or "connect timed out", 1
    elapsed_ms = int((time.monotonic() - start) * 1000)

    return CommandResult(
        machine_id=machine.id,
        command=command,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        duration_ms=elapsed_ms,
        timestamp=datetime.now(timezone.utc),
    )


async def ping_one(machine: Machine, count: int = 1, timeout: int = 2) -> CommandResult:
    """Reachability check for one machine: ICMP ping, falling back to a TCP
    probe of the ssh port for ssh-harness hosts (Windows commonly blocks
    ICMP while sshd answers). The returned command field says which method
    decided the result."""
    result = await _icmp_ping(machine, count, timeout)
    if result.exit_code == 0 or machine.harness != "ssh":
        return result
    return await _tcp_probe(machine, timeout)


async def ping_many(
    machines: list[Machine], count: int = 1, timeout: int = 2
) -> list[CommandResult]:
    """Ping multiple machines concurrently."""
    tasks = [ping_one(m, count=count, timeout=timeout) for m in machines]
    return await asyncio.gather(*tasks)
