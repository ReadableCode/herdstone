from pathlib import Path

# Inventory search path — first match wins
INVENTORY_SEARCH_PATH = [
    Path(__file__).resolve().parent.parent.parent.parent.parent / "dotfiles" / "inventory" / "hosts",
    Path.home() / "hosts",
    Path.home() / "herdstone_hosts",
]


def get_inventory_path() -> Path | None:
    for path in INVENTORY_SEARCH_PATH:
        if path.is_file():
            return path
    return None
