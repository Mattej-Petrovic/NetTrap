from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def bundle_root() -> Path:
    if is_frozen():
        bundle_dir = getattr(sys, "_MEIPASS", None)
        if bundle_dir:
            return Path(bundle_dir).resolve()
        return Path(sys.executable).resolve().parent
    return project_root()


def app_root() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return project_root()


def resource_path(*parts: str) -> Path:
    return bundle_root().joinpath(*parts)


def app_path(*parts: str) -> Path:
    return app_root().joinpath(*parts)
