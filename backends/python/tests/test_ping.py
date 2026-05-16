import asyncio

from engine.models import Machine
from engine.ping import ping_many, ping_one


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
