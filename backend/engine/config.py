import os
from pathlib import Path

from readable_utils.inventory_tools import find_inventory_paths

# Repo root (this file is backend/engine/config.py). In the docker image the
# package sits one level shallower, at /app/engine, where the repo-relative
# paths don't exist: use the package's parent dir there and rely on
# HERDSTONE_HOSTS / the container environment instead.
_PROJECT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = _PROJECT_DIR.parent if _PROJECT_DIR.name == "backend" else _PROJECT_DIR

# Inventory search path — EVERY existing file loads and the herds merge
# (first definition of a name wins), the same multi-context discovery the
# status_board repo uses: each sibling *_credentials repo contributes its
# <context>_hosts.json, so cloning a context's
# credentials repo adds its machines to the herd. HERDSTONE_HOSTS overrides
# everything with a single file.
INVENTORY_SEARCH_PATH = [
    *(Path(p) for p in find_inventory_paths(str(REPO_ROOT.parent))),
    REPO_ROOT / "hosts.json",
    Path.home() / ".config" / "herdstone" / "hosts.json",
    Path.home() / "herdstone_hosts.json",
]


def get_inventory_paths() -> list[Path]:
    """Every inventory file to load, in precedence order (HERDSTONE_HOSTS overrides all)."""
    env_path = os.environ.get("HERDSTONE_HOSTS")
    if env_path:
        p = Path(env_path).expanduser()
        return [p] if p.is_file() else []
    return [path for path in INVENTORY_SEARCH_PATH if path.is_file()]


def load_env() -> None:
    """Load .env from the repo root (and CWD as fallback). Idempotent, safe to call often."""
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    load_dotenv()  # CWD .env, does not override already-set vars
