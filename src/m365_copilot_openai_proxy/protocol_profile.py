from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from .atomic_write import write_text_atomic


_PROFILE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_CAPTURE_NODES = 20_000


def _items(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, str):
        return [item for item in re.split(r"[\s,]+", value) if item]
    return []


def _safe_tokens(value: Any) -> tuple[list[str], int]:
    accepted: list[str] = []
    rejected = 0
    for raw in _items(value):
        token = str(raw or "").strip()
        if not token or not _PROFILE_TOKEN.fullmatch(token):
            rejected += 1
            continue
        if token not in accepted:
            accepted.append(token)
    return accepted, rejected


def protocol_profile_candidate(payloads: Iterable[Any]) -> dict[str, Any]:
    """Extract a non-executable profile candidate from capture records.

    Only the two known protocol fields are inspected. Raw frames, URLs, bearer
    values, control characters and arbitrary nested objects never enter the
    candidate. Captures are evidence; applying them is a separate admin action.
    """
    variants: list[str] = []
    options_sets: list[str] = []
    source_records = 0
    rejected = 0

    def add_unique(target: list[str], items: list[str]) -> None:
        for item in items:
            if item not in target:
                target.append(item)

    def inspect(root: Any) -> bool:
        nonlocal rejected
        found = False
        stack: list[Any] = [root]
        seen: set[int] = set()
        visited = 0
        while stack and visited < _MAX_CAPTURE_NODES:
            node = stack.pop()
            visited += 1
            if isinstance(node, (dict, list)):
                identity = id(node)
                if identity in seen:
                    continue
                seen.add(identity)
            if isinstance(node, list):
                stack.extend(reversed(node))
                continue
            if not isinstance(node, dict):
                continue
            children: list[Any] = []
            for key, value in node.items():
                normalized = str(key).replace("_", "").lower()
                if normalized == "variants":
                    safe, bad = _safe_tokens(value)
                    add_unique(variants, safe)
                    rejected += bad
                    found = True
                elif normalized == "optionssets":
                    safe, bad = _safe_tokens(value)
                    add_unique(options_sets, safe)
                    rejected += bad
                    found = True
                elif normalized != "raw" and isinstance(value, (dict, list)):
                    children.append(value)
            stack.extend(reversed(children))
        if stack:
            # The capture was larger/deeper than the bounded scanner. Keep the
            # safe values already found, and expose the truncation as a rejected
            # item rather than risking unbounded CPU/stack use.
            rejected += 1
        return found

    for payload in payloads:
        if inspect(payload):
            source_records += 1
    return {
        "variants": variants,
        "options_sets": options_sets,
        "source_records": source_records,
        "rejected": rejected,
    }


class ProtocolProfileStore:
    def __init__(self, path: Path, builtin_variants: list[str], builtin_options_sets: list[str]):
        self.path = Path(path)
        self._builtin = {
            "source": "builtin",
            "variants": list(builtin_variants),
            "options_sets": list(builtin_options_sets),
        }
        self._profiles = self._load()

    @staticmethod
    def _scope_key(scope: str, scope_id: str) -> str:
        scope = str(scope or "").strip().lower()
        scope_id = str(scope_id or "").strip()
        if scope not in {"account", "tenant"}:
            raise ValueError("Protocol profile scope must be account or tenant.")
        if not _PROFILE_TOKEN.fullmatch(scope_id):
            raise ValueError("Protocol profile scope id is invalid.")
        return f"{scope}:{scope_id}"

    @staticmethod
    def _validated_profile(raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        variants, rejected_variants = _safe_tokens(raw.get("variants"))
        options_sets, rejected_options = _safe_tokens(raw.get("options_sets"))
        if rejected_variants or rejected_options or not variants or not options_sets:
            return None
        return {
            "source": "captured",
            "variants": variants,
            "options_sets": options_sets,
        }

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        # Legacy files held one unscoped profile. Applying that profile to every
        # account would recreate the cross-tenant leak this store now prevents.
        if not isinstance(raw, dict) or raw.get("version") != 2:
            return {}
        stored = raw.get("profiles")
        if not isinstance(stored, dict):
            return {}
        profiles: dict[str, dict[str, Any]] = {}
        for key, value in stored.items():
            try:
                scope, scope_id = str(key).split(":", 1)
                normalized_key = self._scope_key(scope, scope_id)
            except (ValueError, TypeError):
                continue
            profile = self._validated_profile(value)
            if profile is not None:
                profiles[normalized_key] = profile
        return profiles

    def _builtin_profile(self) -> dict[str, Any]:
        return {
            "source": "builtin",
            "scope": "builtin",
            "variants": list(self._builtin["variants"]),
            "options_sets": list(self._builtin["options_sets"]),
        }

    def _save(self, profiles: dict[str, dict[str, Any]] | None = None) -> None:
        target = self._profiles if profiles is None else profiles
        write_text_atomic(
            self.path,
            json.dumps(
                {"version": 2, "profiles": target},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            mode=0o600,
        )

    @staticmethod
    def _copy_profile(profile: dict[str, Any], scope: str) -> dict[str, Any]:
        return {
            "source": profile["source"],
            "scope": scope,
            "variants": list(profile["variants"]),
            "options_sets": list(profile["options_sets"]),
        }

    def active(self, *, account_id: str = "", tenant_id: str = "") -> dict[str, Any]:
        for scope, scope_id in (("account", account_id), ("tenant", tenant_id)):
            if not scope_id:
                continue
            try:
                key = self._scope_key(scope, scope_id)
            except ValueError:
                continue
            profile = self._profiles.get(key)
            if profile is not None:
                return self._copy_profile(profile, scope)
        return self._builtin_profile()

    def apply(
        self,
        candidate: dict[str, Any],
        *,
        scope: str,
        scope_id: str,
    ) -> dict[str, Any]:
        variants, rejected_variants = _safe_tokens(candidate.get("variants"))
        options_sets, rejected_options = _safe_tokens(candidate.get("options_sets"))
        if rejected_variants or rejected_options or not variants or not options_sets:
            raise ValueError("Captured protocol profile must contain safe variants and optionsSets.")
        key = self._scope_key(scope, scope_id)
        profile = {
            "source": "captured",
            "variants": variants,
            "options_sets": options_sets,
        }
        profiles = dict(self._profiles)
        profiles[key] = profile
        self._save(profiles)
        self._profiles = profiles
        return self._copy_profile(profile, scope)

    def rollback(self, *, scope: str, scope_id: str) -> dict[str, Any]:
        key = self._scope_key(scope, scope_id)
        if key not in self._profiles:
            return self._builtin_profile()
        profiles = dict(self._profiles)
        del profiles[key]
        self._save(profiles)
        self._profiles = profiles
        return self._builtin_profile()
