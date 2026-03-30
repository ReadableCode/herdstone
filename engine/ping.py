import asyncio
import platform
import time
from datetime import datetime, timezone

from .models import CommandResult, Machine


async def ping_one(machine: Machine, count: int = 1, timeout: int = 2) -> CommandResult:
    """Ping a single machine using the system ping command."""
    start = time.monotonic()
    is_windows = platform.system().lower() == "windows"
    cmd = [
        "ping",
        "-n" if is_windows else "-c",
        str(count),
        "-w" if is_windows else "-W",
        str(timeout),
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


async def ping_many(machines: list[Machine], count: int = 1, timeout: int = 2) -> list[CommandResult]:
    """Ping multiple machines concurrently."""
    tasks = [ping_one(m, count=count, timeout=timeout) for m in machines]
    return await asyncio.gather(*tasks)
