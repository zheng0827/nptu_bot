"""Public (no-login) interactive Views and Modals open to all server members."""
from __future__ import annotations

from typing import Any, Callable, Coroutine

import discord

from NptuRequester import NptuRequester
from ui.formatters import (
    build_classroom_embed,
    build_generic_personal_embed,
    build_library_search_embed,
    build_public_courses_embed,
)

BackCallback = Callable[[discord.Interaction], Coroutine[Any, Any, None]]


class CourseSearchModal(discord.ui.Modal, title="📚 免登入全校課程查詢"):
    subject_name = discord.ui.TextInput(label="課程名稱關鍵字", placeholder="例如：資料結構（可留空）", required=False)
    teacher_name = discord.ui.TextInput(label="授課教師", placeholder="例如：王小明（可留空）", required=False)
    week_id = discord.ui.TextInput(label="星期 (1~7)", placeholder="1=星期一 ... 7=星期日（可留空）", required=False)
    year_term = discord.ui.TextInput(label="學年-學期 (留空自動抓最新)", placeholder="例如：114-2", required=False)

    def __init__(self, requester: NptuRequester, on_back: BackCallback | None = None):
        super().__init__()
        self.requester = requester
        self.on_back = on_back

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        year = None
        term = None
        yt = str(self.year_term.value or "").strip()
        if "-" in yt:
            parts = yt.split("-", 1)
            year, term = parts[0].strip(), parts[1].strip()
        try:
            res = await self.requester.query_school_courses(
                year=year,
                term=term,
                subjectName=str(self.subject_name.value or "").strip(),
                teacherName=str(self.teacher_name.value or "").strip(),
                weekID=str(self.week_id.value or "").strip(),
            )
            view = CourseQueryView(self.requester, res, on_back=self.on_back)
            await interaction.edit_original_response(embed=build_public_courses_embed(res, page=0), view=view, attachments=[])
        except Exception as exc:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 課程查詢失敗", description=str(exc), color=0xE74C3C),
            )


class CourseQueryView(discord.ui.View):
    """Paginated public course results with syllabus lookup."""

    def __init__(
        self,
        requester: NptuRequester,
        result: dict[str, Any] | None = None,
        on_back: BackCallback | None = None,
    ):
        super().__init__(timeout=300)
        self.requester = requester
        self.result = result
        self.on_back = on_back
        self.page = 0

    @discord.ui.button(label="🔍 搜尋課程", style=discord.ButtonStyle.primary)
    async def btn_search(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(CourseSearchModal(self.requester, on_back=self.on_back))

    @discord.ui.button(label="◀ 上頁", style=discord.ButtonStyle.secondary)
    async def btn_prev(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.result and self.page > 0:
            self.page -= 1
            await interaction.response.edit_message(
                embed=build_public_courses_embed(self.result, page=self.page),
                view=self,
            )
        else:
            await interaction.response.defer()

    @discord.ui.button(label="下頁 ▶", style=discord.ButtonStyle.secondary)
    async def btn_next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.result:
            total = len(self.result.get("courses") or [])
            if (self.page + 1) * 8 < total:
                self.page += 1
                await interaction.response.edit_message(
                    embed=build_public_courses_embed(self.result, page=self.page),
                    view=self,
                )
                return
        await interaction.response.defer()

    @discord.ui.button(label="🏠 返回主控台", style=discord.ButtonStyle.secondary)
    async def btn_back(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.on_back:
            await self.on_back(interaction)
        else:
            await interaction.response.defer()


class LibrarySearchModal(discord.ui.Modal, title="📖 屏大圖書館館藏查詢"):
    qtext = discord.ui.TextInput(label="搜尋關鍵字", placeholder="例如：Python / 演算法", required=True)
    qtype = discord.ui.TextInput(label="查詢類型 (title / author / keyword / isbn)", default="title", required=True)

    def __init__(self, requester: NptuRequester, on_back: BackCallback | None = None):
        super().__init__()
        self.requester = requester
        self.on_back = on_back

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        qtext = str(self.qtext.value).strip()
        qtype = str(self.qtype.value or "title").strip().lower()
        try:
            data = await self.requester.search_library_books(qtext=qtext, qtype=qtype, page=1)
            view = LibraryView(self.requester, on_back=self.on_back)
            await interaction.edit_original_response(
                embed=build_library_search_embed(qtext, qtype, data),
                view=view,
                attachments=[],
            )
        except Exception as exc:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 圖書查詢失敗", description=str(exc), color=0xE74C3C),
            )


class LibraryView(discord.ui.View):
    """Public library search & opening hours hub."""

    def __init__(self, requester: NptuRequester, on_back: BackCallback | None = None):
        super().__init__(timeout=300)
        self.requester = requester
        self.on_back = on_back

    @discord.ui.button(label="🔍 搜尋館藏", style=discord.ButtonStyle.primary)
    async def btn_search(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(LibrarySearchModal(self.requester, on_back=self.on_back))

    @discord.ui.button(label="🕒 開館時間", style=discord.ButtonStyle.secondary)
    async def btn_open_time(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        try:
            data = await self.requester.get_library_open_time()
            embed = build_generic_personal_embed("🕒 屏大圖書館開館時間", data, "查無開館時間資料。")
            await interaction.edit_original_response(embed=embed, view=self, attachments=[])
        except Exception as exc:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 查詢開館時間失敗", description=str(exc), color=0xE74C3C),
                view=self,
            )

    @discord.ui.button(label="🏠 返回主控台", style=discord.ButtonStyle.secondary)
    async def btn_back(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.on_back:
            await self.on_back(interaction)
        else:
            await interaction.response.defer()


class ClassroomSearchModal(discord.ui.Modal, title="🏫 免登入教室與地點查詢"):
    keyword = discord.ui.TextInput(label="教室或建築關鍵字", placeholder="例如：民生 / 屏商 / 電腦（可留空）", required=False)
    week_id = discord.ui.TextInput(label="星期 (1~7)", placeholder="例如：1（可留空）", required=False)
    lesson_start = discord.ui.TextInput(label="起始節次 (如 01~09, A~D)", placeholder="例如：01（可留空）", required=False)
    lesson_end = discord.ui.TextInput(label="結束節次", placeholder="例如：04（可留空）", required=False)

    def __init__(self, requester: NptuRequester, on_back: BackCallback | None = None):
        super().__init__()
        self.requester = requester
        self.on_back = on_back

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            res = await self.requester.query_classrooms(
                week_id=str(self.week_id.value or "").strip(),
                lesson_start=str(self.lesson_start.value or "").strip(),
                lesson_end=str(self.lesson_end.value or "").strip(),
                keyword=str(self.keyword.value or "").strip(),
            )
            view = ClassroomView(self.requester, on_back=self.on_back)
            await interaction.edit_original_response(embed=build_classroom_embed(res), view=view, attachments=[])
        except Exception as exc:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 教室查詢失敗", description=str(exc), color=0xE74C3C),
            )


class ClassroomView(discord.ui.View):
    """Public classroom usage & campus location hub."""

    def __init__(self, requester: NptuRequester, on_back: BackCallback | None = None):
        super().__init__(timeout=300)
        self.requester = requester
        self.on_back = on_back

    @discord.ui.button(label="🔍 查詢教室／地點", style=discord.ButtonStyle.primary)
    async def btn_search(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(ClassroomSearchModal(self.requester, on_back=self.on_back))

    @discord.ui.button(label="🏠 返回主控台", style=discord.ButtonStyle.secondary)
    async def btn_back(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.on_back:
            await self.on_back(interaction)
        else:
            await interaction.response.defer()
