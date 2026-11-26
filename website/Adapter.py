"""Adapter stub for NPTU RWD Website data source (reserved for future endpoints)."""
from __future__ import annotations

from typing import Any

from core.base_adapter import BaseNptuAdapter, TempDataDumper
from core.storage import BotStorage


class WebsiteAdapter(BaseNptuAdapter):
    """Placeholder adapter for the 行動屏大 RWD source."""

    source_name = "website"

    def __init__(self, storage: BotStorage, dumper: TempDataDumper | None = None):
        self.storage = storage
        self.dumper = dumper or TempDataDumper()

    def _not_ready(self, feature: str) -> Any:
        raise NotImplementedError(f"website (RWD) 來源尚未實作 {feature}，請改用 application 來源。")

    async def close(self) -> None:
        return None

    async def login(self, force: bool = False) -> dict[str, Any]:
        return self._not_ready("login")

    async def logout(self) -> None:
        return None

    def get_profile(self) -> dict[str, Any]:
        return {}

    async def get_semesters(self) -> list[dict[str, Any]]:
        return self._not_ready("get_semesters")

    async def get_scores(self, year: str, term: str) -> list[dict[str, Any]]:
        return self._not_ready("get_scores")

    async def get_courses(self, year: str, term: str, phase: str) -> list[dict[str, Any]]:
        return self._not_ready("get_courses")

    async def get_leave_statistics(self, year: str, term: str) -> Any:
        return self._not_ready("get_leave_statistics")

    async def get_leave_list(self, year: str, term: str, status: str = "") -> list[dict[str, Any]]:
        return self._not_ready("get_leave_list")

    async def get_leave_ask_list(self, status: str = "A") -> list[dict[str, Any]]:
        return self._not_ready("get_leave_ask_list")

    async def get_leave_basic_data(self) -> Any:
        return self._not_ready("get_leave_basic_data")

    async def submit_leave(
        self,
        excuse_date: str,
        lesson_ids: str,
        excuse_id: str,
        reason: str,
        file_base64: str = "",
        file_type: str = "jpg",
    ) -> dict[str, Any]:
        return self._not_ready("submit_leave")

    async def delete_leave(
        self,
        excuse_date: str,
        excuse_id: str,
        lesson_id: str,
        file_pk: str,
    ) -> dict[str, Any]:
        return self._not_ready("delete_leave")

    async def get_rewards(self) -> Any:
        return self._not_ready("get_rewards")

    async def get_score_alerts(self, year: str, term: str) -> Any:
        return self._not_ready("get_score_alerts")

    async def get_course_year_term(self) -> Any:
        return self._not_ready("get_course_year_term")

    async def get_course_departments(self, year: str) -> Any:
        return self._not_ready("get_course_departments")

    async def get_course_basic_data(self) -> Any:
        return self._not_ready("get_course_basic_data")

    async def query_school_courses(self, year: str, term: str, **filters: str) -> list[dict[str, Any]]:
        return self._not_ready("query_school_courses")

    async def get_course_detail(self, open_id: str) -> Any:
        return self._not_ready("get_course_detail")

    async def get_locations(self) -> Any:
        return self._not_ready("get_locations")

    async def get_map_poi(self, poi_type: str = "") -> Any:
        return self._not_ready("get_map_poi")

    async def search_library_books(self, qtype: str, qtext: str, page: int = 1) -> Any:
        return self._not_ready("search_library_books")

    async def get_library_book_detail(self, bib_ids: str) -> Any:
        return self._not_ready("get_library_book_detail")

    async def get_library_open_time(self, month: str = "") -> Any:
        return self._not_ready("get_library_open_time")

    async def get_library_news(self, page: int = 1) -> Any:
        return self._not_ready("get_library_news")


Adapter = WebsiteAdapter
