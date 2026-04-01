import asyncio
import json
from typing import Optional

import typer

from .inventory import parse_inventory
from .ping import ping_many, ping_one  # noqa: F401
from .storage import get_storage_many

app = typer.Typer(name="herdstone", help="Herdstone — machine herd monitor")


def _resolve_targets(
    target: Optional[str] = None,
    group: Optional[str] = None,
    all_hosts: bool = False,
) -> list:
    """Resolve a target host, group, or --all into a list of machines."""
    machines = parse_inventory()
    if not machines:
        typer.echo("No inventory file found or no hosts with ssh_alias.")
        raise typer.Exit(1)

    if all_hosts:
        return machines

    if group:
        matched = [m for m in machines if group in m.groups]
        if not matched:
            typer.echo(f"No machines found in group '{group}'.")
            raise typer.Exit(1)
        return matched

    if target:
        matched = [m for m in machines if m.id == target or m.name == target]
        if not matched:
            typer.echo(f"Machine '{target}' not found.")
            raise typer.Exit(1)
        return matched

    typer.echo("Specify a target host, --group, or --all.")
    raise typer.Exit(1)


@app.command()
def status(output_json: bool = typer.Option(False, "--json", help="Output as JSON")):
    """List all machines with current status."""
    typer.echo("Not yet implemented")


@app.command()
def hosts(output_json: bool = typer.Option(False, "--json", help="Output as JSON")):
    """List all hosts from the inventory."""
    machines = parse_inventory()
    if not machines:
        typer.echo("No inventory file found or no hosts with ssh_alias.")
        raise typer.Exit(1)

    if output_json:
        data = [
            {
                "id": m.id,
                "name": m.name,
                "hostname": m.hostname,
                "user": m.user,
                "port": m.port,
                "groups": m.groups,
            }
            for m in machines
        ]
        typer.echo(json.dumps(data, indent=2))
    else:
        for m in machines:
            port_str = f" -p {m.port}" if m.port != 22 else ""
            typer.echo(f"  {m.id:<20} ssh {m.user}@{m.hostname}{port_str}  [{', '.join(m.groups)}]")


@app.command()
def ping(
    target: Optional[str] = typer.Argument(None, help="Host alias or name to ping"),
    group: Optional[str] = typer.Option(None, "--group", "-g", help="Ping all machines in a group"),
    all_hosts: bool = typer.Option(False, "--all", "-a", help="Ping all machines"),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Ping one machine, a group, or all machines concurrently."""
    targets = _resolve_targets(target=target, group=group, all_hosts=all_hosts)
    results = asyncio.run(ping_many(targets))

    if output_json:
        data = [
            {
                "machine_id": r.machine_id,
                "host": next((m.hostname for m in targets if m.id == r.machine_id), ""),
                "reachable": r.exit_code == 0,
                "duration_ms": r.duration_ms,
                "exit_code": r.exit_code,
            }
            for r in results
        ]
        typer.echo(json.dumps(data, indent=2))
    else:
        name_map = {m.id: m.name for m in targets}
        for r in results:
            host = next((m.hostname for m in targets if m.id == r.machine_id), "")
            name = name_map.get(r.machine_id, r.machine_id)
            icon = "✓" if r.exit_code == 0 else "✗"
            status = "online" if r.exit_code == 0 else "offline"
            typer.echo(f"  {icon} {name:<20} {host:<25} {status}  ({r.duration_ms}ms)")


def _fmt_bytes(n: int) -> str:
    """Format bytes as human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


@app.command()
def storage(
    target: Optional[str] = typer.Argument(None, help="Host alias or name"),
    group: Optional[str] = typer.Option(None, "--group", "-g", help="Query all machines in a group"),
    all_hosts: bool = typer.Option(False, "--all", "-a", help="Query all machines"),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show storage/disk usage for one machine, a group, or all machines."""
    targets = _resolve_targets(target=target, group=group, all_hosts=all_hosts)
    results = asyncio.run(get_storage_many(targets))

    if output_json:
        data = {}
        for machine_id, drives in results.items():
            data[machine_id] = [
                {
                    "filesystem": d.filesystem,
                    "mount_point": d.mount_point,
                    "size_bytes": d.size_bytes,
                    "used_bytes": d.used_bytes,
                    "avail_bytes": d.avail_bytes,
                    "use_percent": d.use_percent,
                }
                for d in drives
            ]
        typer.echo(json.dumps(data, indent=2))
    else:
        name_map = {m.id: m.name for m in targets}
        for machine_id, drives in results.items():
            name = name_map.get(machine_id, machine_id)
            if not drives:
                typer.echo(f"  ✗ {name:<20} no data (unreachable or SSH failed)")
                continue
            for i, d in enumerate(drives):
                prefix = f"  {name:<20}" if i == 0 else f"  {'':<20}"
                bar_len = 20
                filled = int(bar_len * d.use_percent / 100)
                bar = "█" * filled + "░" * (bar_len - filled)
                typer.echo(
                    f"{prefix} {d.mount_point:<20} [{bar}] {d.use_percent:5.1f}%  "
                    f"{_fmt_bytes(d.used_bytes)} / {_fmt_bytes(d.size_bytes)}"
                )


if __name__ == "__main__":
    app()
