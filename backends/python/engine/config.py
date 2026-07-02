import os
from pathlib import Path

# Repo root (this file is backends/python/engine/config.py). In shallower
# layouts (e.g. the docker image, where the package sits at /app/engine) the
# repo-relative paths don't exist — fall back to the package's parent dir and
# rely on HERDSTONE_HOSTS / the container environment instead.
try:
    REPO_ROOT = Path(__file__).resolve().parents[3]
except IndexError:
    REPO_ROOT = Path(__file__).resolve().parents[1]

# Inventory search path — first match wins. HERDSTONE_HOSTS env var overrides.
# Canonical copy lives in the dotfiles repo (assumed checked out beside this one),
# next to the Ansible INI it was converted from.
INVENTORY_SEARCH_PATH = [
    REPO_ROOT.parent / "dotfiles" / "inventory" / "hosts.json",
    REPO_ROOT / "hosts.json",
    Path.home() / ".config" / "herdstone" / "hosts.json",
    Path.home() / "herdstone_hosts.json",
]


def get_inventory_path() -> Path | None:
    env_path = os.environ.get("HERDSTONE_HOSTS")
    if env_path:
        p = Path(env_path).expanduser()
        return p if p.is_file() else None
    for path in INVENTORY_SEARCH_PATH:
        if path.is_file():
            return path
    return None


def load_env() -> None:
    """Load .env from the repo root (and CWD as fallback). Idempotent, safe to call often."""
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    load_dotenv()  # CWD .env, does not override already-set vars
