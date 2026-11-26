"""Adapter implementation for NPTU mobile APK data source."""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from application.client import AppClientConfig, NptuAppClient
from core.base_adapter import BaseNptuAdapter, NPTUError, TempDataDumper
from core.storage import BotStorage


_EMPTY_DATA_ERROR_CODES = {"310"}
_EMPTY_DATA_ERRORS = {"student_data_not_fount_error", "student_data_not_found_error"}


def _is_not_found_error(err_data: dict[str, Any]) -> bool:
    code = str(err_data.get("errorCode") or "").strip()
    err_name = str(err_data.get("error") or "").strip().lower()
    return (not code) or (code in _EMPTY_DATA_ERROR_CODES) or (err_name in _EMPTY_DATA_ERRORS)


def _extract_data_list(payload: Any) -> list[dict[str, Any]]:
    """Safely extract list data from NPTU API responses without crashing on empty results."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if payload.get("result") is False:
            err_data = data if isinstance(data, dict) else {}
            if _is_not_found_error(err_data):
                return []
            code = str(err_data.get("errorCode") or "unknown")
            desc = str(err_data.get("errorDescription") or payload.get("reason") or "")
            raise NPTUError(f"屏大 API 回傳錯誤 (errorCode={code})：{desc}")
    return []


def _extract_data_any(payload: Any) -> Any:
    """Safely unwrap payload['data'] while preserving unknown structures."""
    if isinstance(payload, dict):
        if payload.get("result") is False:
            err_data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            if _is_not_found_error(err_data):
                return None
            code = str(err_data.get("errorCode") or "unknown")
            desc = str(err_data.get("errorDescription") or payload.get("reason") or "")
            raise NPTUError(f"屏大 API 回傳錯誤 (errorCode={code})：{desc}")
        if "data" in payload:
            return payload["data"]
    return payload


class ApplicationAdapter(BaseNptuAdapter):
    """Concrete adapter targeting https://app.nptu.edu.tw:8443 (Mobile APK)."""

    source_name = "application"

    def __init__(
        self,
        storage: BotStorage,
        dumper: TempDataDumper | None = None,
        config: AppClientConfig | None = None,
    ):
        self.client = NptuAppClient(
            config=config or AppClientConfig.from_env(),
            storage=storage,
            dumper=dumper,
        )

    async def close(self) -> None:
        await self.client.close()

    # --- Auth & Profile ---
    async def login(self, force: bool = False) -> dict[str, Any]:
        return await self.client.login(force=force)

    async def logout(self) -> None:
        await self.client.logout()

    def get_profile(self) -> dict[str, Any]:
        return dict(self.client.config.profile)

    # --- Personal Academic ---
    async def get_semesters(self) -> list[dict[str, Any]]:
        payload = await self.client.request("student_semesters")
        return _extract_data_list(payload)

    async def get_scores(self, year: str, term: str) -> list[dict[str, Any]]:
        payload = await self.client.request("student_scores", {"year": str(year), "term": str(term)})
        return _extract_data_list(payload)

    async def get_courses(self, year: str, term: str, phase: str) -> list[dict[str, Any]]:
        payload = await self.client.request(
            "student_courses",
            {"year": str(year), "term": str(term), "phase": str(phase)},
        )
        return _extract_data_list(payload)

    async def get_leave_statistics(self, year: str, term: str) -> Any:
        payload = await self.client.request(
            "student_leave_statistics",
            {"year": str(year), "term": str(term)},
        )
        return _extract_data_any(payload)

    async def get_leave_list(self, year: str, term: str, status: str = "") -> list[dict[str, Any]]:
        params: dict[str, Any] = {"year": str(year), "term": str(term)}
        if status:
            params["status"] = status
        payload = await self.client.request("student_leave_list", params)
        return _extract_data_list(payload)

    async def get_leave_ask_list(self, status: str = "A") -> list[dict[str, Any]]:
        payload = await self.client.request("student_leave_ask_list", {"status": status})
        return _extract_data_list(payload)

    async def get_leave_basic_data(self) -> Any:
        payload = await self.client.request("leave_basic_data")
        return _extract_data_any(payload)

    async def submit_leave(
        self,
        excuse_date: str,
        lesson_ids: str,
        excuse_id: str,
        reason: str,
        file_base64: str = "",
        file_type: str = "jpg",
    ) -> dict[str, Any]:
        params = {
            "status": "A",
            "EXCUSE_DT": excuse_date,
            "LESSON_ID": lesson_ids,
            "EXCUSE_ID": excuse_id,
            "REASON": reason,
        }
        body: dict[str, Any] = {}
        if file_base64:
            body = {"fileBase64String": file_base64, "fileType": file_type}
        payload = await self.client.request(
            "student_leave_submit",
            params,
            method="POST",
            body=body,
            allow_mutation=True,
        )
        return payload if isinstance(payload, dict) else {"result": True, "data": payload}

    async def delete_leave(
        self,
        excuse_date: str,
        excuse_id: str,
        lesson_id: str,
        file_pk: str,
    ) -> dict[str, Any]:
        params = {
            "EXCUSE_DT": excuse_date,
            "EXCUSE_ID": excuse_id,
            "LESSON_ID": lesson_id,
            "FILE_PK": file_pk,
        }
        payload = await self.client.request(
            "student_leave_delete",
            params,
            allow_mutation=True,
        )
        return payload if isinstance(payload, dict) else {"result": True, "data": payload}

    async def get_rewards(self) -> Any:
        payload = await self.client.request("student_reward")
        return _extract_data_any(payload)

    async def get_score_alerts(self, year: str, term: str) -> Any:
        payload = await self.client.request(
            "student_score_alert",
            {"year": str(year), "term": str(term)},
        )
        return _extract_data_any(payload)

    # --- Public Queries (No Login Required) ---
    async def get_course_year_term(self) -> Any:
        payload = await self.client.request("course_year_term")
        return _extract_data_any(payload)

    async def get_course_departments(self, year: str) -> Any:
        safe_year = quote(str(year), safe="")
        payload = await self.client.request(
            "course_departments",
            path=f"/appws/school/getCourseDeptByYear/{safe_year}",
            params={"year": str(year)},
        )
        return _extract_data_any(payload)

    async def get_course_basic_data(self) -> Any:
        payload = await self.client.request("course_basic_data")
        return _extract_data_any(payload)

    async def query_school_courses(self, year: str, term: str, **filters: str) -> list[dict[str, Any]]:
        allowed = {
            "deptID",
            "commonID",
            "subjectName",
            "teacherName",
            "systemID",
            "weekID",
            "lessonStartID",
            "lessonEndID",
        }
        params = {k: v for k, v in filters.items() if k in allowed and v not in (None, "")}
        safe_year = quote(str(year), safe="")
        safe_term = quote(str(term), safe="")
        payload = await self.client.request(
            "course_query",
            path=f"/appws/school/queryCourse/{safe_year}/{safe_term}",
            params=params,
        )
        return _extract_data_list(payload)

    async def get_course_detail(self, open_id: str) -> Any:
        safe_id = quote(str(open_id), safe="")
        payload = await self.client.request(
            "course_detail",
            path=f"/appws/school/getCoursePlanByOpenID/{safe_id}",
            params={"open_ID": str(open_id)},
        )
        return _extract_data_any(payload)

    async def get_locations(self) -> Any:
        payload = await self.client.request("location_list")
        return _extract_data_any(payload)

    async def get_map_poi(self, poi_type: str = "") -> Any:
        params = {"type": poi_type} if poi_type else {}
        payload = await self.client.request("poi", params=params)
        return _extract_data_any(payload)

    async def search_library_books(self, qtype: str, qtext: str, page: int = 1) -> Any:
        payload = await self.client.request(
            "library_search_book",
            method="POST",
            body={"qtype": qtype, "qtext": qtext, "p": str(page)},
            params={"qtype": qtype, "qtext": qtext, "p": str(page)},
        )
        return _extract_data_any(payload)

    async def get_library_book_detail(self, bib_ids: str) -> Any:
        payload = await self.client.request(
            "library_book_detail",
            method="POST",
            body={"bibids": bib_ids},
            params={"bibids": bib_ids},
        )
        return _extract_data_any(payload)

    async def get_library_open_time(self, month: str = "") -> Any:
        if month:
            payload = await self.client.request(
                "library_open_time_lv2",
                method="POST",
                body={"month": month},
                params={"month": month},
            )
        else:
            payload = await self.client.request("library_open_time_lv1", method="POST", body={})
        return _extract_data_any(payload)

    async def get_library_news(self, page: int = 1) -> Any:
        safe_page = quote(str(page), safe="")
        payload = await self.client.request(
            "library_news",
            path=f"/appws/libNewsList/{safe_page}",
            params={"page": str(page)},
        )
        return _extract_data_any(payload)


# Alias for uniform dynamic import across sources
Adapter = ApplicationAdapter
