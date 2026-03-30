import json
from pathlib import Path
from textwrap import dedent

from typer.testing import CliRunner

from engine.cli import app

runner = CliRunner()


def _write_test_inventory(tmp_path: Path) -> Path:
    inv = tmp_path / "hosts"
    inv.write_text(dedent("""\
        [test_group]
        localhost ansible_host=127.0.0.1 ansible_user=tester ssh_alias=sshlocal
    """))
    return inv


def test_ping_all(tmp_path, monkeypatch):
    inv = _write_test_inventory(tmp_path)
    monkeypatch.setattr("engine.config.INVENTORY_SEARCH_PATH", [inv])
    result = runner.invoke(app, ["ping", "--all"])
    assert result.exit_code == 0
    assert "sshlocal" in result.output
    assert "✓" in result.output
    assert "online" in result.output


def test_ping_all_json(tmp_path, monkeypatch):
    inv = _write_test_inventory(tmp_path)
    monkeypatch.setattr("engine.config.INVENTORY_SEARCH_PATH", [inv])
    result = runner.invoke(app, ["ping", "--all", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["machine_id"] == "sshlocal"
    assert data[0]["reachable"] is True


def test_ping_group(tmp_path, monkeypatch):
    inv = _write_test_inventory(tmp_path)
    monkeypatch.setattr("engine.config.INVENTORY_SEARCH_PATH", [inv])
    result = runner.invoke(app, ["ping", "--group", "test_group"])
    assert result.exit_code == 0
    assert "sshlocal" in result.output


def test_ping_single_target(tmp_path, monkeypatch):
    inv = _write_test_inventory(tmp_path)
    monkeypatch.setattr("engine.config.INVENTORY_SEARCH_PATH", [inv])
    result = runner.invoke(app, ["ping", "sshlocal"])
    assert result.exit_code == 0
    assert "sshlocal" in result.output


def test_ping_unknown_target(tmp_path, monkeypatch):
    inv = _write_test_inventory(tmp_path)
    monkeypatch.setattr("engine.config.INVENTORY_SEARCH_PATH", [inv])
    result = runner.invoke(app, ["ping", "nonexistent"])
    assert result.exit_code == 1


def test_ping_unknown_group(tmp_path, monkeypatch):
    inv = _write_test_inventory(tmp_path)
    monkeypatch.setattr("engine.config.INVENTORY_SEARCH_PATH", [inv])
    result = runner.invoke(app, ["ping", "--group", "nonexistent"])
    assert result.exit_code == 1

