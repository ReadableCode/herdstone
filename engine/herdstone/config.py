from pathlib import Path

# Default paths
DEFAULT_INVENTORY_FILENAME = "herdstone_inventory.yaml"


def get_config_dir() -> Path:
    config_dir = Path.home() / ".config" / "herdstone"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_inventory_path() -> Path:
    return get_config_dir() / DEFAULT_INVENTORY_FILENAME
