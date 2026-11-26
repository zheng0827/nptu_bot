"""Unified NPTU data requester facade routing to configured source Adapters."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Callable, Coroutine, Literal

from application.Adapter import ApplicationAdapter
from core.base_adapter import BaseNptuAdapter, NPTUError, TempDataDumper
from core.gpa import ScoreSummary, summarize_scores
from core.schedule_renderer import render_schedule_png
from core.storage import BotStorage
from website.Adapter import WebsiteAdapter

logger = logging.getLogger(__name__)

ScopeType = Literal["term", "year", "all"]
AttendanceFilter = Literal["all", "leave", "absent"]


def _is_absent_record(rec: dict[str, Any]) -> bool:
    """Heuristic classifier distinguishing 曠課 (unexcused absence) from 請假 (leave)."""
    combined = " ".join(
        str(rec.get(k) or "")
        for k in ("excuse_NAME", "EXCUSE_NAME", "leave_NAME", "type_NAME", "status_TXT", "EXCUSE_ID", "status")
    )
    return "曠" in combined or "缺席" in combined


def _merge_stat_dicts(items: list[Any]) -> dict[str, float]:
    """Aggregate numeric fields across multiple semester leave-statistics payloads."""
    totals: dict[str, float] = {}

    def _accumulate(obj: Any) -> None:
        if isinstance(obj, list):
            for entry in obj:
                _accumulate(entry)
        elif isinstance(obj, dict):
            # Pattern A: {"name": "病假", "count": 2} or {"excuse_NAME": "事假", "hours": 3}
            label_key = next(
                (k for k in ("excuse_NAME", "EXCUSE_NAME", "leave_NAME", "name", "type", "title", "KIND_NAME") if k in obj),
                None,
            )
            value_key = next(
                (k for k in ("count", "hours", "total", "QTY", "qty", "CNT", "cnt", "num", "value") if k in obj),
                None,
            )
            if label_key and value_key:
                label = str(obj[label_key]).strip()
                try:
                    val = float(str(obj[value_key]).strip())
                except (TypeError, ValueError):
                    val = 0.0
                if label:
                    totals[label] = totals.get(label, 0.0) + val
                return

            # Pattern B: flat dict of {"病假": 2, "曠課": 1, ...}
            for k, v in obj.items():
                if k.lower() in {"syear", "seme", "year", "term", "studentid", "std_id"}:
                    continue
                if isinstance(v, (int, float)):
                    totals[k] = totals.get(k, 0.0) + float(v)
                elif isinstance(v, str):
                    try:
                        totals[k] = totals.get(k, 0.0) + float(v.strip())
                    except ValueError:
                        pass
                elif isinstance(v, (dict, list)):
                    _accumulate(v)

    for item in items:
        _accumulate(item)
    return totals


class NptuRequester:
    """Facade used by discord_bot.py to access application/ or website/ adapters."""

    def __init__(
        self,
        default_source: str | None = None,
        storage: BotStorage | None = None,
        dumper: TempDataDumper | None = None,
        cache_ttl: int | None = None,
    ):
        self.default_source = (default_source or os.getenv("NPTU_DEFAULT_SOURCE", "application")).strip().lower()
        self.storage = storage or BotStorage()
        self.dumper = dumper or TempDataDumper()
        self.cache_ttl = cache_ttl if cache_ttl is not None else int(os.getenv("NPTU_CACHE_TTL", "300"))

        self._adapters: dict[str, BaseNptuAdapter] = {
            "application": ApplicationAdapter(storage=self.storage, dumper=self.dumper),
            "website": WebsiteAdapter(storage=self.storage, dumper=self.dumper),
        }

    def get_adapter(self, source: str | None = None) -> BaseNptuAdapter:
        key = (source or self.default_source).strip().lower()
        if key not in self._adapters:
            raise NPTUError(f"不支援的資料來源：{key}（可用：{', '.join(self._adapters)}）")
        return self._adapters[key]

    async def close(self) -> None:
        for adapter in self._adapters.values():
            await adapter.close()

    async def _cached(
        self,
        cache_key: str,
        fetcher: Callable[[], Coroutine[Any, Any, Any]],
        *,
        force_refresh: bool = False,
        ttl: int | None = None,
    ) -> Any:
        effective_ttl = self.cache_ttl if ttl is None else ttl
        if not force_refresh and effective_ttl > 0:
            hit = self.storage.cache_get(cache_key, effective_ttl)
            if hit is not None:
                return hit
        data = await fetcher()
        if effective_ttl > 0:
            self.storage.cache_put(cache_key, data)
        return data

    # =========================================================================
    # Auth & Profile
    # =========================================================================
    async def login(self, force: bool = False, source: str | None = None) -> dict[str, Any]:
        return await self.get_adapter(source).login(force=force)

    async def logout(self, source: str | None = None) -> None:
        adapter = self.get_adapter(source)
        await adapter.logout()
        self.storage.cache_clear_prefix(f"{adapter.source_name}:")

    def get_profile(self, source: str | None = None) -> dict[str, Any]:
        return self.get_adapter(source).get_profile()

    # =========================================================================
    # Semesters
    # =========================================================================
    async def get_semesters(self, *, force_refresh: bool = False, source: str | None = None) -> list[dict[str, Any]]:
        adapter = self.get_adapter(source)
        return await self._cached(
            f"{adapter.source_name}:semesters",
            adapter.get_semesters,
            force_refresh=force_refresh,
            ttl=600,
        )

    async def get_latest_semester(self, source: str | None = None) -> tuple[str, str, str]:
        semesters = await self.get_semesters(source=source)
        if not semesters:
            raise NPTUError("找不到任何學期資料。")
        first = semesters[0]
        year = str(first.get("syear") or "")
        term = str(first.get("seme") or "1")
        phase = str(first.get("default_PHASE") or "4")
        if phase in {"-1", "0", ""}:
            phase = "1"
        return year, term, phase

    async def _resolve_semesters_for_scope(
        self,
        scope: ScopeType,
        year: str | None = None,
        term: str | None = None,
        source: str | None = None,
    ) -> tuple[list[tuple[str, str]], str]:
        semesters = await self.get_semesters(source=source)
        if not semesters and not year:
            raise NPTUError("無法取得學期清單。")

        if scope == "term":
            if year and term:
                return [(str(year), str(term))], f"{year} 學年第 {term} 學期"
            latest_y, latest_t, _ = await self.get_latest_semester(source=source)
            y = str(year or latest_y)
            t = str(term or latest_t)
            return [(y, t)], f"{y} 學年第 {t} 學期"

        if scope == "year":
            target_year = str(year or semesters[0].get("syear"))
            pairs = [
                (str(s.get("syear")), str(s.get("seme")))
                for s in semesters
                if str(s.get("syear")) == target_year and s.get("seme")
            ]
            if not pairs:
                pairs = [(target_year, "1"), (target_year, "2")]
            return pairs, f"{target_year} 學年度"

        # scope == "all"
        pairs = [
            (str(s.get("syear")), str(s.get("seme")))
            for s in semesters
            if s.get("syear") and s.get("seme")
        ]
        return pairs, "在學期間（全部學期）"

    # =========================================================================
    # 1. Attendance / Leave Statistics & Records
    # =========================================================================
    async def get_attendance_statistics(
        self,
        scope: ScopeType = "term",
        year: str | None = None,
        term: str | None = None,
        *,
        force_refresh: bool = False,
        source: str | None = None,
    ) -> dict[str, Any]:
        adapter = self.get_adapter(source)
        pairs, label = await self._resolve_semesters_for_scope(scope, year, term, source=source)

        async def _fetch_one(y: str, t: str) -> tuple[str, str, Any]:
            data = await self._cached(
                f"{adapter.source_name}:leave_stat:{y}:{t}",
                lambda: adapter.get_leave_statistics(y, t),
                force_refresh=force_refresh,
            )
            return y, t, data

        results = await asyncio.gather(*[_fetch_one(y, t) for y, t in pairs], return_exceptions=True)
        raw_items: list[dict[str, Any]] = []
        raw_payloads: list[Any] = []
        for res in results:
            if isinstance(res, Exception):
                logger.warning("Failed to fetch leave statistics: %s", res)
                continue
            y, t, data = res
            if data is not None:
                raw_items.append({"year": y, "term": t, "data": data})
                raw_payloads.append(data)

        totals = _merge_stat_dicts(raw_payloads)
        return {
            "scope": scope,
            "label": label,
            "semesters": pairs,
            "totals": totals,
            "raw_by_semester": raw_items,
        }

    async def get_attendance_records(
        self,
        scope: ScopeType = "term",
        record_filter: AttendanceFilter = "all",
        year: str | None = None,
        term: str | None = None,
        *,
        force_refresh: bool = False,
        source: str | None = None,
    ) -> dict[str, Any]:
        adapter = self.get_adapter(source)
        pairs, label = await self._resolve_semesters_for_scope(scope, year, term, source=source)

        async def _fetch_one(y: str, t: str) -> list[dict[str, Any]]:
            rows = await self._cached(
                f"{adapter.source_name}:leave_list:{y}:{t}",
                lambda: adapter.get_leave_list(y, t),
                force_refresh=force_refresh,
            )
            enriched = []
            for row in rows:
                item = dict(row)
                item.setdefault("_year", y)
                item.setdefault("_term", t)
                enriched.append(item)
            return enriched

        results = await asyncio.gather(*[_fetch_one(y, t) for y, t in pairs], return_exceptions=True)
        all_rows: list[dict[str, Any]] = []
        for res in results:
            if isinstance(res, Exception):
                logger.warning("Failed to fetch leave list: %s", res)
                continue
            all_rows.extend(res)

        if record_filter == "absent":
            filtered = [r for r in all_rows if _is_absent_record(r)]
        elif record_filter == "leave":
            filtered = [r for r in all_rows if not _is_absent_record(r)]
        else:
            filtered = all_rows

        return {
            "scope": scope,
            "filter": record_filter,
            "label": label,
            "semesters": pairs,
            "records": filtered,
            "total_before_filter": len(all_rows),
        }

    # =========================================================================
    # 2. Scores & Official NPTU 4.0 GPA
    # =========================================================================
    async def get_scores(
        self,
        scope: ScopeType = "term",
        year: str | None = None,
        term: str | None = None,
        *,
        force_refresh: bool = False,
        source: str | None = None,
    ) -> dict[str, Any]:
        adapter = self.get_adapter(source)
        pairs, label = await self._resolve_semesters_for_scope(scope, year, term, source=source)

        async def _fetch_one(y: str, t: str) -> list[dict[str, Any]]:
            rows = await self._cached(
                f"{adapter.source_name}:scores:{y}:{t}",
                lambda: adapter.get_scores(y, t),
                force_refresh=force_refresh,
            )
            enriched = []
            for row in rows:
                item = dict(row)
                item.setdefault("_year", y)
                item.setdefault("_term", t)
                enriched.append(item)
            return enriched

        results = await asyncio.gather(*[_fetch_one(y, t) for y, t in pairs], return_exceptions=True)
        records: list[dict[str, Any]] = []
        for res in results:
            if isinstance(res, Exception):
                logger.warning("Failed to fetch scores: %s", res)
                continue
            records.extend(res)

        summary: ScoreSummary = summarize_scores(records)
        return {
            "scope": scope,
            "label": label,
            "semesters": pairs,
            "records": records,
            "summary": summary,
        }

    # =========================================================================
    # 3. Schedule & PNG Rendering
    # =========================================================================
    async def get_schedule(
        self,
        year: str | None = None,
        term: str | None = None,
        phase: str | None = None,
        *,
        force_refresh: bool = False,
        source: str | None = None,
    ) -> dict[str, Any]:
        adapter = self.get_adapter(source)
        if not year or not term or not phase:
            ly, lt, lp = await self.get_latest_semester(source=source)
            year = str(year or ly)
            term = str(term or lt)
            phase = str(phase or lp)

        courses = await self._cached(
            f"{adapter.source_name}:courses:{year}:{term}:{phase}",
            lambda: adapter.get_courses(year, term, phase),
            force_refresh=force_refresh,
        )
        png_bytes = await asyncio.to_thread(render_schedule_png, courses) if courses else None
        return {
            "year": year,
            "term": term,
            "phase": phase,
            "courses": courses,
            "png_bytes": png_bytes,
        }

    # =========================================================================
    # 4. Leave Application & Cancellation
    # =========================================================================
    async def get_leave_ask_list(self, status: str = "A", source: str | None = None) -> list[dict[str, Any]]:
        return await self.get_adapter(source).get_leave_ask_list(status=status)

    async def get_leave_basic_data(self, *, force_refresh: bool = False, source: str | None = None) -> Any:
        adapter = self.get_adapter(source)
        return await self._cached(
            f"{adapter.source_name}:leave_basic_data",
            adapter.get_leave_basic_data,
            force_refresh=force_refresh,
            ttl=3600,
        )

    async def submit_leave(
        self,
        excuse_date: str,
        lesson_ids: str,
        excuse_id: str,
        reason: str,
        file_base64: str = "",
        file_type: str = "jpg",
        source: str | None = None,
    ) -> dict[str, Any]:
        adapter = self.get_adapter(source)
        result = await adapter.submit_leave(
            excuse_date=excuse_date,
            lesson_ids=lesson_ids,
            excuse_id=excuse_id,
            reason=reason,
            file_base64=file_base64,
            file_type=file_type,
        )
        self.storage.cache_clear_prefix(f"{adapter.source_name}:leave_")
        return result

    async def delete_leave(
        self,
        excuse_date: str,
        excuse_id: str,
        lesson_id: str,
        file_pk: str,
        source: str | None = None,
    ) -> dict[str, Any]:
        adapter = self.get_adapter(source)
        result = await adapter.delete_leave(
            excuse_date=excuse_date,
            excuse_id=excuse_id,
            lesson_id=lesson_id,
            file_pk=file_pk,
        )
        self.storage.cache_clear_prefix(f"{adapter.source_name}:leave_")
        return result

    # =========================================================================
    # 5 & 6. Rewards & Academic Score Alerts
    # =========================================================================
    async def get_rewards(self, *, force_refresh: bool = False, source: str | None = None) -> Any:
        adapter = self.get_adapter(source)
        return await self._cached(
            f"{adapter.source_name}:rewards",
            adapter.get_rewards,
            force_refresh=force_refresh,
        )

    async def get_score_alerts(
        self,
        year: str | None = None,
        term: str | None = None,
        *,
        force_refresh: bool = False,
        source: str | None = None,
    ) -> dict[str, Any]:
        adapter = self.get_adapter(source)
        if not year or not term:
            ly, lt, _ = await self.get_latest_semester(source=source)
            year = str(year or ly)
            term = str(term or lt)
        data = await self._cached(
            f"{adapter.source_name}:alerts:{year}:{term}",
            lambda: adapter.get_score_alerts(year, term),
            force_refresh=force_refresh,
        )
        return {"year": year, "term": term, "data": data}

    # =========================================================================
    # 7, 8, 9. Public No-Login Queries (Courses, Classrooms, Library)
    # =========================================================================
    async def get_public_course_year_term(self, source: str | None = None) -> Any:
        adapter = self.get_adapter(source)
        return await self._cached(
            f"{adapter.source_name}:pub_course_yt",
            adapter.get_course_year_term,
            ttl=3600,
        )

    async def get_public_latest_year_term(self, source: str | None = None) -> tuple[str, str]:
        raw = await self.get_public_course_year_term(source=source)
        if isinstance(raw, list) and raw:
            first = raw[0] if isinstance(raw[0], dict) else {}
            year = str(first.get("syear") or first.get("year") or first.get("YEAR") or "")
            term = str(first.get("seme") or first.get("term") or first.get("TERM") or "1")
            if year:
                return year, term
        if isinstance(raw, dict):
            year = str(raw.get("syear") or raw.get("year") or raw.get("YEAR") or "")
            term = str(raw.get("seme") or raw.get("term") or raw.get("TERM") or "1")
            if year:
                return year, term
        raise NPTUError("無法自動取得公開開課學期，請手動指定學年與學期。")

    async def query_school_courses(
        self,
        year: str | None = None,
        term: str | None = None,
        *,
        source: str | None = None,
        **filters: str,
    ) -> dict[str, Any]:
        adapter = self.get_adapter(source)
        if not year or not term:
            ly, lt = await self.get_public_latest_year_term(source=source)
            year = str(year or ly)
            term = str(term or lt)
        clean_filters = {k: str(v).strip() for k, v in filters.items() if v not in (None, "")}
        cache_key = f"{adapter.source_name}:pub_courses:{year}:{term}:{json.dumps(clean_filters, sort_keys=True, ensure_ascii=False)}"
        courses = await self._cached(
            cache_key,
            lambda: adapter.query_school_courses(year, term, **clean_filters),
            ttl=300,
        )
        return {"year": year, "term": term, "filters": clean_filters, "courses": courses}

    async def get_course_detail(self, open_id: str, source: str | None = None) -> Any:
        adapter = self.get_adapter(source)
        return await self._cached(
            f"{adapter.source_name}:pub_course_detail:{open_id}",
            lambda: adapter.get_course_detail(open_id),
            ttl=3600,
        )

    async def query_classrooms(
        self,
        year: str | None = None,
        term: str | None = None,
        week_id: str = "",
        lesson_start: str = "",
        lesson_end: str = "",
        keyword: str = "",
        *,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Query classroom usage via public course timetable + campus building locations."""
        adapter = self.get_adapter(source)
        filters: dict[str, str] = {}
        if week_id:
            filters["weekID"] = week_id
        if lesson_start:
            filters["lessonStartID"] = lesson_start
        if lesson_end:
            filters["lessonEndID"] = lesson_end

        course_res = await self.query_school_courses(year, term, source=source, **filters)
        courses = course_res["courses"]
        kw = keyword.strip().lower()

        room_map: dict[str, list[dict[str, Any]]] = {}
        for c in courses:
            room = str(
                c.get("room_CNAME")
                or c.get("ROOM_CNAME")
                or c.get("room")
                or c.get("classRoom")
                or ""
            ).strip()
            if not room:
                continue
            if kw and kw not in room.lower():
                continue
            room_map.setdefault(room, []).append(c)

        locations = await self._cached(
            f"{adapter.source_name}:pub_locations",
            adapter.get_locations,
            ttl=3600,
        )
        matched_locations: list[Any] = []
        if isinstance(locations, list):
            for loc in locations:
                if not kw or kw in json.dumps(loc, ensure_ascii=False).lower():
                    matched_locations.append(loc)

        return {
            "year": course_res["year"],
            "term": course_res["term"],
            "filters": filters,
            "keyword": keyword,
            "rooms": room_map,
            "locations": matched_locations[:15],
        }

    async def search_library_books(
        self,
        qtext: str,
        qtype: str = "title",
        page: int = 1,
        *,
        source: str | None = None,
    ) -> Any:
        adapter = self.get_adapter(source)
        return await self._cached(
            f"{adapter.source_name}:lib_search:{qtype}:{qtext}:{page}",
            lambda: adapter.search_library_books(qtype=qtype, qtext=qtext, page=page),
            ttl=300,
        )

    async def get_library_book_detail(self, bib_ids: str, source: str | None = None) -> Any:
        adapter = self.get_adapter(source)
        return await self._cached(
            f"{adapter.source_name}:lib_detail:{bib_ids}",
            lambda: adapter.get_library_book_detail(bib_ids),
            ttl=300,
        )

    async def get_library_open_time(self, month: str = "", source: str | None = None) -> Any:
        adapter = self.get_adapter(source)
        return await self._cached(
            f"{adapter.source_name}:lib_opentime:{month or 'lv1'}",
            lambda: adapter.get_library_open_time(month=month),
            ttl=1800,
        )

    # =========================================================================
    # Background Polling Diff Engine (Score & Leave Notifications -> DM)
    # =========================================================================
    async def check_score_updates(self, source: str | None = None) -> list[dict[str, Any]]:
        """Detect newly published or updated scores for the latest semester."""
        year, term, _ = await self.get_latest_semester(source=source)
        res = await self.get_scores("term", year, term, force_refresh=True, source=source)
        records = res["records"]

        current_map: dict[str, dict[str, Any]] = {}
        for rec in records:
            subj_id = str(rec.get("subj_ID") or rec.get("subj_CN") or "")
            if not subj_id:
                continue
            current_map[subj_id] = {
                "subj_ID": subj_id,
                "subj_CN": str(rec.get("subj_CN") or subj_id),
                "score": str(rec.get("score") or "").strip(),
                "pass_TXT": str(rec.get("pass_TXT") or "").strip(),
                "credits": str(rec.get("credits") or ""),
                "year": year,
                "term": term,
            }

        snap_key = f"scores:{year}:{term}"
        previous = self.storage.get_snapshot(snap_key)
        self.storage.save_snapshot(snap_key, current_map)

        if previous is None:
            # First run establishes baseline without spamming
            return []

        changes: list[dict[str, Any]] = []
        for subj_id, cur in current_map.items():
            prev = previous.get(subj_id)
            if cur["score"] and (prev is None or prev.get("score") != cur["score"]):
                changes.append({**cur, "old_score": prev.get("score") if prev else ""})
        return changes

    async def check_leave_updates(self, source: str | None = None) -> list[dict[str, Any]]:
        """Detect newly created or status-changed leave records for the latest semester."""
        year, term, _ = await self.get_latest_semester(source=source)
        res = await self.get_attendance_records("term", "all", year, term, force_refresh=True, source=source)
        records = res["records"]

        current_map: dict[str, dict[str, Any]] = {}
        for idx, rec in enumerate(records):
            key = "|".join(
                str(rec.get(k) or "")
                for k in ("EXCUSE_DT", "excuse_DT", "LESSON_ID", "lesson_ID", "EXCUSE_ID", "excuse_ID", "FILE_PK")
            ).strip("|")
            if not key:
                key = f"row_{idx}"
            status_val = str(
                rec.get("status_TXT")
                or rec.get("STATUS_TXT")
                or rec.get("verify_TXT")
                or rec.get("status")
                or rec.get("STATUS")
                or ""
            ).strip()
            current_map[key] = {
                "key": key,
                "status": status_val,
                "year": year,
                "term": term,
                "raw": rec,
            }

        snap_key = f"leaves:{year}:{term}"
        previous = self.storage.get_snapshot(snap_key)
        self.storage.save_snapshot(snap_key, current_map)

        if previous is None:
            return []

        changes: list[dict[str, Any]] = []
        for key, cur in current_map.items():
            prev = previous.get(key)
            if prev is None:
                changes.append({**cur, "change_type": "new", "old_status": ""})
            elif prev.get("status") != cur["status"]:
                changes.append({**cur, "change_type": "status_changed", "old_status": prev.get("status", "")})
        return changes
