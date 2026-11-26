"""Discord Bot entry layer: Slash Commands, Interactive Panel, and DM Notification Poller."""
from __future__ import annotations

import io
import logging
import os
from typing import Literal

import discord
from discord import app_commands
from discord.ext import tasks

from NptuRequester import AttendanceFilter, NptuRequester, ScopeType
from ui.formatters import (
    build_attendance_records_embed,
    build_attendance_stats_embed,
    build_classroom_embed,
    build_generic_personal_embed,
    build_leave_notify_embed,
    build_library_search_embed,
    build_main_panel_embed,
    build_public_courses_embed,
    build_schedule_embed,
    build_score_notify_embed,
    build_score_trend_embed,
    build_scores_embed,
)
from ui.panel import MainPanelView
from ui.views_personal import (
    AttendanceView,
    LeaveApplyModal,
    LeaveView,
    RewardAlertView,
    ScheduleView,
    ScoreView,
)
from ui.views_public import ClassroomView, CourseQueryView, LibraryView

logger = logging.getLogger(__name__)


def _parse_owner_id() -> int | None:
    raw = os.getenv("DISCORD_OWNER_ID", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid DISCORD_OWNER_ID in .env: %r", raw)
        return None


class NptuBot(discord.Client):
    """NPTU Discord Bot powered by Slash Commands, Embed Panels, and NptuRequester."""

    def __init__(self, requester: NptuRequester):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.requester = requester
        self.owner_id = _parse_owner_id()
        self.tree = app_commands.CommandTree(self)
        self.poll_minutes = max(5, int(os.getenv("NPTU_POLL_INTERVAL_MINUTES", "30")))
        self._register_commands()

    async def setup_hook(self) -> None:
        self.poll_notifications.change_interval(minutes=self.poll_minutes)
        self.poll_notifications.start()
        synced = await self.tree.sync()
        logger.info("Synced %d slash commands.", len(synced))

    async def close(self) -> None:
        if self.poll_notifications.is_running():
            self.poll_notifications.cancel()
        await self.requester.close()
        await super().close()

    async def on_ready(self) -> None:
        logger.info("Bot logged in as %s (ID: %s)", self.user, self.user.id if self.user else "-")

    async def _require_owner(self, interaction: discord.Interaction) -> bool:
        if self.owner_id and interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "🔒 此指令屬個人校務功能，僅限 Bot 擁有者使用。",
                ephemeral=True,
            )
            return False
        return True

    async def _send_owner_dm(self, embed: discord.Embed) -> bool:
        if not self.owner_id:
            logger.warning("DISCORD_OWNER_ID 未設定，無法發送 DM 通知。")
            return False
        try:
            user = self.get_user(self.owner_id) or await self.fetch_user(self.owner_id)
            await user.send(embed=embed)
            return True
        except Exception as exc:
            logger.error("發送 DM 給 Owner 失敗：%s", exc)
            return False

    # =========================================================================
    # Background Notification Poller (Score & Leave -> DM)
    # =========================================================================
    @tasks.loop(minutes=30)
    async def poll_notifications(self) -> None:
        if not self.requester.storage.get_setting("notify_enabled", True):
            return
        if not self.owner_id:
            return
        try:
            score_changes = await self.requester.check_score_updates()
            if score_changes:
                await self._send_owner_dm(build_score_notify_embed(score_changes))
        except Exception as exc:
            logger.warning("背景檢查成績異動失敗：%s", exc)

        try:
            leave_changes = await self.requester.check_leave_updates()
            if leave_changes:
                await self._send_owner_dm(build_leave_notify_embed(leave_changes))
        except Exception as exc:
            logger.warning("背景檢查請假異動失敗：%s", exc)

    @poll_notifications.before_loop
    async def _before_poll(self) -> None:
        await self.wait_until_ready()

    # =========================================================================
    # Slash Commands Registration
    # =========================================================================
    def _register_commands(self) -> None:
        tree = self.tree

        @tree.command(name="panel", description="開啟行動屏大互動中控台面板（按鈕位於 Embed 下方）")
        async def cmd_panel(interaction: discord.Interaction) -> None:
            notify_enabled = bool(self.requester.storage.get_setting("notify_enabled", True))
            embed = build_main_panel_embed(
                self.requester.get_profile(),
                notify_enabled=notify_enabled,
                source=self.requester.default_source,
            )
            view = MainPanelView(self.requester, self.owner_id)
            await interaction.response.send_message(embed=embed, view=view)

        @tree.command(name="schedule", description="查詢並繪製指定學期課表圖片（僅限擁有者）")
        @app_commands.describe(year="學年（如 114，留空自動抓最新）", term="學期（1 或 2）", phase="選課階段（1~4）")
        async def cmd_schedule(
            interaction: discord.Interaction,
            year: str | None = None,
            term: str | None = None,
            phase: str | None = None,
        ) -> None:
            if not await self._require_owner(interaction):
                return
            await interaction.response.defer()
            try:
                semesters = await self.requester.get_semesters()
                res = await self.requester.get_schedule(year, term, phase)
                embed = build_schedule_embed(res, self.requester.get_profile())
                panel = MainPanelView(self.requester, self.owner_id)
                view = ScheduleView(
                    self.requester,
                    self.owner_id,
                    semesters,
                    res["year"],
                    res["term"],
                    res["phase"],
                    on_back=panel.return_to_main,
                )
                files = []
                if res.get("png_bytes"):
                    files.append(discord.File(io.BytesIO(res["png_bytes"]), filename="schedule.png"))
                await interaction.followup.send(embed=embed, files=files, view=view)
            except Exception as exc:
                await interaction.followup.send(
                    embed=discord.Embed(title="❌ 查詢課表失敗", description=str(exc), color=0xE74C3C)
                )

        @tree.command(name="score", description="查詢成績統計、屏大 4.0 GPA 與歷年平均折線圖（僅限擁有者）")
        @app_commands.describe(
            scope="模式：term(學期) / year(學年) / all(在學期間) / trend(歷年平均折線圖)",
            year="學年（如 114，留空自動抓當學期）",
            term="學期（1 / 2 / 3暑期）",
        )
        async def cmd_score(
            interaction: discord.Interaction,
            scope: Literal["term", "year", "all", "trend"] = "term",
            year: str | None = None,
            term: str | None = None,
        ) -> None:
            if not await self._require_owner(interaction):
                return
            await interaction.response.defer()
            try:
                semesters = await self.requester.get_semesters()
                default_y, default_t, _ = await self.requester.get_latest_semester()
                sel_year = str(year or default_y)
                sel_term = str(term or default_t)
                panel = MainPanelView(self.requester, self.owner_id)
                view = ScoreView(
                    self.requester,
                    self.owner_id,
                    semesters=semesters,
                    selected_year=sel_year,
                    selected_term=sel_term,
                    on_back=panel.return_to_main,
                    scope=scope,
                )
                if scope == "trend":
                    res = await self.requester.get_score_trend()
                    embed = build_score_trend_embed(res, self.requester.get_profile())
                    files = []
                    if res.get("png_bytes"):
                        files.append(discord.File(io.BytesIO(res["png_bytes"]), filename="score_trend.png"))
                    await interaction.followup.send(embed=embed, files=files, view=view)
                    return
                res = await self.requester.get_scores(scope, sel_year if scope in {"term", "year"} else None, sel_term if scope == "term" else None)
                await interaction.followup.send(embed=build_scores_embed(res, self.requester.get_profile()), view=view)
            except Exception as exc:
                await interaction.followup.send(
                    embed=discord.Embed(title="❌ 查詢成績失敗", description=str(exc), color=0xE74C3C)
                )

        @tree.command(name="attendance", description="查詢缺曠課統計或紀錄（僅限擁有者）")
        @app_commands.describe(
            mode="查詢模式：stats(統計) / records(明細紀錄)",
            scope="範圍：term(學期) / year(學年) / all(在學期間)",
            record_filter="紀錄篩選：all(全部) / leave(請假) / absent(曠課)",
            year="學年（選填）",
            term="學期（選填）",
        )
        async def cmd_attendance(
            interaction: discord.Interaction,
            mode: Literal["stats", "records"] = "stats",
            scope: ScopeType = "term",
            record_filter: AttendanceFilter = "all",
            year: str | None = None,
            term: str | None = None,
        ) -> None:
            if not await self._require_owner(interaction):
                return
            await interaction.response.defer()
            try:
                panel = MainPanelView(self.requester, self.owner_id)
                view = AttendanceView(
                    self.requester,
                    self.owner_id,
                    on_back=panel.return_to_main,
                    mode=mode,
                    scope=scope,
                    record_filter=record_filter,
                )
                if mode == "stats":
                    res = await self.requester.get_attendance_statistics(scope, year, term)
                    embed = build_attendance_stats_embed(res)
                else:
                    res = await self.requester.get_attendance_records(scope, record_filter, year, term)
                    embed = build_attendance_records_embed(res)
                view._last_result = res
                await interaction.followup.send(embed=embed, view=view)
            except Exception as exc:
                await interaction.followup.send(
                    embed=discord.Embed(title="❌ 查詢缺曠課失敗", description=str(exc), color=0xE74C3C)
                )

        @tree.command(name="leave", description="請假管理：查詢假單、可請假節次或線上申請（僅限擁有者）")
        @app_commands.describe(action="操作：panel(管理面板) / apply(直接開啟申請表單)")
        async def cmd_leave(
            interaction: discord.Interaction,
            action: Literal["panel", "apply"] = "panel",
        ) -> None:
            if not await self._require_owner(interaction):
                return
            if action == "apply":
                await interaction.response.send_modal(LeaveApplyModal(self.requester, self.owner_id))
                return
            panel = MainPanelView(self.requester, self.owner_id)
            view = LeaveView(self.requester, self.owner_id, on_back=panel.return_to_main)
            embed = discord.Embed(
                title="📝 屏大請假管理",
                description="請透過下方按鈕查詢假單、檢視可請假節次、查看假別代碼，或直接填表申請請假。",
                color=0x2B7DE9,
            )
            await interaction.response.send_message(embed=embed, view=view)

        @tree.command(name="reward", description="查詢個人獎懲紀錄（僅限擁有者）")
        async def cmd_reward(interaction: discord.Interaction) -> None:
            if not await self._require_owner(interaction):
                return
            await interaction.response.defer()
            try:
                data = await self.requester.get_rewards()
                panel = MainPanelView(self.requester, self.owner_id)
                view = RewardAlertView(self.requester, self.owner_id, on_back=panel.return_to_main)
                await interaction.followup.send(
                    embed=build_generic_personal_embed("🏅 個人獎懲紀錄", data, "目前查無獎懲紀錄。"),
                    view=view,
                )
            except Exception as exc:
                await interaction.followup.send(
                    embed=discord.Embed(title="❌ 查詢獎懲失敗", description=str(exc), color=0xE74C3C)
                )

        @tree.command(name="alert", description="查詢學習預警紀錄（僅限擁有者）")
        @app_commands.describe(year="學年（留空自動抓最新）", term="學期（1 或 2）")
        async def cmd_alert(
            interaction: discord.Interaction,
            year: str | None = None,
            term: str | None = None,
        ) -> None:
            if not await self._require_owner(interaction):
                return
            await interaction.response.defer()
            try:
                res = await self.requester.get_score_alerts(year, term)
                panel = MainPanelView(self.requester, self.owner_id)
                view = RewardAlertView(self.requester, self.owner_id, on_back=panel.return_to_main)
                await interaction.followup.send(
                    embed=build_generic_personal_embed(
                        f"⚠️ 學習預警紀錄（{res['year']}-{res['term']}）",
                        res["data"],
                        "本學期無學習預警紀錄！",
                    ),
                    view=view,
                )
            except Exception as exc:
                await interaction.followup.send(
                    embed=discord.Embed(title="❌ 查詢學習預警失敗", description=str(exc), color=0xE74C3C)
                )

        # === Public No-Login Commands (Open to Everyone) ===
        @tree.command(name="course", description="【免登入】全校課程資訊與課綱查詢（所有人可用）")
        @app_commands.describe(
            subject_name="課程名稱關鍵字",
            teacher_name="授課教師姓名",
            week_id="星期 (1~7)",
            year="學年（留空自動抓最新）",
            term="學期（1 或 2）",
            open_id="指定開課代碼直接查詢課程大綱",
        )
        async def cmd_course(
            interaction: discord.Interaction,
            subject_name: str = "",
            teacher_name: str = "",
            week_id: str = "",
            year: str | None = None,
            term: str | None = None,
            open_id: str = "",
        ) -> None:
            await interaction.response.defer()
            try:
                panel = MainPanelView(self.requester, self.owner_id)
                if open_id.strip():
                    detail = await self.requester.get_course_detail(open_id.strip())
                    embed = build_generic_personal_embed(f"📄 課程大綱（{open_id.strip()}）", detail, "查無課程大綱。")
                    await interaction.followup.send(embed=embed, view=CourseQueryView(self.requester, on_back=panel.return_to_main))
                    return
                res = await self.requester.query_school_courses(
                    year=year,
                    term=term,
                    subjectName=subject_name,
                    teacherName=teacher_name,
                    weekID=week_id,
                )
                view = CourseQueryView(self.requester, res, on_back=panel.return_to_main)
                await interaction.followup.send(embed=build_public_courses_embed(res, page=0), view=view)
            except Exception as exc:
                await interaction.followup.send(
                    embed=discord.Embed(title="❌ 課程查詢失敗", description=str(exc), color=0xE74C3C)
                )

        @tree.command(name="library", description="【免登入】屏大圖書館館藏與開館時間查詢（所有人可用）")
        @app_commands.describe(
            qtext="搜尋關鍵字（留空可搭配 open_time 查開館時間）",
            qtype="查詢類型：title / author / keyword / isbn",
            bib_id="指定館藏 BibID 查詢館藏位置與可借狀態",
            open_time="設為 True 查詢圖書館開館時間",
        )
        async def cmd_library(
            interaction: discord.Interaction,
            qtext: str = "",
            qtype: Literal["title", "author", "keyword", "isbn"] = "title",
            bib_id: str = "",
            open_time: bool = False,
        ) -> None:
            await interaction.response.defer()
            try:
                panel = MainPanelView(self.requester, self.owner_id)
                view = LibraryView(self.requester, on_back=panel.return_to_main)
                if open_time or (not qtext.strip() and not bib_id.strip()):
                    data = await self.requester.get_library_open_time()
                    embed = build_generic_personal_embed("🕒 屏大圖書館開館時間", data, "查無開館時間。")
                    await interaction.followup.send(embed=embed, view=view)
                    return
                if bib_id.strip():
                    data = await self.requester.get_library_book_detail(bib_id.strip())
                    embed = build_generic_personal_embed(f"📖 館藏明細（BibID: {bib_id.strip()}）", data, "查無館藏明細。")
                    await interaction.followup.send(embed=embed, view=view)
                    return
                data = await self.requester.search_library_books(qtext=qtext.strip(), qtype=qtype, page=1)
                await interaction.followup.send(embed=build_library_search_embed(qtext.strip(), qtype, data), view=view)
            except Exception as exc:
                await interaction.followup.send(
                    embed=discord.Embed(title="❌ 圖書查詢失敗", description=str(exc), color=0xE74C3C)
                )

        @tree.command(name="classroom", description="【免登入】教室使用狀況與校園地點查詢（所有人可用）")
        @app_commands.describe(
            keyword="教室或大樓關鍵字（例如：民生、屏商）",
            week_id="星期 (1~7)",
            lesson_start="起始節次 (01~09, A~D)",
            lesson_end="結束節次",
            year="學年（留空自動抓最新）",
            term="學期（1 或 2）",
        )
        async def cmd_classroom(
            interaction: discord.Interaction,
            keyword: str = "",
            week_id: str = "",
            lesson_start: str = "",
            lesson_end: str = "",
            year: str | None = None,
            term: str | None = None,
        ) -> None:
            await interaction.response.defer()
            try:
                res = await self.requester.query_classrooms(
                    year=year,
                    term=term,
                    week_id=week_id,
                    lesson_start=lesson_start,
                    lesson_end=lesson_end,
                    keyword=keyword,
                )
                panel = MainPanelView(self.requester, self.owner_id)
                view = ClassroomView(self.requester, on_back=panel.return_to_main)
                await interaction.followup.send(embed=build_classroom_embed(res), view=view)
            except Exception as exc:
                await interaction.followup.send(
                    embed=discord.Embed(title="❌ 教室查詢失敗", description=str(exc), color=0xE74C3C)
                )

        # === Owner Utility Commands ===
        @tree.command(name="notify", description="管理成績與請假 DM 異動推播通知（僅限擁有者）")
        @app_commands.describe(action="status(檢視狀態) / toggle(開關推播) / check_now(立即檢查並發送DM)")
        async def cmd_notify(
            interaction: discord.Interaction,
            action: Literal["status", "toggle", "check_now"] = "status",
        ) -> None:
            if not await self._require_owner(interaction):
                return
            if action == "toggle":
                cur = bool(self.requester.storage.get_setting("notify_enabled", True))
                self.requester.storage.set_setting("notify_enabled", not cur)
                state = "已開啟" if not cur else "已暫停"
                await interaction.response.send_message(f"🔔 DM 異動推播通知：**{state}**。", ephemeral=True)
                return
            if action == "check_now":
                await interaction.response.defer(ephemeral=True)
                s_changes = await self.requester.check_score_updates()
                l_changes = await self.requester.check_leave_updates()
                if s_changes:
                    await self._send_owner_dm(build_score_notify_embed(s_changes))
                if l_changes:
                    await self._send_owner_dm(build_leave_notify_embed(l_changes))
                await interaction.followup.send(
                    f"✅ 檢查完成：成績異動 `{len(s_changes)}` 筆、請假異動 `{len(l_changes)}` 筆（有異動時已透過 DM 推播）。",
                    ephemeral=True,
                )
                return
            enabled = bool(self.requester.storage.get_setting("notify_enabled", True))
            await interaction.response.send_message(
                f"🔔 DM 推播狀態：**{'開啟中' if enabled else '已暫停'}**｜輪詢間隔：每 `{self.poll_minutes}` 分鐘｜目標：Owner DM (`{self.owner_id}`)",
                ephemeral=True,
            )

        @tree.command(name="auth", description="手動登入、清除本機 Token 或檢視登入狀態（僅限擁有者）")
        async def cmd_auth(
            interaction: discord.Interaction,
            action: Literal["status", "login", "logout"] = "status",
        ) -> None:
            if not await self._require_owner(interaction):
                return
            await interaction.response.defer(ephemeral=True)
            try:
                if action == "logout":
                    await self.requester.logout()
                    await interaction.followup.send("🗑️ 已清除本機登入 Token 與快取。", ephemeral=True)
                    return
                if action == "login":
                    res = await self.requester.login(force=True)
                    name = (res.get("profile") or {}).get("std_CNAME", "同學")
                    await interaction.followup.send(f"✅ 登入成功！歡迎回來，{name}。", ephemeral=True)
                    return
                profile = self.requester.get_profile()
                name = profile.get("std_CNAME") or "尚未登入"
                await interaction.followup.send(
                    f"👤 目前登入狀態：`{name}`｜資料來源：`{self.requester.default_source}`",
                    ephemeral=True,
                )
            except Exception as exc:
                await interaction.followup.send(f"❌ 操作失敗：{exc}", ephemeral=True)
