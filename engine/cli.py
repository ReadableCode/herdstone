import json

import typer

from .inventory import parse_inventory

app = typer.Typer(name="herdstone", help="Herdstone — machine herd monitor")


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


if __name__ == "__main__":
    app()
