from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from nettrap.core.runtime import app_root

APP_ROOT = app_root()
CONFIG_PATH = APP_ROOT / "config.yaml"
_CONFIG_ERROR: str | None = None

DEFAULT_CONFIG: dict[str, Any] = {
    "services": {
        "ssh": {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 22,
            "banner": "SSH-2.0-OpenSSH_8.9p1 Ubuntu-3ubuntu0.6",
        },
        "http": {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 80,
            "server_header": "Apache/2.4.41 (Ubuntu)",
            "page_profile": "admin",
            "trust_proxy_headers": False,
            "debug_proxy_resolution": False,
        },
    },
    "database": {"path": "data/nettrap.db"},
    "logging": {"json_dir": "data/logs", "level": "INFO"},
    "geoip": {"database_path": "data/GeoLite2-City.mmdb"},
    "gui": {"refresh_rate_ms": 1500, "max_feed_items": 200, "theme": "dark"},
    "export": {"default_format": "json", "default_directory": "exports"},
}

_PATH_KEYS = {"path", "json_dir", "database_path", "default_directory"}


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _resolve_paths(value: Any, project_root: Path, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {
            nested_key: _resolve_paths(nested_value, project_root, nested_key)
            for nested_key, nested_value in value.items()
        }

    if isinstance(value, list):
        return [_resolve_paths(item, project_root) for item in value]

    if isinstance(value, str) and key in _PATH_KEYS:
        path = Path(value)
        return str(path if path.is_absolute() else (project_root / path).resolve())

    return value


def _write_default_config(config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(DEFAULT_CONFIG, handle, sort_keys=False)


def _serialize_paths(value: Any, project_root: Path, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {
            nested_key: _serialize_paths(nested_value, project_root, nested_key)
            for nested_key, nested_value in value.items()
        }

    if isinstance(value, list):
        return [_serialize_paths(item, project_root) for item in value]

    if isinstance(value, str) and key in _PATH_KEYS:
        try:
            path = Path(value)
            if path.is_absolute():
                return str(path.relative_to(project_root))
        except Exception:
            return value

    return value


def reset_config_cache() -> None:
    get_config.cache_clear()


def get_last_config_error() -> str | None:
    return _CONFIG_ERROR


def get_config_path() -> Path:
    return CONFIG_PATH


def save_config(config: dict[str, Any]) -> None:
    serialized = _serialize_paths(config, CONFIG_PATH.parent)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(serialized, handle, sort_keys=False)
    reset_config_cache()


@lru_cache(maxsize=1)
def get_config() -> dict[str, Any]:
    global _CONFIG_ERROR
    _CONFIG_ERROR = None
    if not CONFIG_PATH.exists():
        _write_default_config(CONFIG_PATH)

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:
        _CONFIG_ERROR = str(exc)
        loaded = {}
    except Exception:
        loaded = {}

    if not isinstance(loaded, dict):
        loaded = {}

    merged = _merge_dicts(DEFAULT_CONFIG, loaded)
    return _resolve_paths(merged, CONFIG_PATH.parent)
