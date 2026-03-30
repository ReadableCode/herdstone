import asyncio
import json
from typing import Optional

import typer

from .inventory import parse_inventory
from .ping import ping_many, ping_one  # noqa: F401

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
            typer.echo(
                f"  {m.id:<20} ssh {m.user}@{m.hostname}{port_str}  [{', '.join(m.groups)}]"
            )


@app.command()
def ping(
    target: Optional[str] = typer.Argument(None, help="Host alias or name to ping"),
    group: Optional[str] = typer.Option(
        None, "--group", "-g", help="Ping all machines in a group"
    ),
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
        for r in results:
            host = next((m.hostname for m in targets if m.id == r.machine_id), "")
            icon = "✓" if r.exit_code == 0 else "✗"
            status = "online" if r.exit_code == 0 else "offline"
            typer.echo(
                f"  {icon} {r.machine_id:<20} {host:<25} {status}  ({r.duration_ms}ms)"
            )


if __name__ == "__main__":
    app()
