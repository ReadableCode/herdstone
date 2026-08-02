"""Host stats (disk / cpu / mem) via the shared @@STATS@@ one-liner probe.

The probe command and its parser live in readable_utils.host_stats_tools
(shared with the status_board repo): the remote host emits one
machine-readable line from numbers the kernel already maintains, and all
rendering happens locally. Linux hosts only.
"""

import asyncio

from readable_utils.host_stats_tools import HOST_STATS_COMMAND, parse_host_stats

from .models import Machine
from .ssh import run_ssh_command


async def get_stats_one(machine: Machine, timeout: int = 10) -> dict | None:
    """Fetch and parse one machine's stats line, or None (non-Linux, unreachable, garbled)."""
    if machine.os != "linux":
        return None
    result = await run_ssh_command(machine, HOST_STATS_COMMAND, timeout=timeout)
    if result.exit_code != 0 or not result.stdout.strip():
        return None
    return parse_host_stats(result.stdout.strip().splitlines()[-1])


async def get_stats_many(machines: list[Machine], timeout: int = 10) -> dict[str, dict | None]:
    """Fetch stats for multiple machines concurrently: machine_id -> stats dict or None."""
    tasks = [get_stats_one(m, timeout=timeout) for m in machines]
    results = await asyncio.gather(*tasks)
    return {m.id: stats for m, stats in zip(machines, results)}
