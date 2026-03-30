from engine.inventory import parse_inventory


def test_parse_real_inventory():
    machines = parse_inventory()

    # Print all discovered hosts for verification
    print(f"\n{'='*60}")
    print(f"Found {len(machines)} hosts with ssh_alias:")
    print(f"{'='*60}")
    for m in machines:
        port_str = f" -p {m.port}" if m.port != 22 else ""
        print(f"  {m.id:<20} -> ssh {m.user}@{m.hostname}{port_str}  [{m.groups[0]}]")
    print(f"{'='*60}\n")

    # Must find at least one host
    assert len(machines) > 0, "Expected at least one host in inventory"

    # Verify first host has required fields populated
    first = machines[0]
    assert first.id, "id (ssh_alias) must not be empty"
    assert first.name, "name (inventory hostname) must not be empty"
    assert first.hostname, "hostname must not be empty"
    assert first.user, "user must not be empty"
    assert first.port > 0, "port must be positive"
    assert len(first.groups) > 0, "must belong to at least one group"
