"""Main interactive control panel (buttons embedded directly under the hub Embed)."""
from __future__ import annotations

import io

import discord

from NptuRequester import NptuRequester
from ui.formatters import (
    build_generic_personal_embed,
    build_main_panel_embed,
    build_schedule_embed,
)
from ui.views_personal import (
    AttendanceView,
    LeaveView,
    RewardAlertView,
    ScheduleView,
    ScoreView,
)
from ui.views_public import (
    ClassroomSearchModal,
    CourseSearchModal,
    LibrarySearchModal,
)


class MainPanelView(discord.ui.View):
    """Unified NPTU Bot control panel: Row 0 = Personal (Owner only), Row 1 = Public (Everyone)."""

    def __init__(self, requester: NptuRequester, owner_id: int | None):
        super().__init__(timeout=600)
        self.requester = requester
        self.owner_id = owner_id

    def _is_owner(self, interaction: discord.Interaction) -> bool:
        return (not self.owner_id) or (interaction.user.id == self.owner_id)

    async def _require_owner(self, interaction: discord.Interaction) -> bool:
        if not self._is_owner(interaction):
            await interaction.response.send_message(
                "🔒 此按鈕為個人校務功能，僅限 Bot 擁有者操作；第二排公開查詢則所有人皆可使用。",
                ephemeral=True,
            )
            return False
        return True

    async def return_to_main(self, interaction: discord.Interaction) -> None:
        notify_enabled = bool(self.requester.storage.get_setting("notify_enabled", True))
        embed = build_main_panel_embed(
            self.requester.get_profile(),
            notify_enabled=notify_enabled,
            source=self.requester.default_source,
        )
        view = MainPanelView(self.requester, self.owner_id)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=view, attachments=[])
        else:
            await interaction.response.edit_message(embed=embed, view=view, attachments=[])

    # === Row 0: Personal Academic (Owner Only) ===
    @discord.ui.button(label="📅 課表", style=discord.ButtonStyle.primary, row=0)
    async def btn_schedule(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._require_owner(interaction):
            return
        await interaction.response.defer()
        try:
            semesters = await self.requester.get_semesters()
            year, term, phase = await self.requester.get_latest_semester()
            res = await self.requester.get_schedule(year, term, phase)
            embed = build_schedule_embed(res, self.requester.get_profile())
            view = ScheduleView(
                self.requester,
                self.owner_id,
                semesters,
                year,
                term,
                phase,
                on_back=self.return_to_main,
            )
            files = []
            if res.get("png_bytes"):
                files.append(discord.File(io.BytesIO(res["png_bytes"]), filename="schedule.png"))
            await interaction.edit_original_response(embed=embed, attachments=files, view=view)
        except Exception as exc:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 載入課表失敗", description=str(exc), color=0xE74C3C),
                view=self,
            )

    @discord.ui.button(label="🎓 成績 & GPA", style=discord.ButtonStyle.primary, row=0)
    async def btn_score(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._require_owner(interaction):
            return
        await interaction.response.defer()
        try:
            semesters = await self.requester.get_semesters()
            year, term, _ = await self.requester.get_latest_semester()
            view = ScoreView(
                self.requester,
                self.owner_id,
                semesters=semesters,
                selected_year=year,
                selected_term=term,
                on_back=self.return_to_main,
                scope="term",
            )
            await view.render(interaction)
        except Exception as exc:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 載入成績失敗", description=str(exc), color=0xE74C3C),
                view=self,
            )

    @discord.ui.button(label="📋 缺曠課", style=discord.ButtonStyle.primary, row=0)
    async def btn_attendance(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._require_owner(interaction):
            return
        view = AttendanceView(self.requester, self.owner_id, on_back=self.return_to_main)
        await view.render(interaction)

    @discord.ui.button(label="📝 請假", style=discord.ButtonStyle.primary, row=0)
    async def btn_leave(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._require_owner(interaction):
            return
        view = LeaveView(self.requester, self.owner_id, on_back=self.return_to_main)
        embed = discord.Embed(
            title="📝 屏大請假管理",
            description="請選擇要查詢目前假單、查看可請假節次、查詢假別代碼，或直接線上申請請假。",
            color=0x2B7DE9,
        )
        await interaction.response.edit_message(embed=embed, view=view, attachments=[])

    @discord.ui.button(label="🏅 獎懲／預警", style=discord.ButtonStyle.primary, row=0)
    async def btn_reward_alert(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._require_owner(interaction):
            return
        await interaction.response.defer()
        view = RewardAlertView(self.requester, self.owner_id, on_back=self.return_to_main)
        try:
            data = await self.requester.get_rewards()
            embed = build_generic_personal_embed("🏅 個人獎懲紀錄", data, "目前查無獎懲紀錄。")
            await interaction.edit_original_response(embed=embed, view=view, attachments=[])
        except Exception as exc:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 查詢失敗", description=str(exc), color=0xE74C3C),
                view=view,
            )

    # === Row 1: Public No-Login Queries (Everyone) ===
    @discord.ui.button(label="📚 課程查詢", style=discord.ButtonStyle.success, row=1)
    async def btn_public_course(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(CourseSearchModal(self.requester, on_back=self.return_to_main))

    @discord.ui.button(label="📖 圖書查詢", style=discord.ButtonStyle.success, row=1)
    async def btn_public_library(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(LibrarySearchModal(self.requester, on_back=self.return_to_main))

    @discord.ui.button(label="🏫 教室查詢", style=discord.ButtonStyle.success, row=1)
    async def btn_public_classroom(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(ClassroomSearchModal(self.requester, on_back=self.return_to_main))

    @discord.ui.button(label="🔔 切換DM推播", style=discord.ButtonStyle.secondary, row=1)
    async def btn_toggle_notify(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._require_owner(interaction):
            return
        current = bool(self.requester.storage.get_setting("notify_enabled", True))
        self.requester.storage.set_setting("notify_enabled", not current)
        await self.return_to_main(interaction)
