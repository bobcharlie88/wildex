"""Best-effort Linnaean taxonomy from GBIF's public species-match API.

Never blocks card rendering: unknown names return {} immediately and a
background thread fills the in-memory cache for the next render.
"""
from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request

_CACHE: dict[str, dict] = {}
_PENDING: set[str] = set()
_LOCK = threading.Lock()
_KEYS = ("kingdom", "phylum", "class", "order", "family")


def _fetch(name: str) -> None:
    result: dict = {}
    try:
        url = "https://api.gbif.org/v1/species/match?" + urllib.parse.urlencode({"name": name, "strict": "false"})
        with urllib.request.urlopen(url, timeout=4) as resp:  # noqa: S310 - fixed https host
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("matchType") not in (None, "NONE") and int(data.get("confidence") or 0) >= 80:
            result = {k: data[k] for k in _KEYS if data.get(k)}
            # Newer GBIF backbones list reptile orders as classes; show the familiar form.
            if result.get("class") in {"Squamata", "Testudines", "Crocodylia"} and not result.get("order"):
                result["order"] = result["class"]
                result["class"] = "Reptilia"
    except Exception:
        result = {}
    with _LOCK:
        _CACHE[name] = result
        _PENDING.discard(name)


def taxonomy_for(scientific_name: str | None) -> dict:
    name = " ".join(str(scientific_name or "").split())
    if not name or len(name) > 120:
        return {}
    key = name.lower()
    with _LOCK:
        if key in _CACHE:
            return dict(_CACHE[key])
        if key in _PENDING:
            return {}
        _PENDING.add(key)
    threading.Thread(target=_fetch, args=(key,), daemon=True).start()
    return {}
