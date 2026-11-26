"""Base adapter interface, shared exceptions, and temp_data JSON dumper."""
from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class NPTUError(RuntimeError):
    """Base exception for NPTU API and adapter errors."""


class NPTUAuthError(NPTUError):
    """Raised when authentication or token refresh fails."""


class NPTURateLimitError(NPTUError):
    """Raised when a local rate limit is triggered."""


_SENSITIVE_KEYS = {
    "password",
    "pwd",
    "accesstoken",
    "refreshtoken",
    "access_token",
    "refresh_token",
    "logintoken",
    "des_key",
    "nptu_app_3des_key",
}


def sanitize_for_dump(obj: Any) -> Any:
    """Recursively redact sensitive keys before writing JSON snapshots."""
    if isinstance(obj, Mapping):
        sanitized: dict[str, Any] = {}
        for k, v in obj.items():
            if str(k).lower() in _SENSITIVE_KEYS:
                sanitized[str(k)] = "***REDACTED***"
            else:
                sanitized[str(k)] = sanitize_for_dump(v)
        return sanitized
    if isinstance(obj, list):
        return [sanitize_for_dump(item) for item in obj]
    return obj


def _safe_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", value.strip())
    return cleaned.strip("_")[:48]


class TempDataDumper:
    """Saves every fetched API payload into temp_data/ as JSON for schema inspection."""

    def __init__(self, base_dir: Path | str | None = None, enabled: bool | None = None):
        env_enabled = os.getenv("NPTU_DUMP_TEMP_DATA", "true").strip().lower()
        self.enabled = (env_enabled not in {"0", "false", "no", "off"}) if enabled is None else enabled
        self.base_dir = Path(base_dir or os.getenv("NPTU_TEMP_DATA_DIR", "temp_data"))

    def dump(
        self,
        source: str,
        endpoint_name: str,
        payload: Any,
        params: Mapping[str, Any] | None = None,
    ) -> Path | None:
        if not self.enabled:
            return None
        self.base_dir.mkdir(parents=True, exist_ok=True)
        suffix_parts: list[str] = []
        if params:
            for k, v in params.items():
                if str(k).lower() in _SENSITIVE_KEYS or v in (None, ""):
                    continue
                if k in {"studentID", "account", "fileBase64String"}:
                    continue
                part = _safe_filename_part(f"{k}-{v}")
                if part:
                    suffix_parts.append(part)
        tag = ("_" + "_".join(suffix_parts[:4])) if suffix_parts else ""
        filename = f"{_safe_filename_part(source)}_{_safe_filename_part(endpoint_name)}{tag}.json"
        target = self.base_dir / filename

        record = {
            "meta": {
                "source": source,
                "endpoint": endpoint_name,
                "params": sanitize_for_dump(dict(params or {})),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            },
            "response": sanitize_for_dump(payload),
        }
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(target)
        return target


class BaseNptuAdapter(ABC):
    """Unified interface implemented by application/Adapter.py and website/Adapter.py."""

    source_name: str = "base"

    @abstractmethod
    async def close(self) -> None:
        """Release underlying HTTP sessions or resources."""

    # --- Auth & Profile ---
    @abstractmethod
    async def login(self, force: bool = False) -> dict[str, Any]:
        """Authenticate and return profile + oauth status."""

    @abstractmethod
    async def logout(self) -> None:
        """Clear local auth tokens and profile."""

    @abstractmethod
    def get_profile(self) -> dict[str, Any]:
        """Return cached student profile (e.g., std_CNAME)."""

    # --- Personal Academic (Login Required) ---
    @abstractmethod
    async def get_semesters(self) -> list[dict[str, Any]]:
        """Return available academic year/term records."""

    @abstractmethod
    async def get_scores(self, year: str, term: str) -> list[dict[str, Any]]:
        """Return course scores for a specific year/term."""

    @abstractmethod
    async def get_courses(self, year: str, term: str, phase: str) -> list[dict[str, Any]]:
        """Return personal timetable courses for a specific year/term/phase."""

    @abstractmethod
    async def get_leave_statistics(self, year: str, term: str) -> Any:
        """Return attendance/leave statistics for a specific year/term."""

    @abstractmethod
    async def get_leave_list(self, year: str, term: str, status: str = "") -> list[dict[str, Any]]:
        """Return leave/absence records for a specific year/term."""

    @abstractmethod
    async def get_leave_ask_list(self, status: str = "A") -> list[dict[str, Any]]:
        """Return absence/course slots available for leave application."""

    @abstractmethod
    async def get_leave_basic_data(self) -> Any:
        """Return leave type metadata (codes & names)."""

    @abstractmethod
    async def submit_leave(
        self,
        excuse_date: str,
        lesson_ids: str,
        excuse_id: str,
        reason: str,
        file_base64: str = "",
        file_type: str = "jpg",
    ) -> dict[str, Any]:
        """Submit a leave application."""

    @abstractmethod
    async def delete_leave(
        self,
        excuse_date: str,
        excuse_id: str,
        lesson_id: str,
        file_pk: str,
    ) -> dict[str, Any]:
        """Delete/cancel a leave application."""

    @abstractmethod
    async def get_rewards(self) -> Any:
        """Return personal reward/punishment records."""

    @abstractmethod
    async def get_score_alerts(self, year: str, term: str) -> Any:
        """Return midterm/academic alert records."""

    # --- Public Queries (No Login Required) ---
    @abstractmethod
    async def get_course_year_term(self) -> Any:
        """Return public available year/term list for course queries."""

    @abstractmethod
    async def get_course_departments(self, year: str) -> Any:
        """Return department list for a given academic year."""

    @abstractmethod
    async def get_course_basic_data(self) -> Any:
        """Return public course query basic metadata."""

    @abstractmethod
    async def query_school_courses(self, year: str, term: str, **filters: str) -> list[dict[str, Any]]:
        """Query public school-wide courses."""

    @abstractmethod
    async def get_course_detail(self, open_id: str) -> Any:
        """Return syllabus/detail for a specific open_ID."""

    @abstractmethod
    async def get_locations(self) -> Any:
        """Return campus building/location list."""

    @abstractmethod
    async def get_map_poi(self, poi_type: str = "") -> Any:
        """Return campus map POI list."""

    @abstractmethod
    async def search_library_books(self, qtype: str, qtext: str, page: int = 1) -> Any:
        """Search library catalog."""

    @abstractmethod
    async def get_library_book_detail(self, bib_ids: str) -> Any:
        """Get holding/availability detail for library book bib IDs."""

    @abstractmethod
    async def get_library_open_time(self, month: str = "") -> Any:
        """Get library opening hours (lv1 overview or lv2 monthly)."""

    @abstractmethod
    async def get_library_news(self, page: int = 1) -> Any:
        """Get library announcements."""
