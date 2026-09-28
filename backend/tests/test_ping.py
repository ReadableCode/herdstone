import asyncio
from datetime import datetime, timezone

import engine.ping as ping_module
from engine.models import CommandResult, Machine
from engine.ping import ping_many, ping_one


def _failed_icmp(machine, count, timeout):
    async def fake():
        return CommandResult(
            machine_id=machine.id, command="ping (blocked)", stdout="", stderr="timeout",
            exit_code=1, duration_ms=1, timestamp=datetime.now(timezone.utc),
        )
    return fake()


def test_ping_falls_back_to_tcp_when_icmp_blocked(monkeypatch):
    """Windows blocks ICMP by default - an answering ssh port still means online."""
    monkeypatch.setattr(ping_module, "_icmp_ping", _failed_icmp)

    async def scenario():
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        machine = Machine(id="winbox", name="winbox", hostname="127.0.0.1", user="me",
                          port=port, harness="ssh")
        async with server:
            return await ping_one(machine)

    result = asyncio.run(scenario())
    assert result.exit_code == 0
    assert result.command.startswith("tcp connect")


def test_ping_tcp_fallback_offline_when_port_closed(monkeypatch):
    monkeypatch.setattr(ping_module, "_icmp_ping", _failed_icmp)

    async def scenario():
        # grab an ephemeral port, then close the server so nothing listens on it
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        server.close()
        await server.wait_closed()
        machine = Machine(id="downbox", name="downbox", hostname="127.0.0.1", user="me",
                          port=port, harness="ssh")
        return await ping_one(machine)

    result = asyncio.run(scenario())
    assert result.exit_code != 0


def test_ping_no_tcp_fallback_for_non_ssh_harness(monkeypatch):
    monkeypatch.setattr(ping_module, "_icmp_ping", _failed_icmp)
    machine = Machine(id="iot", name="iot", hostname="127.0.0.1", user="", harness="ping")
    result = asyncio.run(ping_one(machine))
    assert result.exit_code != 0
    assert result.command == "ping (blocked)"


def test_ping_one():
    machine = Machine(id="localhost", name="Localhost", hostname="127.0.0.1", user="tester")
    result = asyncio.run(ping_one(machine))
    print(f"Ping result for {machine.hostname}:")
    print(f"  machine_id: {result.machine_id}")
    print(f"  Command: {result.command}")
    print(f"  Exit Code: {result.exit_code}")
    print(f"  Stdout: {result.stdout.strip()}")
    print(f"  Stderr: {result.stderr.strip()}")
    print(f"  Duration: {result.duration_ms} ms")
    print(f"  Timestamp: {result.timestamp.isoformat()}")
    assert result.exit_code == 0, "Expected ping to localhost to succeed"


def test_ping_many():
    machines = [Machine(id="localhost", name="Localhost", hostname="127.0.0.1", user="tester")]
    results = asyncio.run(ping_many(machines))
    assert len(results) == 1, "Expected one result"
    result = results[0]
    print(f"Ping result for {machines[0].hostname}:")
    print(f"  machine_id: {result.machine_id}")
    print(f"  Command: {result.command}")
    print(f"  Exit Code: {result.exit_code}")
    print(f"  Stdout: {result.stdout.strip()}")
    print(f"  Stderr: {result.stderr.strip()}")
    print(f"  Duration: {result.duration_ms} ms")
    print(f"  Timestamp: {result.timestamp.isoformat()}")
    assert result.exit_code == 0, "Expected ping to localhost to succeed"


if __name__ == "__main__":
    test_ping_one()
    test_ping_many()
    print("All ping tests passed.")
