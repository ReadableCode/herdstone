import json
from pathlib import Path

from typer.testing import CliRunner

from engine.cli import app

runner = CliRunner()


def _write_test_inventory(tmp_path: Path) -> Path:
    inv = tmp_path / "hosts.json"
    inv.write_text(
        json.dumps(
            {
                "hosts": [
                    {
                        "name": "localhost",
                        "hostname": "127.0.0.1",
                        "user": "tester",
                        "os": "linux",
                        "harness": "ssh",
                        "groups": ["test_group"],
                        "aliases": ["sshlocal"],
                    },
                    {"name": "unreachable-thing", "os": "other", "harness": "none", "groups": ["test_group"]},
                ]
            }
        )
    )
    return inv


def _use_inventory(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("HERDSTONE_HOSTS", raising=False)
    monkeypatch.setattr("engine.config.INVENTORY_SEARCH_PATH", [_write_test_inventory(tmp_path)])


def test_cli_surface():
    """Media commands moved to Sync_Plex — only herd commands remain."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "media" not in result.output
    for command in ("hosts", "ping", "storage", "push-key", "import-ansible", "tui", "web"):
        assert command in result.output


def test_tui_app_constructs():
    from engine.tui.app import HerdMonitor, run_tui  # noqa: F401

    assert HerdMonitor().TITLE == "❯ herdstone"


def test_web_app_importable():
    from engine.web.app import _TOKENS_CSS, run_web  # noqa: F401

    assert "--green-bright" in _TOKENS_CSS


def test_hosts(tmp_path, monkeypatch):
    _use_inventory(tmp_path, monkeypatch)
    result = runner.invoke(app, ["hosts"])
    assert result.exit_code == 0
    assert "localhost" in result.output
    assert "unreachable-thing" in result.output


def test_ping_all_skips_harness_none(tmp_path, monkeypatch):
    _use_inventory(tmp_path, monkeypatch)
    result = runner.invoke(app, ["ping", "--all"])
    assert result.exit_code == 0
    assert "localhost" in result.output
    assert "✓" in result.output
    assert "online" in result.output
    assert "unreachable-thing" not in result.output


def test_ping_all_json(tmp_path, monkeypatch):
    _use_inventory(tmp_path, monkeypatch)
    result = runner.invoke(app, ["ping", "--all", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["machine_id"] == "localhost"
    assert data[0]["reachable"] is True


def test_ping_group(tmp_path, monkeypatch):
    _use_inventory(tmp_path, monkeypatch)
    result = runner.invoke(app, ["ping", "--group", "test_group"])
    assert result.exit_code == 0
    assert "localhost" in result.output


def test_ping_single_target_by_alias(tmp_path, monkeypatch):
    _use_inventory(tmp_path, monkeypatch)
    result = runner.invoke(app, ["ping", "sshlocal"])
    assert result.exit_code == 0
    assert "localhost" in result.output


def test_ping_unknown_target(tmp_path, monkeypatch):
    _use_inventory(tmp_path, monkeypatch)
    result = runner.invoke(app, ["ping", "nonexistent"])
    assert result.exit_code == 1


def test_ping_unknown_group(tmp_path, monkeypatch):
    _use_inventory(tmp_path, monkeypatch)
    result = runner.invoke(app, ["ping", "--group", "nonexistent"])
    assert result.exit_code == 1


def test_import_ansible(tmp_path, monkeypatch):
    ini = tmp_path / "ansible_hosts"
    ini.write_text("[macs]\nMacBookPro12 ansible_user=jason ssh_alias=sshmac\n")
    out = tmp_path / "converted.json"
    result = runner.invoke(app, ["import-ansible", str(ini), "-o", str(out)])
    assert result.exit_code == 0
    data = json.loads(out.read_text())
    assert data["hosts"][0]["name"] == "MacBookPro12"
    assert data["hosts"][0]["aliases"] == ["sshmac"]
