import typer

app = typer.Typer(name="herdstone", help="Herdstone — machine herd monitor")


@app.command()
def status(json: bool = typer.Option(False, "--json", help="Output as JSON")):
    """List all machines with current status."""
    typer.echo("Not yet implemented")


if __name__ == "__main__":
    app()
