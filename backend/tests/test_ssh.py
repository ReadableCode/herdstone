import json
from pathlib import Path

from engine.inventory import parse_inventory
from engine.ssh import command_argv


def _write_jump_inventory(tmp_path: Path) -> Path:
    inv = tmp_path / "hosts.json"
    inv.write_text(
        json.dumps(
            {
                "hosts": [
                    {"name": "gateway", "hostname": "10.0.0.1", "user": "jgate", "port": 2222,
                     "aliases": ["sshgate"]},
                    {"name": "inner-vm", "hostname": "10.0.0.20", "user": "svc", "harness": "ssh",
                     "jump": "sshgate", "identity_file": "~/.ssh/id_inner"},
                ]
            }
        )
    )
    return inv


def test_jump_resolves_and_builds_proxy_argv(tmp_path):
    machines = parse_inventory(_write_jump_inventory(tmp_path))
    inner = next(m for m in machines if m.name == "inner-vm")
    assert inner.jump == "sshgate"
    assert inner.jump_via is not None and inner.jump_via.name == "gateway"

    argv = command_argv(inner, "uptime")
    assert argv[0] == "ssh"
    assert argv[argv.index("-J") + 1] == "jgate@10.0.0.1:2222"
    assert "-i" in argv
    assert argv[-2:] == ["svc@10.0.0.20", "uptime"]


def test_local_target_short_circuits_to_shell(tmp_path):
    inv = tmp_path / "hosts.json"
    inv.write_text(json.dumps({"hosts": [{"name": "self", "hostname": "127.0.0.1", "user": "me"}]}))
    machines = parse_inventory(inv)
    argv = command_argv(machines[0], "uptime")
    assert argv[0] != "ssh"
    assert argv[-1] == "uptime"
