"""Interactive Discord Views and Modals for personal NPTU features (Owner-only)."""
from __future__ import annotations

import io
from typing import Any, Callable, Coroutine

import discord

from application.constants import PHASE_MAP
from NptuRequester import AttendanceFilter, NptuRequester, ScopeType
from ui.formatters import (
    build_attendance_records_embed,
    build_attendance_stats_embed,
    build_generic_personal_embed,
    build_schedule_embed,
    build_scores_embed,
)

BackCallback = Callable[[discord.Interaction], Coroutine[Any, Any, None]]


class OwnerGuardView(discord.ui.View):
    """Base View restricting interactions to the configured Discord Owner."""

    def __init__(self, owner_id: int | None, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.owner_id and interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "🔒 此面板為個人校務功能，僅限 Bot 擁有者操作。",
                ephemeral=True,
            )
            return False
        return True


class AttendanceView(OwnerGuardView):
    """Switch between Statistics/Records, Scope (學期/學年/在學), and Filter (全部/請假/曠課)."""

    def __init__(
        self,
        requester: NptuRequester,
        owner_id: int | None,
        on_back: BackCallback | None = None,
        *,
        mode: str = "stats",
        scope: ScopeType = "term",
        record_filter: AttendanceFilter = "all",
    ):
        super().__init__(owner_id)
        self.requester = requester
        self.on_back = on_back
        self.mode = mode
        self.scope: ScopeType = scope
        self.record_filter: AttendanceFilter = record_filter
        self.page = 0
        self._last_result: dict[str, Any] | None = None

    async def render(self, interaction: discord.Interaction, *, force_refresh: bool = False) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()
        try:
            if self.mode == "stats":
                res = await self.requester.get_attendance_statistics(self.scope, force_refresh=force_refresh)
                self._last_result = res
                embed = build_attendance_stats_embed(res)
            else:
                res = await self.requester.get_attendance_records(
                    self.scope, self.record_filter, force_refresh=force_refresh
                )
                self._last_result = res
                embed = build_attendance_records_embed(res, page=self.page)
            await interaction.edit_original_response(embed=embed, view=self, attachments=[])
        except Exception as exc:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 查詢缺曠課失敗", description=str(exc), color=0xE74C3C),
                view=self,
            )

    @discord.ui.button(label="統計", style=discord.ButtonStyle.primary, row=0)
    async def btn_stats(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.mode = "stats"
        await self.render(interaction)

    @discord.ui.button(label="紀錄", style=discord.ButtonStyle.primary, row=0)
    async def btn_records(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.mode = "records"
        self.page = 0
        await self.render(interaction)

    @discord.ui.button(label="本學期", style=discord.ButtonStyle.secondary, row=0)
    async def btn_term(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.scope = "term"
        self.page = 0
        await self.render(interaction)

    @discord.ui.button(label="本學年", style=discord.ButtonStyle.secondary, row=0)
    async def btn_year(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.scope = "year"
        self.page = 0
        await self.render(interaction)

    @discord.ui.button(label="在學期間", style=discord.ButtonStyle.secondary, row=0)
    async def btn_all(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.scope = "all"
        self.page = 0
        await self.render(interaction)

    @discord.ui.button(label="全部", style=discord.ButtonStyle.success, row=1)
    async def btn_filter_all(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.mode = "records"
        self.record_filter = "all"
        self.page = 0
        await self.render(interaction)

    @discord.ui.button(label="僅請假", style=discord.ButtonStyle.success, row=1)
    async def btn_filter_leave(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.mode = "records"
        self.record_filter = "leave"
        self.page = 0
        await self.render(interaction)

    @discord.ui.button(label="僅曠課", style=discord.ButtonStyle.danger, row=1)
    async def btn_filter_absent(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.mode = "records"
        self.record_filter = "absent"
        self.page = 0
        await self.render(interaction)

    @discord.ui.button(label="◀ 上頁", style=discord.ButtonStyle.secondary, row=2)
    async def btn_prev(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.mode == "records" and self._last_result and self.page > 0:
            self.page -= 1
            await interaction.response.edit_message(
                embed=build_attendance_records_embed(self._last_result, page=self.page),
                view=self,
            )
        else:
            await interaction.response.defer()

    @discord.ui.button(label="下頁 ▶", style=discord.ButtonStyle.secondary, row=2)
    async def btn_next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.mode == "records" and self._last_result:
            total = len(self._last_result.get("records") or [])
            if (self.page + 1) * 10 < total:
                self.page += 1
                await interaction.response.edit_message(
                    embed=build_attendance_records_embed(self._last_result, page=self.page),
                    view=self,
                )
                return
        await interaction.response.defer()

    @discord.ui.button(label="🏠 返回主控台", style=discord.ButtonStyle.secondary, row=2)
    async def btn_back(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.on_back:
            await self.on_back(interaction)
        else:
            await interaction.response.defer()


class ScoreView(OwnerGuardView):
    """Switch score statistics across 學期 / 學年 / 在學期間 with official NPTU 4.0 GPA."""

    def __init__(
        self,
        requester: NptuRequester,
        owner_id: int | None,
        on_back: BackCallback | None = None,
        *,
        scope: ScopeType = "term",
    ):
        super().__init__(owner_id)
        self.requester = requester
        self.on_back = on_back
        self.scope: ScopeType = scope

    async def render(self, interaction: discord.Interaction, *, force_refresh: bool = False) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()
        try:
            res = await self.requester.get_scores(self.scope, force_refresh=force_refresh)
            embed = build_scores_embed(res, self.requester.get_profile())
            await interaction.edit_original_response(embed=embed, view=self, attachments=[])
        except Exception as exc:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 查詢成績失敗", description=str(exc), color=0xE74C3C),
                view=self,
            )

    @discord.ui.button(label="本學期", style=discord.ButtonStyle.primary, row=0)
    async def btn_term(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.scope = "term"
        await self.render(interaction)

    @discord.ui.button(label="本學年", style=discord.ButtonStyle.primary, row=0)
    async def btn_year(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.scope = "year"
        await self.render(interaction)

    @discord.ui.button(label="在學期間", style=discord.ButtonStyle.primary, row=0)
    async def btn_all(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.scope = "all"
        await self.render(interaction)

    @discord.ui.button(label="🔄 重新抓取", style=discord.ButtonStyle.secondary, row=0)
    async def btn_refresh(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.render(interaction, force_refresh=True)

    @discord.ui.button(label="🏠 返回主控台", style=discord.ButtonStyle.secondary, row=1)
    async def btn_back(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.on_back:
            await self.on_back(interaction)
        else:
            await interaction.response.defer()


class ScheduleView(OwnerGuardView):
    """Select semester & phase to render high-res schedule PNG."""

    def __init__(
        self,
        requester: NptuRequester,
        owner_id: int | None,
        semesters: list[dict[str, Any]],
        selected_year: str,
        selected_term: str,
        selected_phase: str,
        on_back: BackCallback | None = None,
    ):
        super().__init__(owner_id)
        self.requester = requester
        self.on_back = on_back
        self.year = selected_year
        self.term = selected_term
        self.phase = selected_phase

        # Semester dropdown (max 25 options)
        sem_options: list[discord.SelectOption] = []
        for s in semesters[:25]:
            sy = str(s.get("syear") or "")
            sm = str(s.get("seme") or "")
            if not sy or not sm:
                continue
            label = str(s.get("syse_TXT") or f"{sy} 學年第 {sm} 學期")
            sem_options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=f"{sy}:{sm}",
                    default=(sy == selected_year and sm == selected_term),
                )
            )
        if sem_options:
            sem_select = discord.ui.Select(placeholder="選擇學期...", options=sem_options, row=0)
            sem_select.callback = self._on_semester_change
            self.add_item(sem_select)

        phase_options = [
            discord.SelectOption(label=f"{k} - {v}", value=k, default=(k == selected_phase))
            for k, v in PHASE_MAP.items()
            if k in {"1", "2", "3", "4"}
        ]
        phase_select = discord.ui.Select(placeholder="選擇選課階段...", options=phase_options, row=1)
        phase_select.callback = self._on_phase_change
        self.add_item(phase_select)

    async def _render_schedule(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()
        try:
            res = await self.requester.get_schedule(self.year, self.term, self.phase)
            embed = build_schedule_embed(res, self.requester.get_profile())
            files = []
            if res.get("png_bytes"):
                files.append(discord.File(io.BytesIO(res["png_bytes"]), filename="schedule.png"))
            await interaction.edit_original_response(embed=embed, attachments=files, view=self)
        except Exception as exc:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 繪製課表失敗", description=str(exc), color=0xE74C3C),
                attachments=[],
                view=self,
            )

    async def _on_semester_change(self, interaction: discord.Interaction) -> None:
        val = interaction.data["values"][0]
        self.year, self.term = val.split(":", 1)
        await self._render_schedule(interaction)

    async def _on_phase_change(self, interaction: discord.Interaction) -> None:
        self.phase = interaction.data["values"][0]
        await self._render_schedule(interaction)

    @discord.ui.button(label="🏠 返回主控台", style=discord.ButtonStyle.secondary, row=2)
    async def btn_back(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.on_back:
            await self.on_back(interaction)
        else:
            await interaction.response.defer()


class LeaveConfirmView(OwnerGuardView):
    """Explicit confirmation step before calling mutating askLeave endpoint."""

    def __init__(
        self,
        requester: NptuRequester,
        owner_id: int | None,
        payload: dict[str, str],
    ):
        super().__init__(owner_id, timeout=120)
        self.requester = requester
        self.payload = payload

    @discord.ui.button(label="✅ 確認送出請假單", style=discord.ButtonStyle.danger)
    async def btn_confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        try:
            res = await self.requester.submit_leave(
                excuse_date=self.payload["excuse_date"],
                lesson_ids=self.payload["lesson_ids"],
                excuse_id=self.payload["excuse_id"],
                reason=self.payload["reason"],
            )
            embed = build_generic_personal_embed("✅ 請假申請已送出", res, "無回應內容")
            await interaction.edit_original_response(embed=embed, view=None)
        except Exception as exc:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 請假送出失敗", description=str(exc), color=0xE74C3C),
                view=None,
            )

    @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary)
    async def btn_cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=discord.Embed(title="已取消請假申請", color=0x95A5A6),
            view=None,
        )


class LeaveApplyModal(discord.ui.Modal, title="📝 填寫屏大請假申請"):
    excuse_date = discord.ui.TextInput(label="請假日期 (YYYY/MM/DD 或系統格式)", placeholder="例如：2026/11/25", required=True)
    lesson_ids = discord.ui.TextInput(label="節次代碼 (多節以逗號分隔)", placeholder="例如：01,02 或 03", required=True)
    excuse_id = discord.ui.TextInput(label="假別代碼 (可先點「假別代碼」查詢)", placeholder="例如：01 (事假) / 02 (病假)", required=True)
    reason = discord.ui.TextInput(label="請假事由", style=discord.TextStyle.paragraph, placeholder="請簡述請假原因...", required=True)

    def __init__(self, requester: NptuRequester, owner_id: int | None):
        super().__init__()
        self.requester = requester
        self.owner_id = owner_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        payload = {
            "excuse_date": str(self.excuse_date.value).strip(),
            "lesson_ids": str(self.lesson_ids.value).strip(),
            "excuse_id": str(self.excuse_id.value).strip(),
            "reason": str(self.reason.value).strip(),
        }
        embed = discord.Embed(
            title="⚠️ 請確認請假申請內容",
            description=(
                f"• **日期**：`{payload['excuse_date']}`\n"
                f"• **節次**：`{payload['lesson_ids']}`\n"
                f"• **假別代碼**：`{payload['excuse_id']}`\n"
                f"• **事由**：{payload['reason']}"
            ),
            color=0xF39C12,
        )
        await interaction.response.send_message(
            embed=embed,
            view=LeaveConfirmView(self.requester, self.owner_id, payload),
            ephemeral=True,
        )


class LeaveView(OwnerGuardView):
    """Leave management hub: Query records, view askable slots, view leave codes, submit application."""

    def __init__(
        self,
        requester: NptuRequester,
        owner_id: int | None,
        on_back: BackCallback | None = None,
    ):
        super().__init__(owner_id)
        self.requester = requester
        self.on_back = on_back

    @discord.ui.button(label="📋 查詢假單", style=discord.ButtonStyle.primary, row=0)
    async def btn_query(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        try:
            res = await self.requester.get_attendance_records("term", "leave")
            await interaction.edit_original_response(embed=build_attendance_records_embed(res), view=self, attachments=[])
        except Exception as exc:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 查詢假單失敗", description=str(exc), color=0xE74C3C),
                view=self,
            )

    @discord.ui.button(label="🗓️ 可請假節次", style=discord.ButtonStyle.secondary, row=0)
    async def btn_ask_list(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        try:
            rows = await self.requester.get_leave_ask_list()
            embed = build_generic_personal_embed("🗓️ 目前可申請請假節次", rows, "目前沒有可請假的節次紀錄。")
            await interaction.edit_original_response(embed=embed, view=self, attachments=[])
        except Exception as exc:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 取得可請假節次失敗", description=str(exc), color=0xE74C3C),
                view=self,
            )

    @discord.ui.button(label="📖 假別代碼", style=discord.ButtonStyle.secondary, row=0)
    async def btn_basic_data(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        try:
            data = await self.requester.get_leave_basic_data()
            embed = build_generic_personal_embed("📖 屏大假別基本代碼表", data, "查無假別代碼資料。")
            await interaction.edit_original_response(embed=embed, view=self, attachments=[])
        except Exception as exc:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 取得假別代碼失敗", description=str(exc), color=0xE74C3C),
                view=self,
            )

    @discord.ui.button(label="📝 申請請假", style=discord.ButtonStyle.success, row=0)
    async def btn_apply(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(LeaveApplyModal(self.requester, self.owner_id))

    @discord.ui.button(label="🏠 返回主控台", style=discord.ButtonStyle.secondary, row=1)
    async def btn_back(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.on_back:
            await self.on_back(interaction)
        else:
            await interaction.response.defer()


class RewardAlertView(OwnerGuardView):
    """Toggle between personal Rewards and Academic Score Alerts."""

    def __init__(
        self,
        requester: NptuRequester,
        owner_id: int | None,
        on_back: BackCallback | None = None,
    ):
        super().__init__(owner_id)
        self.requester = requester
        self.on_back = on_back

    @discord.ui.button(label="🏅 個人獎懲", style=discord.ButtonStyle.primary)
    async def btn_reward(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        try:
            data = await self.requester.get_rewards()
            embed = build_generic_personal_embed("🏅 個人獎懲紀錄", data, "目前查無獎懲紀錄。")
            await interaction.edit_original_response(embed=embed, view=self, attachments=[])
        except Exception as exc:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 查詢獎懲失敗", description=str(exc), color=0xE74C3C),
                view=self,
            )

    @discord.ui.button(label="⚠️ 學習預警", style=discord.ButtonStyle.danger)
    async def btn_alert(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        try:
            res = await self.requester.get_score_alerts()
            embed = build_generic_personal_embed(
                f"⚠️ 學習預警紀錄（{res['year']}-{res['term']}）",
                res["data"],
                "本學期無學習預警紀錄！",
            )
            await interaction.edit_original_response(embed=embed, view=self, attachments=[])
        except Exception as exc:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 查詢學習預警失敗", description=str(exc), color=0xE74C3C),
                view=self,
            )

    @discord.ui.button(label="🏠 返回主控台", style=discord.ButtonStyle.secondary)
    async def btn_back(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.on_back:
            await self.on_back(interaction)
        else:
            await interaction.response.defer()
