import asyncio
import json
import os
from typing import Optional

import typer

from .inventory import find_machine, machines_to_json, parse_ansible_ini, parse_inventory
from .media.cli import media_app
from .ping import ping_many, ping_one  # noqa: F401
from .storage import get_storage_many

app = typer.Typer(name="herdstone", help="Herdstone — machine herd monitor")
app.add_typer(media_app)


@app.command()
def tui():
    """Launch the media remote TUI (Textual)."""
    from .tui.app import run_tui

    run_tui()


@app.command()
def web(
    host: str = typer.Option("127.0.0.1", "--host", help="Interface to bind (use your Tailscale IP to share)"),
    port: int = typer.Option(8787, "--port", help="Port to listen on"),
):
    """Launch the media remote web UI (NiceGUI)."""
    from .web.app import run_web

    run_web(host=host, port=port)


def _resolve_targets(
    target: Optional[str] = None,
    group: Optional[str] = None,
    all_hosts: bool = False,
    reachable_only: bool = True,
) -> list:
    """Resolve a target host, group, or --all into a list of machines.

    For group/--all selections, hosts with harness "none" are excluded when
    reachable_only is set (they have nothing to ping or SSH to).
    """
    machines = parse_inventory()
    if not machines:
        typer.echo("No inventory found. Expected hosts.json (see README) or HERDSTONE_HOSTS.")
        raise typer.Exit(1)

    if all_hosts:
        return [m for m in machines if m.harness != "none"] if reachable_only else machines

    if group:
        matched = [m for m in machines if group in m.groups]
        if reachable_only:
            matched = [m for m in matched if m.harness != "none"]
        if not matched:
            typer.echo(f"No machines found in group '{group}'.")
            raise typer.Exit(1)
        return matched

    if target:
        matched = find_machine(machines, target)
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
        typer.echo("No inventory found. Expected hosts.json (see README) or HERDSTONE_HOSTS.")
        raise typer.Exit(1)

    if output_json:
        data = [
            {
                "id": m.id,
                "name": m.name,
                "hostname": m.hostname,
                "user": m.user,
                "port": m.port,
                "os": m.os,
                "harness": m.harness,
                "groups": m.groups,
                "aliases": m.aliases,
                "services": [{"type": s.type, "name": s.name, "port": s.port} for s in m.services],
            }
            for m in machines
        ]
        typer.echo(json.dumps(data, indent=2))
    else:
        for m in machines:
            if m.harness == "ssh":
                port_str = f" -p {m.port}" if m.port != 22 else ""
                conn = f"ssh {m.user}@{m.hostname}{port_str}"
            else:
                conn = f"{m.harness}: {m.hostname}" if m.harness != "none" else "(no harness)"
            svc = f"  {{{', '.join(s.name for s in m.services)}}}" if m.services else ""
            typer.echo(f"  {m.name:<22} {conn:<45} [{', '.join(m.groups)}]{svc}")


@app.command("import-ansible")
def import_ansible(
    path: str = typer.Argument(..., help="Path to an Ansible INI inventory file"),
    output: str = typer.Option("hosts.json", "--output", "-o", help="Where to write the JSON inventory"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite the output file if it exists"),
):
    """Convert an Ansible INI inventory into a hosts.json inventory."""
    from pathlib import Path

    src = Path(path).expanduser()
    if not src.is_file():
        typer.echo(f"Inventory file not found: {src}")
        raise typer.Exit(1)

    dest = Path(output).expanduser()
    if dest.exists() and not force:
        typer.echo(f"{dest} already exists — use --force to overwrite.")
        raise typer.Exit(1)

    machines = parse_ansible_ini(src)
    dest.write_text(machines_to_json(machines) + "\n")
    typer.echo(f"Wrote {len(machines)} hosts to {dest}")


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
        for r in results:
            host = next((m.hostname for m in targets if m.id == r.machine_id), "")
            icon = "✓" if r.exit_code == 0 else "✗"
            status = "online" if r.exit_code == 0 else "offline"
            typer.echo(f"  {icon} {r.machine_id:<20} {host:<25} {status}  ({r.duration_ms}ms)")


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


def get_local_public_key(key_path: str = ""):
    """Read the local public SSH key from the specified path."""
    if not key_path:
        key_path = os.path.expanduser("~/.ssh/id_rsa.pub")

    if not os.path.exists(key_path):
        typer.echo(f"Public SSH key not found at: {key_path}")
        raise typer.Exit(1)

    with open(key_path, "r") as f:
        return f.read().strip()


@app.command()
def push_key(
    target: str = typer.Argument(..., help="Host alias or name to push SSH key to"),
    key_path: str = typer.Option("~/.ssh/id_rsa.pub", "--key", "-k", help="Path to public SSH key"),
    auth_keys_path: str = typer.Option(
        "", "--auth-keys", "-a", help="Remote authorized_keys path (default: OS-appropriate)"
    ),
):
    """Push your public SSH key to a target machine's authorized_keys."""
    targets = _resolve_targets(target=target)
    if len(targets) > 1:
        typer.echo("Multiple machines matched. Please specify a unique target.")
        raise typer.Exit(1)
    machine = targets[0]

    target_is_windows = machine.os == "windows"

    if not auth_keys_path:
        if target_is_windows:
            auth_keys_path = f"C:\\Users\\{machine.user}\\.ssh\\authorized_keys"
        else:
            auth_keys_path = "~/.ssh/authorized_keys"

    key_path = os.path.expanduser(key_path)

    print(f"Pushing SSH key to {machine.name} ({machine.hostname})...")
    local_key = get_local_public_key(key_path)

    client_is_posix = os.name == "posix"

    # ssh-copy-id is client-side and only available on POSIX; it also only
    # works when the remote uses the default ~/.ssh/authorized_keys path.
    use_ssh_copy_id = client_is_posix and not target_is_windows and auth_keys_path == "~/.ssh/authorized_keys"

    if use_ssh_copy_id:
        import subprocess

        ssh_cmd = [
            "ssh-copy-id",
            "-i",
            key_path,
            f"{machine.user}@{machine.hostname}",
        ]
        if machine.port != 22:
            ssh_cmd.insert(1, "-p")
            ssh_cmd.insert(2, str(machine.port))
        try:
            subprocess.run(ssh_cmd, check=True)
            print("SSH key pushed successfully.")
        except subprocess.CalledProcessError as e:
            print(f"Failed to push SSH key: {e}")
    else:
        import paramiko

        password = typer.prompt(f"Password for {machine.user}@{machine.hostname}", hide_input=True)

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(machine.hostname, username=machine.user, port=machine.port, password=password)

            # Ensure .ssh dir exists, then append key if not already present
            if target_is_windows:
                # Windows OpenSSH uses a different file for admin users
                if not auth_keys_path or auth_keys_path == f"C:\\Users\\{machine.user}\\.ssh\\authorized_keys":
                    # Check if user is in Administrators group
                    _, stdout_admin, _ = ssh.exec_command("net localgroup Administrators")
                    stdout_admin.channel.recv_exit_status()
                    admin_output = stdout_admin.read().decode()
                    if (
                        machine.user.lower() in admin_output.lower()
                        or machine.user.split("\\")[-1].lower() in admin_output.lower()
                    ):
                        auth_keys_path = "C:\\ProgramData\\ssh\\administrators_authorized_keys"
                        print(f"User is admin — using {auth_keys_path}")

                # Use SFTP to read/write — Windows echo mangles SSH keys
                sftp = ssh.open_sftp()
                try:
                    existing = sftp.open(auth_keys_path, "r").read().decode()
                except FileNotFoundError:
                    existing = ""
                    # Ensure directory exists
                    ssh_dir = auth_keys_path.rsplit("\\", 1)[0]
                    _, stdout_mk, _ = ssh.exec_command(f'if not exist "{ssh_dir}" mkdir "{ssh_dir}"')
                    stdout_mk.channel.recv_exit_status()

                if local_key in existing:
                    print("SSH key already present on target.")
                else:
                    new_content = (
                        existing.rstrip("\r\n") + "\n" + local_key + "\n" if existing.strip() else local_key + "\n"
                    )
                    with sftp.open(auth_keys_path, "w") as f:
                        f.write(new_content)
                    print("SSH key pushed successfully.")
                sftp.close()
            else:
                ssh_dir = os.path.dirname(auth_keys_path) if auth_keys_path != "~/.ssh/authorized_keys" else "~/.ssh"
                check_cmd = f"grep -qxF '{local_key}' {auth_keys_path} 2>/dev/null"
                mkdir_cmd = f"mkdir -p {ssh_dir} && chmod 700 {ssh_dir}"
                append_cmd = f"echo '{local_key}' >> {auth_keys_path} && chmod 600 {auth_keys_path}"

                # Create directory
                _, stdout_mk, stderr_mk = ssh.exec_command(mkdir_cmd)
                stdout_mk.channel.recv_exit_status()

                # Check if key already exists
                _, stdout, _ = ssh.exec_command(check_cmd)
                if stdout.channel.recv_exit_status() == 0:
                    print("SSH key already present on target.")
                else:
                    _, stdout_ap, stderr_ap = ssh.exec_command(append_cmd)
                    exit_code = stdout_ap.channel.recv_exit_status()
                    if exit_code != 0:
                        err = stderr_ap.read().decode().strip()
                        print(f"Failed to append key (exit {exit_code}): {err}")
                    else:
                        print("SSH key pushed successfully.")
        except Exception as e:
            print(f"Failed to push SSH key: {e}")
        finally:
            ssh.close()


if __name__ == "__main__":
    app()
