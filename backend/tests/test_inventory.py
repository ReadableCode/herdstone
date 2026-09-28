import json
from pathlib import Path

from engine.inventory import find_machine, parse_inventory


def _write_hosts_json(tmp_path: Path) -> Path:
    inv = tmp_path / "hosts.json"
    inv.write_text(
        json.dumps(
            {
                "hosts": [
                    {
                        "name": "behemoth",
                        "hostname": "192.168.86.31",
                        "user": "root",
                        "os": "linux",
                        "harness": "ssh",
                        "groups": ["unraid"],
                        "aliases": ["sshbehemoth"],
                        "services": [
                            {
                                "type": "sonarr",
                                "name": "sonarr-behemoth",
                                "port": 8989,
                                "api_key_env": "SONARR_BEHEMOTH_API_KEY",
                            }
                        ],
                    },
                    {"name": "AppleTV", "os": "ios", "harness": "none", "groups": ["iOS"]},
                ]
            }
        )
    )
    return inv


def test_parse_hosts_json(tmp_path):
    machines = parse_inventory(_write_hosts_json(tmp_path))
    assert len(machines) == 2

    behemoth = machines[0]
    assert behemoth.id == "behemoth"
    assert behemoth.hostname == "192.168.86.31"
    assert behemoth.user == "root"
    assert behemoth.port == 22
    assert behemoth.os == "linux"
    assert behemoth.harness == "ssh"
    assert behemoth.groups == ["unraid"]
    assert behemoth.aliases == ["sshbehemoth"]
    assert len(behemoth.services) == 1
    assert behemoth.services[0].type == "sonarr"
    assert behemoth.services[0].port == 8989
    assert behemoth.services[0].api_key_env == "SONARR_BEHEMOTH_API_KEY"

    appletv = machines[1]
    assert appletv.harness == "none"
    assert appletv.hostname == "AppleTV"  # defaults to name
    assert appletv.services == []


def test_find_machine_matches_id_name_alias(tmp_path):
    machines = parse_inventory(_write_hosts_json(tmp_path))
    assert find_machine(machines, "behemoth")[0].id == "behemoth"
    assert find_machine(machines, "BEHEMOTH")[0].id == "behemoth"
    assert find_machine(machines, "sshbehemoth")[0].id == "behemoth"
    assert find_machine(machines, "nope") == []


def test_parse_real_inventory():
    """The repo-root hosts.json must parse and contain the media hosts."""
    machines = parse_inventory()
    assert len(machines) > 0
    by_name = {m.name: m for m in machines}
    assert "behemoth" in by_name
    assert any(s.type == "sonarr" for s in by_name["behemoth"].services)
