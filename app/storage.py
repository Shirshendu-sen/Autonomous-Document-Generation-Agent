"""
app/storage.py
--------------
Minimal in-memory registry from request_id -> {filepath, plan, reflection_log}.

A database would be over-engineering for a single-process demo service. The
registry is deliberately hidden behind a two-function interface (save/get)
so it can be swapped for Redis/Postgres later without touching main.py.
"""
from __future__ import annotations
from typing import Dict, Any, Optional

_REGISTRY: Dict[str, Dict[str, Any]] = {}


def save(request_id: str, record: Dict[str, Any]) -> None:
    _REGISTRY[request_id] = record


def get(request_id: str) -> Optional[Dict[str, Any]]:
    return _REGISTRY.get(request_id)
