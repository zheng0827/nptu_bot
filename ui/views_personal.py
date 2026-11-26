"""Interactive Discord Views and Modals for personal NPTU features (Owner-only)."""
from __future__ import annotations

import io
from typing import Any, Callable, Coroutine

import discord

from application.constants import (
    LEAVE_LESSON_NAME_TO_ID,
    LEAVE_NAME_TO_ID,
    LEAVE_TYPE_MAP,
    PHASE_MAP,
)
from NptuRequester import AttendanceFilter, NptuRequester, ScopeType
from ui.formatters import (
    build_attendance_records_embed,
    build_attendance_stats_embed,
    build_generic_personal_embed,
    build_leave_ask_list_embed,
    build_leave_basic_data_embed,
    build_schedule_embed,
    build_score_trend_embed,
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
    """Select specific semester or academic year, view full history, or render average trend line chart."""

    def __init__(
        self,
        requester: NptuRequester,
        owner_id: int | None,
        semesters: list[dict[str, Any]] | None = None,
        selected_year: str | None = None,
        selected_term: str | None = None,
        on_back: BackCallback | None = None,
        *,
        scope: ScopeType | str = "term",
    ):
        super().__init__(owner_id)
        self.requester = requester
        self.on_back = on_back
        self.semesters = semesters or []
        self.year = selected_year
        self.term = selected_term
        self.scope: str = scope

        # Row 0: Select specific semester (just like ScheduleView)
        sem_options: list[discord.SelectOption] = []
        seen_sem: set[tuple[str, str]] = set()
        for s in self.semesters[:25]:
            sy = str(s.get("syear") or "").strip()
            sm = str(s.get("seme") or "").strip()
            if not sy or not sm or (sy, sm) in seen_sem:
                continue
            seen_sem.add((sy, sm))
            label = str(s.get("syse_TXT") or (f"{sy}學年暑期" if sm == "3" else f"{sy}學年第{sm}學期"))
            sem_options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=f"{sy}:{sm}",
                    default=(self.scope == "term" and sy == self.year and sm == self.term),
                )
            )
        if sem_options:
            self._sem_select = discord.ui.Select(placeholder="選擇指定學期...", options=sem_options, row=0)
            self._sem_select.callback = self._on_semester_change
            self.add_item(self._sem_select)
        else:
            self._sem_select = None

        # Row 1: Select specific academic year
        year_options: list[discord.SelectOption] = []
        seen_years: set[str] = set()
        for s in self.semesters:
            sy = str(s.get("syear") or "").strip()
            if not sy or sy in seen_years:
                continue
            seen_years.add(sy)
            year_options.append(
                discord.SelectOption(
                    label=f"{sy} 學年度",
                    value=sy,
                    default=(self.scope == "year" and sy == self.year),
                )
            )
            if len(year_options) >= 25:
                break
        if year_options:
            self._year_select = discord.ui.Select(placeholder="選擇指定學年...", options=year_options, row=1)
            self._year_select.callback = self._on_year_change
            self.add_item(self._year_select)
        else:
            self._year_select = None

    def _sync_select_defaults(self) -> None:
        if self._sem_select:
            for opt in self._sem_select.options:
                opt.default = self.scope == "term" and opt.value == f"{self.year}:{self.term}"
        if self._year_select:
            for opt in self._year_select.options:
                opt.default = self.scope == "year" and opt.value == str(self.year or "")

    async def render(self, interaction: discord.Interaction, *, force_refresh: bool = False) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()
        self._sync_select_defaults()
        try:
            if self.scope == "trend":
                res = await self.requester.get_score_trend(force_refresh=force_refresh)
                embed = build_score_trend_embed(res, self.requester.get_profile())
                files = []
                if res.get("png_bytes"):
                    files.append(discord.File(io.BytesIO(res["png_bytes"]), filename="score_trend.png"))
                await interaction.edit_original_response(embed=embed, attachments=files, view=self)
                return

            res = await self.requester.get_scores(
                self.scope,  # type: ignore[arg-type]
                year=self.year if self.scope in {"term", "year"} else None,
                term=self.term if self.scope == "term" else None,
                force_refresh=force_refresh,
            )
            embed = build_scores_embed(res, self.requester.get_profile())
            await interaction.edit_original_response(embed=embed, attachments=[], view=self)
        except Exception as exc:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 查詢成績失敗", description=str(exc), color=0xE74C3C),
                attachments=[],
                view=self,
            )

    async def _on_semester_change(self, interaction: discord.Interaction) -> None:
        val = interaction.data["values"][0]
        self.year, self.term = val.split(":", 1)
        self.scope = "term"
        await self.render(interaction)

    async def _on_year_change(self, interaction: discord.Interaction) -> None:
        self.year = interaction.data["values"][0]
        self.scope = "year"
        await self.render(interaction)

    @discord.ui.button(label="📊 在學期間總覽", style=discord.ButtonStyle.primary, row=2)
    async def btn_all(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.scope = "all"
        await self.render(interaction)

    @discord.ui.button(label="📈 學期平均折線圖", style=discord.ButtonStyle.success, row=2)
    async def btn_trend(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.scope = "trend"
        await self.render(interaction)

    @discord.ui.button(label="🔄 重新抓取", style=discord.ButtonStyle.secondary, row=2)
    async def btn_refresh(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.render(interaction, force_refresh=True)

    @discord.ui.button(label="🏠 返回主控台", style=discord.ButtonStyle.secondary, row=2)
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


def _normalize_excuse_date(raw: str) -> str:
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) != 8:
        raise ValueError(f"日期格式須為 8 碼西元年月日（YYYYMMDD），收到：{raw!r}")
    return digits


def _normalize_excuse_id(raw: str) -> str:
    key = raw.strip().upper()
    return LEAVE_NAME_TO_ID.get(raw.strip(), LEAVE_NAME_TO_ID.get(key, key))


def _normalize_lesson_ids(raw: str) -> str:
    parts = [p.strip().upper() for p in raw.replace("，", ",").split(",") if p.strip()]
    if not parts:
        raise ValueError("請至少輸入一個節次（例如：01,02 或 M,N）。")
    mapped = [LEAVE_LESSON_NAME_TO_ID.get(p, p) for p in parts]
    return ",".join(mapped)


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
            if isinstance(res, dict) and res.get("result") is False:
                data = res.get("data") if isinstance(res.get("data"), dict) else {}
                code = data.get("errorCode", "unknown")
                desc = data.get("errorDescription") or res.get("reason") or "請假申請遭伺服器拒絕"
                embed = discord.Embed(
                    title="❌ 請假申請失敗",
                    description=f"錯誤代碼：`{code}`\n說明：{desc}",
                    color=0xE74C3C,
                )
                embed.set_footer(text="詳細回應已存至 temp_data/")
                await interaction.edit_original_response(embed=embed, view=None)
                return

            embed = discord.Embed(
                title="✅ 請假申請已送出成功",
                description=(
                    f"• **日期**：`{self.payload['excuse_date']}`\n"
                    f"• **節次代碼**：`{self.payload['lesson_ids']}`\n"
                    f"• **假別**：`{LEAVE_TYPE_MAP.get(self.payload['excuse_id'], self.payload['excuse_id'])}`\n"
                    f"• **事由**：{self.payload['reason']}"
                ),
                color=0x2ECC71,
            )
            embed.set_footer(text="詳細回應已存至 temp_data/")
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
    excuse_date = discord.ui.TextInput(
        label="請假日期 (YYYYMMDD 或 YYYY/MM/DD)",
        placeholder="例如：20261125（系統會自動轉為 8 碼）",
        required=True,
    )
    lesson_ids = discord.ui.TextInput(
        label="請假節次 (輸入節次名稱或代碼，逗號分隔)",
        placeholder="例如：01,02 或 M,N,09,A（自動轉系統代碼）",
        required=True,
    )
    excuse_id = discord.ui.TextInput(
        label="假別 (輸入中文或代碼：B事假 / C病假 / J生理假)",
        placeholder="例如：事假 / 病假 / 生理假 或 B / C / J",
        required=True,
    )
    reason = discord.ui.TextInput(
        label="請假事由",
        style=discord.TextStyle.paragraph,
        placeholder="請簡述請假原因...",
        required=True,
    )

    def __init__(self, requester: NptuRequester, owner_id: int | None):
        super().__init__()
        self.requester = requester
        self.owner_id = owner_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            norm_date = _normalize_excuse_date(str(self.excuse_date.value))
            norm_lessons = _normalize_lesson_ids(str(self.lesson_ids.value))
            norm_excuse = _normalize_excuse_id(str(self.excuse_id.value))
        except ValueError as exc:
            await interaction.response.send_message(f"⚠️ 輸入格式有誤：{exc}", ephemeral=True)
            return

        payload = {
            "excuse_date": norm_date,
            "lesson_ids": norm_lessons,
            "excuse_id": norm_excuse,
            "reason": str(self.reason.value).strip(),
        }
        excuse_label = LEAVE_TYPE_MAP.get(norm_excuse, norm_excuse)
        embed = discord.Embed(
            title="⚠️ 請確認請假申請內容",
            description=(
                f"• **日期**：`{norm_date}`\n"
                f"• **節次（已轉系統代碼）**：`{self.lesson_ids.value.strip()}` → `{norm_lessons}`\n"
                f"• **假別**：`{excuse_label}` (`{norm_excuse}`)\n"
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
    """Leave management hub: Query records, view ask list, view leave codes, submit application."""

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

    @discord.ui.button(label="🗓️ 線上請假單", style=discord.ButtonStyle.secondary, row=0)
    async def btn_ask_list(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        try:
            rows = await self.requester.get_leave_ask_list()
            embed = build_leave_ask_list_embed(rows)
            await interaction.edit_original_response(embed=embed, view=self, attachments=[])
        except Exception as exc:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 取得線上請假單失敗", description=str(exc), color=0xE74C3C),
                view=self,
            )

    @discord.ui.button(label="📖 假別代碼", style=discord.ButtonStyle.secondary, row=0)
    async def btn_basic_data(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        try:
            data = await self.requester.get_leave_basic_data()
            embed = build_leave_basic_data_embed(data)
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
