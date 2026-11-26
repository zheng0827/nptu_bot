"""Embed builders and safe formatters for both known and unknown NPTU API schemas."""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

import discord

from application.constants import PHASE_MAP, WEEK_MAP
from core.gpa import ScoreSummary, score_to_grade

COLOR_PRIMARY = 0x2B7DE9
COLOR_SUCCESS = 0x2ECC71
COLOR_WARNING = 0xF39C12
COLOR_DANGER = 0xE74C3C
COLOR_PUBLIC = 0x1ABC9C


def _truncate(text: str, limit: int = 1000) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _pick(d: Mapping[str, Any], *keys: str, default: str = "-") -> str:
    for k in keys:
        val = d.get(k)
        if val not in (None, ""):
            return str(val).strip()
    return default


def _format_generic_item(item: Any) -> str:
    """Render an unknown dict/list cleanly without assuming exact field names."""
    if isinstance(item, Mapping):
        parts = []
        for k, v in item.items():
            if str(k).startswith("_") or v in (None, "", [], {}):
                continue
            parts.append(f"{k}: {v}")
            if len(parts) >= 6:
                break
        return " | ".join(parts) if parts else json.dumps(item, ensure_ascii=False)
    return str(item)


def build_main_panel_embed(profile: Mapping[str, Any], notify_enabled: bool, source: str) -> discord.Embed:
    student_name = _pick(profile, "std_CNAME", "name", default="尚未登入（操作個人功能時自動登入）")
    embed = discord.Embed(
        title="🏛️ 行動屏大 Discord 校務中控台",
        description=(
            "點擊下方按鈕即可在面板內切換功能，或直接使用 `/` 斜線指令。\n"
            "• **第一排（個人校務）**：僅限 Bot 擁有者操作\n"
            "• **第二排（公開免登入）**：所有人皆可查詢"
        ),
        color=COLOR_PRIMARY,
    )
    embed.add_field(name="👤 目前帳號", value=student_name, inline=True)
    embed.add_field(name="🔌 資料來源", value=f"`{source}`", inline=True)
    embed.add_field(name="🔔 DM 異動推播", value="開啟中" if notify_enabled else "已暫停", inline=True)
    embed.set_footer(text="所有抓回的原始 API 物件皆會自動保存至 temp_data/ 供檢視資料結構")
    return embed


def _parse_sco_avg(raw: str) -> dict[str, str]:
    """Extract 班級名次 and 操行成績 from NPTU sco_AVG summary text."""
    import re

    out: dict[str, str] = {}
    if not raw:
        return out
    m_rank = re.search(r"班級名次[：:]\s*([^\s]+)", raw)
    if m_rank:
        out["rank"] = m_rank.group(1).strip()
    m_conduct = re.search(r"操行成績[：:]\s*([^\s]+)", raw)
    if m_conduct:
        out["conduct"] = m_conduct.group(1).strip()
    m_avg = re.search(r"學業平均[：:]\s*([^\s]+)", raw)
    if m_avg:
        out["avg"] = m_avg.group(1).strip()
    return out


def build_scores_embed(result: Mapping[str, Any], profile: Mapping[str, Any]) -> discord.Embed:
    summary: ScoreSummary = result["summary"]
    records: Sequence[Mapping[str, Any]] = result["records"]
    label: str = result["label"]
    scope: str = str(result.get("scope") or "term")

    gpa_text = f"**{summary.gpa:.2f}** / 4.00" if summary.gpa is not None else "尚無可採計成績"
    avg_text = f"**{summary.weighted_score_avg:.2f}**" if summary.weighted_score_avg is not None else "-"
    dist_parts = [f"{g}:{summary.grade_counts.get(g, 0)}" for g in ("A", "B", "C", "D", "E", "X")]

    desc_lines = [
        f"• **屏大 4.0 GPA**：{gpa_text}",
        f"• **加權平均**：{avg_text}",
        f"• **學分**：實得 `{summary.earned_credits:g}` / 修習 `{summary.attempted_credits:g}`（共 `{summary.total_courses}` 門）",
        f"• **等第分布**：`{' | '.join(dist_parts)}`",
    ]

    # Collect per-semester conduct & rank from sco_AVG
    sem_meta: dict[tuple[str, str], dict[str, str]] = {}
    for rec in records:
        y = str(rec.get("_year") or rec.get("syear") or "").strip()
        t = str(rec.get("_term") or rec.get("seme") or "").strip()
        sco_avg = str(rec.get("sco_AVG") or "").strip()
        if y and t and sco_avg and (y, t) not in sem_meta:
            parsed = _parse_sco_avg(sco_avg)
            if parsed:
                sem_meta[(y, t)] = parsed

    if scope != "term" and sem_meta:
        def _sk(pair: tuple[str, str]) -> tuple[int, int]:
            try:
                return (int(pair[0]), int(pair[1]))
            except ValueError:
                return (0, 0)

        conduct_parts: list[str] = []
        for (y, t) in sorted(sem_meta.keys(), key=_sk):
            info = sem_meta[(y, t)]
            sem_lbl = f"{y}-暑" if t == "3" else f"{y}-{t}"
            piece = f"`{sem_lbl}` 操行 **{info.get('conduct', '-')}**"
            if info.get("rank"):
                piece += f"（名次 {info['rank']}）"
            conduct_parts.append(piece)
        desc_lines.append("• **各學期操行**：" + " ｜ ".join(conduct_parts))

    embed = discord.Embed(
        title=f"🎓 成績統計 — {label}",
        description=_truncate("\n".join(desc_lines), 3900),
        color=COLOR_PRIMARY,
    )
    student_name = _pick(profile, "std_CNAME", default="")
    if student_name and student_name != "-":
        embed.set_author(name=student_name)

    if not records:
        embed.add_field(name="📭 查無紀錄", value="此範圍內目前沒有成績資料。", inline=False)
        return embed

    # Show up to 18 courses in embed fields to stay well within Discord's 25-field & 6000-char limits
    for rec in records[:18]:
        subj = _pick(rec, "subj_CN", "subj_CNAME", default="未命名科目")
        subj_id = _pick(rec, "subj_ID", default="")
        raw_score = rec.get("score")
        score_txt = str(rec.get("score_TXT") or "").strip()
        grade = score_to_grade(raw_score)
        if score_txt:
            score_display = f"{score_txt}({grade.letter})" if grade else score_txt
        elif raw_score not in (None, ""):
            raw_clean = str(raw_score).strip()
            if raw_clean.endswith(".0"):
                raw_clean = raw_clean[:-2]
            score_display = f"{raw_clean}({grade.letter})" if grade else raw_clean
        else:
            score_display = "尚未結算"

        credits = _pick(rec, "credits", default="-")
        if credits.endswith(".0"):
            credits = credits[:-2]
        course_type = _pick(rec, "course_CNAME", default="")
        must_txt = _pick(rec, "must_TXT", default="")
        cat_txt = f"{course_type}/{must_txt}" if course_type != "-" and must_txt != "-" else ""
        term_tag = f"{rec.get('_year', '')}-{rec.get('_term', '')} " if scope != "term" else ""

        val_line = f"成績：`{score_display}`\n學分：`{credits}`"
        if cat_txt:
            val_line += f" | `{cat_txt}`"

        embed.add_field(
            name=_truncate(f"📘 {term_tag}{subj} ({subj_id})", 200),
            value=val_line,
            inline=True,
        )

    footer_parts: list[str] = []
    if scope == "term" and sem_meta:
        info = next(iter(sem_meta.values()))
        if info.get("rank"):
            footer_parts.append(f"班級名次：{info['rank']}")
        if info.get("conduct"):
            footer_parts.append(f"操行成績：{info['conduct']}")
    if len(records) > 18:
        footer_parts.append(f"僅顯示前 18 筆（共 {len(records)} 筆）")
    if footer_parts:
        embed.set_footer(text=" ｜ ".join(footer_parts))
    return embed


def build_score_trend_embed(result: Mapping[str, Any], profile: Mapping[str, Any]) -> discord.Embed:
    overall: ScoreSummary = result["overall"]
    points: Sequence[Mapping[str, Any]] = result.get("points") or []

    gpa_text = f"**{overall.gpa:.2f}** / 4.00" if overall.gpa is not None else "-"
    avg_text = f"**{overall.weighted_score_avg:.2f}**" if overall.weighted_score_avg is not None else "-"

    lines = [
        f"• **總加權平均**：{avg_text}｜**總 GPA**：{gpa_text}",
        f"• **累積實得學分**：`{overall.earned_credits:g}` / `{overall.attempted_credits:g}`",
    ]
    if points:
        summary_rows = []
        for p in points:
            row = f"`{p['label']}`：平均 **{p['avg']:.2f}**"
            extra: list[str] = []
            if p.get("gpa") is not None:
                extra.append(f"GPA {p['gpa']:.2f}")
            if p.get("conduct"):
                extra.append(f"操行 {p['conduct']}")
            if p.get("rank"):
                extra.append(f"名次 {p['rank']}")
            if extra:
                row += f"（{' / '.join(extra)}）"
            summary_rows.append(row)
        lines.append("\n" + "\n".join(summary_rows))

    embed = discord.Embed(
        title="📈 歷年學期成績平均趨勢折線圖",
        description=_truncate("\n".join(lines), 3900),
        color=COLOR_PRIMARY,
    )
    student_name = _pick(profile, "std_CNAME", default="")
    if student_name and student_name != "-":
        embed.set_author(name=student_name)
    if result.get("png_bytes"):
        embed.set_image(url="attachment://score_trend.png")
    else:
        embed.add_field(name="📭 尚無資料", value="目前沒有已結算的學期成績可繪製折線圖。", inline=False)
    embed.set_footer(text="僅統計已有結算成績之學期；可透過上方選單切換檢視單一學期或學年明細")
    return embed


def build_attendance_stats_embed(result: Mapping[str, Any]) -> discord.Embed:
    totals: Mapping[str, float] = result.get("totals") or {}
    courses: Sequence[Mapping[str, Any]] = result.get("courses") or []
    embed = discord.Embed(
        title=f"📊 缺曠課統計 — {result['label']}",
        color=COLOR_WARNING,
    )
    if totals:
        lines = [f"• **{k}**：`{v:g}`" for k, v in totals.items()]
        embed.description = _truncate("\n".join(lines), 3800)
    else:
        embed.description = "📭 此範圍內查無缺曠課統計紀錄。"

    if courses:
        # Sort so courses with leave or absence appear first
        ordered = sorted(
            courses,
            key=lambda c: (float(c.get("abwol_HOURS", 0)) + float(c.get("leave_HOURS", 0))),
            reverse=True,
        )
        c_lines: list[str] = []
        for c in ordered[:15]:
            sem_tag = f"[{c.get('syear', '')}-{c.get('seme', '')}] " if result.get("scope") != "term" else ""
            lh = float(c.get("leave_HOURS", 0))
            ah = float(c.get("abwol_HOURS", 0))
            th = float(c.get("subj_TOTAL_HOURS", 0))
            warn = " ⚠️" if ah > 0 else ""
            c_lines.append(
                f"• {sem_tag}**{c.get('subj_CNAME', '-')}**：請假 `{lh:g}` 節｜曠課 `{ah:g}` 節（總時數 `{th:g}`）{warn}"
            )
        embed.add_field(name="📚 各科缺曠明細", value=_truncate("\n".join(c_lines), 1000), inline=False)

    embed.set_footer(text=f"涵蓋學期數：{len(result.get('semesters', []))} | 原始結構已存至 temp_data/")
    return embed


def build_attendance_records_embed(result: Mapping[str, Any], page: int = 0, page_size: int = 10) -> discord.Embed:
    filter_label = {"all": "全部", "leave": "請假", "absent": "曠課"}.get(result.get("filter", "all"), "全部")
    records: Sequence[Mapping[str, Any]] = result.get("records") or []
    total_pages = max(1, (len(records) + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    chunk = records[page * page_size : (page + 1) * page_size]

    embed = discord.Embed(
        title=f"📋 缺曠課紀錄（{filter_label}）— {result['label']}",
        color=COLOR_WARNING,
    )
    if not chunk:
        embed.description = "📭 此篩選條件下查無紀錄。"
    else:
        lines: list[str] = []
        for idx, rec in enumerate(chunk, start=page * page_size + 1):
            dt = _pick(rec, "excuse_DT", "EXCUSE_DT", "date", "DATE", default="")
            kind = _pick(rec, "excuse_TXT", "cutclass_TXT", "filter_TXT", "excuse_NAME", "EXCUSE_ID", default="")
            subj = _pick(rec, "subj_CN", "subj_CNAME", default="")
            lesson = _pick(rec, "lesson_ID", "LESSON_ID", "lesson", default="")
            status = _pick(rec, "check_M_TXT", "status_TXT", "STATUS_TXT", "verify_TXT", default="")
            reason = _pick(rec, "reason", "REASON", default="")
            if dt != "-" or kind != "-":
                subj_part = f"｜{subj}" if subj and subj != "-" else ""
                line = f"**{idx}.** `{dt}`｜**{kind}**{subj_part}｜節次 `{lesson}`｜{status}"
                if reason and reason != "-":
                    line += f"\n　事由：{_truncate(reason, 70)}"
            else:
                line = f"**{idx}.** {_truncate(_format_generic_item(rec), 140)}"
            lines.append(line)
        embed.description = _truncate("\n".join(lines), 3900)

    embed.set_footer(text=f"第 {page + 1}/{total_pages} 頁（共 {len(records)} 筆）")
    return embed


def build_schedule_embed(result: Mapping[str, Any], profile: Mapping[str, Any]) -> discord.Embed:
    phase_txt = PHASE_MAP.get(str(result.get("phase", "")), str(result.get("phase", "")))
    embed = discord.Embed(
        title=f"📅 {result['year']} 學年第 {result['term']} 學期課表 — {phase_txt}",
        color=COLOR_PRIMARY,
    )
    student_name = _pick(profile, "std_CNAME", default="")
    if student_name and student_name != "-":
        embed.set_author(name=student_name)
    if result.get("png_bytes"):
        embed.set_image(url="attachment://schedule.png")
    else:
        embed.description = "📭 此學期階段查無選課紀錄。"
    return embed


def build_leave_basic_data_embed(data: Any) -> discord.Embed:
    """Format /appws/school/getLeaveBasicData cleanly into leave types & lesson ID tables."""
    embed = discord.Embed(title="📖 屏大假別與節次代碼表", color=COLOR_PRIMARY)
    if not isinstance(data, Mapping):
        embed.description = "📭 查無假別基本代碼資料。"
        return embed

    leave_types = data.get("leaveTypeList") or []
    if leave_types:
        lt_lines = [
            f"• **`{item.get('EXCUSE_ID', '-')}`** — {item.get('EXCUSE_ID_TXT', '-')}"
            for item in leave_types
            if isinstance(item, Mapping)
        ]
        embed.add_field(
            name="🏷️ 可線上申請假別（輸入代碼或中文皆可）",
            value="\n".join(lt_lines),
            inline=False,
        )

    lessons = data.get("lessonList") or []
    if lessons:
        ls_lines = []
        for item in lessons:
            if not isinstance(item, Mapping):
                continue
            cname = str(item.get("LESSON_CNAME") or "").strip()
            lid = str(item.get("LESSON_ID") or "").strip()
            btime = str(item.get("BTIME") or "").strip()
            etime = str(item.get("ETIME") or "").strip()
            if not lid:
                continue
            ls_lines.append(f"`{cname:>2}` ({btime}-{etime}) → 代碼 `{lid}`")
        # Split into 2 columns for readability
        mid = (len(ls_lines) + 1) // 2
        embed.add_field(name="🕒 節次對照（上午／中午）", value="\n".join(ls_lines[:mid]) or "-", inline=True)
        embed.add_field(name="🕒 節次對照（下午／夜間）", value="\n".join(ls_lines[mid:]) or "-", inline=True)

    embed.set_footer(text="申請請假時可直接輸入節次名稱（如 01,02 或 M,N）或假別中文（事假/病假/生理假），系統會自動轉換代碼")
    return embed


def build_leave_ask_list_embed(rows: Sequence[Mapping[str, Any]]) -> discord.Embed:
    """Format /appws/student/getStudentLeaveListForAsk records cleanly."""
    from application.constants import LEAVE_TYPE_MAP

    embed = discord.Embed(title="📝 線上請假單紀錄", color=COLOR_PRIMARY)
    if not rows:
        embed.description = "📭 目前沒有線上請假單紀錄。"
        return embed

    lines: list[str] = []
    for idx, rec in enumerate(rows[:15], 1):
        raw_dt = _pick(rec, "excuse_DT", "EXCUSE_DT", default="-")
        dt_fmt = f"{raw_dt[:4]}/{raw_dt[4:6]}/{raw_dt[6:8]}" if len(raw_dt) == 8 and raw_dt.isdigit() else raw_dt
        excuse_id = _pick(rec, "excuse_ID", "EXCUSE_ID", default="-")
        excuse_name = LEAVE_TYPE_MAP.get(excuse_id.upper(), excuse_id)
        sy = _pick(rec, "syear", default="")
        sm = _pick(rec, "seme", default="")
        reason = _pick(rec, "reason", "REASON", default="-")
        lesson = _pick(rec, "lesson_ID", "LESSON_ID", default="")
        status = _pick(rec, "status_TXT", "STATUS_TXT", "verify_TXT", default="")

        header = f"**{idx}.** `{dt_fmt}`｜**{excuse_name}** (`{excuse_id}`)"
        if sy != "-" and sm != "-":
            header += f"｜{sy}-{sm}"
        if lesson and lesson != "-":
            header += f"｜節次 `{lesson}`"
        if status and status != "-":
            header += f"｜狀態：{status}"
        lines.append(f"{header}\n　事由：{_truncate(reason, 90)}")

    embed.description = _truncate("\n".join(lines), 3900)
    embed.set_footer(text=f"共 {len(rows)} 筆｜原始 JSON 已存至 temp_data/")
    return embed


def build_generic_personal_embed(title: str, data: Any, empty_msg: str) -> discord.Embed:
    embed = discord.Embed(title=title, color=COLOR_PRIMARY)
    if not data:
        embed.description = f"📭 {empty_msg}"
        embed.set_footer(text="原始回應已存至 temp_data/ 供確認資料結構")
        return embed

    if isinstance(data, list):
        lines = [f"**{i}.** {_truncate(_format_generic_item(item), 160)}" for i, item in enumerate(data[:15], 1)]
        embed.description = _truncate("\n".join(lines), 3900)
        if len(data) > 15:
            embed.set_footer(text=f"僅顯示前 15 筆（共 {len(data)} 筆）| 完整 JSON 已存至 temp_data/")
        else:
            embed.set_footer(text=f"共 {len(data)} 筆 | 原始 JSON 已存至 temp_data/")
    else:
        embed.description = _truncate(f"```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```", 3900)
        embed.set_footer(text="原始 JSON 已存至 temp_data/ 供確認資料結構")
    return embed


def _format_course_time(course: Mapping[str, Any]) -> str:
    week_raw = str(course.get("week_CNAME") or course.get("week_ID") or "").strip().strip("[]")
    lesson_raw = str(course.get("lesson_CNAME") or course.get("lesson_ID") or "").strip()
    if week_raw:
        week_parts = [WEEK_MAP.get(w.strip(), f"週{w.strip()}") for w in week_raw.split(",") if w.strip()]
        week_txt = "/".join(week_parts)
    else:
        week_txt = ""
    if week_txt and lesson_raw:
        return f"{week_txt} {lesson_raw}"
    return week_txt or lesson_raw or _pick(course, "time_TXT", "TIME_TXT", default="-")


def build_public_courses_embed(result: Mapping[str, Any], page: int = 0, page_size: int = 5) -> discord.Embed:
    courses: Sequence[Mapping[str, Any]] = result.get("courses") or []
    total_pages = max(1, (len(courses) + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    chunk = courses[page * page_size : (page + 1) * page_size]

    embed = discord.Embed(
        title=f"📚 全校課程查詢 — {result['year']} 學年第 {result['term']} 學期",
        description="點擊下方對應課程按鈕即可快速檢視該課程完整資訊與大綱。",
        color=COLOR_PUBLIC,
    )
    if not chunk:
        embed.description = "📭 查無符合條件的課程。"
    else:
        for idx, c in enumerate(chunk, start=1):
            name = _pick(c, "subj_CNAME", "subj_CN", "SUBJ_CNAME", default="未命名課程")
            teacher = _pick(c, "emp_CNAME", "teacher_CNAME", "TEACHER_CNAME", "teacherName", default="-")
            room = _pick(c, "room_CNAME", "ROOM_CNAME", default="-")
            time_txt = _format_course_time(c)
            credits = _pick(c, "credits", "CREDITS", default="-")
            if credits.endswith(".0"):
                credits = credits[:-2]
            dept = _pick(c, "show_CLASS", default="")
            must = _pick(c, "must_TXT", default="")
            stds_y = _pick(c, "stds_Y", default="")
            std_max = _pick(c, "std_MAX", default="")
            cap = f"｜人數：`{stds_y}/{std_max}`" if stds_y != "-" and std_max != "-" else ""
            meta = f"（{dept}・{must}）" if dept != "-" and must != "-" else ""
            open_id = _pick(c, "open_ID", "plan_OPEN_ID", "OPEN_ID", default="")
            embed.add_field(
                name=_truncate(f"{idx}. 📖 {name} {meta}", 200),
                value=(
                    f"教師：`{teacher}`｜學分：`{credits}`{cap}\n"
                    f"時間：`{time_txt}`｜教室：`{room}`\n"
                    f"代碼：`{open_id}`"
                ),
                inline=False,
            )
    embed.set_footer(text=f"第 {page + 1}/{total_pages} 頁（共 {len(courses)} 筆）｜免登入公開資料")
    return embed


def build_course_detail_embed(detail: Any, *, show_syllabus: bool = False) -> discord.Embed:
    """Format /appws/school/getCoursePlanByOpenID/{open_ID} cleanly into Overview or Weekly Syllabus."""
    item: Mapping[str, Any] = {}
    if isinstance(detail, list) and detail and isinstance(detail[0], Mapping):
        item = detail[0]
    elif isinstance(detail, Mapping):
        item = detail

    if not item:
        return discord.Embed(title="📄 課程資訊", description="📭 查無此課程的詳細大綱資料。", color=COLOR_PUBLIC)

    cname = _pick(item, "subj_CNAME", "subj_CN", default="未命名課程")
    ename = _pick(item, "subj_ENAME", default="")
    subj_id = _pick(item, "subj_ID", default="-")
    open_id = _pick(item, "open_ID", default="-")
    teacher = _pick(item, "emp_CNAME", default="-")
    dept = _pick(item, "show_CLASS", "divs_CNAME", default="-")
    must = _pick(item, "must_TXT", default="-")
    credits = _pick(item, "credits", default="-")
    if credits.endswith(".0"):
        credits = credits[:-2]
    hours = _pick(item, "hours", default="-")
    if hours.endswith(".0"):
        hours = hours[:-2]
    tchtype = _pick(item, "tchtype_TXT", default="")
    langs = [str(item.get(k) or "").strip() for k in ("lang1", "lang2", "lang3") if str(item.get(k) or "").strip()]
    lang_str = " / ".join(langs) if langs else "-"

    def _clean(text: Any, limit: int = 950) -> str:
        s = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        while "\n\n\n" in s:
            s = s.replace("\n\n\n", "\n\n")
        return _truncate(s, limit) if s else ""

    if show_syllabus:
        syllabus = _clean(item.get("syllabus"), 3900)
        embed = discord.Embed(
            title=f"📑 每週課程進度 — {cname}",
            description=syllabus or "📭 授課教師未填寫每週進度。",
            color=COLOR_PUBLIC,
        )
        embed.set_footer(text=f"開課代碼：{open_id} ｜ 授課教師：{teacher}")
        return embed

    subtitle = f"*{ename}*\n" if ename and ename != "-" else ""
    header_info = (
        f"{subtitle}"
        f"• **授課教師**：`{teacher}`｜**開課單位**：`{dept}`（`{must}`）\n"
        f"• **學分／時數**：`{credits}` 學分 / `{hours}` 小時｜**授課語言**：`{lang_str}`\n"
        f"• **科目代碼**：`{subj_id}`｜**開課代碼**：`{open_id}`"
    )
    if tchtype and tchtype != "-":
        header_info += f"\n• **教學方式**：{tchtype}"

    embed = discord.Embed(
        title=f"📘 {cname}",
        description=header_info,
        color=COLOR_PUBLIC,
    )

    score_way = _clean(item.get("score_WAY"), 950)
    if score_way:
        embed.add_field(name="📊 評分方式", value=score_way, inline=False)

    target = _clean(item.get("target"), 950)
    if target:
        embed.add_field(name="🎯 教學目標", value=target, inline=False)

    outcomes = _clean(item.get("outcomes"), 950)
    if outcomes:
        embed.add_field(name="🎓 學習成效", value=outcomes, inline=False)

    books: list[str] = []
    mastread = _clean(item.get("mastread"), 450)
    reference = _clean(item.get("reference"), 450)
    if mastread:
        books.append(f"**指定用書**：{mastread}")
    if reference:
        books.append(f"**參考教材**：{reference}")
    if books:
        embed.add_field(name="📚 教材與參考書目", value="\n".join(books), inline=False)

    othermm = _clean(item.get("othermm"), 400)
    if othermm:
        embed.add_field(name="📝 備註", value=othermm, inline=False)

    embed.set_footer(text="點擊下方「📑 檢視每週進度」按鈕可切換查看完整 16 週教學進度")
    return embed


def build_library_search_embed(qtext: str, qtype: str, data: Any) -> discord.Embed:
    embed = discord.Embed(
        title=f"📖 屏大圖書館館藏查詢：{qtext}",
        description=f"查詢類型：`{qtype}`",
        color=COLOR_PUBLIC,
    )
    items = data if isinstance(data, list) else (data.get("list") or data.get("data") if isinstance(data, dict) else [])
    if not items:
        embed.add_field(name="📭 查無館藏", value="請嘗試其他關鍵字，或檢查 `temp_data/` 確認回傳格式。", inline=False)
        return embed

    for idx, item in enumerate(items[:10], 1):
        if isinstance(item, Mapping):
            title = _pick(item, "title", "TITLE", "bibTitle", "name", default=f"書籍 #{idx}")
            author = _pick(item, "author", "AUTHOR", default="-")
            pub = _pick(item, "publisher", "pubYear", "publish", default="-")
            bib_id = _pick(item, "bibId", "bibid", "BIBID", "id", default="-")
            embed.add_field(
                name=_truncate(f"{idx}. {title}", 200),
                value=f"作者：`{author}` | 出版：`{pub}` | BibID：`{bib_id}`",
                inline=False,
            )
        else:
            embed.add_field(name=f"{idx}.", value=_truncate(str(item), 200), inline=False)
    embed.set_footer(text="免登入公開資料 | 原始 JSON 已存至 temp_data/")
    return embed


def build_classroom_embed(result: Mapping[str, Any]) -> discord.Embed:
    rooms: Mapping[str, list[dict[str, Any]]] = result.get("rooms") or {}
    locations: Sequence[Any] = result.get("locations") or []
    filters = result.get("filters") or {}
    week_label = WEEK_MAP.get(str(filters.get("weekID", "")), "不限星期")

    embed = discord.Embed(
        title=f"🏫 教室使用與校園地點查詢（{result['year']}-{result['term']}）",
        description=f"條件：`{week_label}` | 節次：`{filters.get('lessonStartID', '不限')}~{filters.get('lessonEndID', '不限')}` | 關鍵字：`{result.get('keyword') or '無'}`",
        color=COLOR_PUBLIC,
    )
    if rooms:
        lines = []
        for room_name, course_list in list(rooms.items())[:15]:
            sample = ", ".join(
                _pick(c, "subj_CNAME", "subj_CN", default="課程") for c in course_list[:2]
            )
            lines.append(f"• **{room_name}**（{len(course_list)} 堂使用中：{sample}）")
        embed.add_field(name="📋 查詢時段使用中教室", value=_truncate("\n".join(lines), 1000), inline=False)
    else:
        embed.add_field(name="📋 教室使用狀況", value="此條件下查無排課使用中的教室紀錄。", inline=False)

    if locations:
        loc_lines = [_truncate(_format_generic_item(loc), 100) for loc in locations[:8]]
        embed.add_field(name="📍 相關校園地點", value=_truncate("\n".join(loc_lines), 1000), inline=False)

    embed.set_footer(text="免登入公開資料（由開課課表反推教室使用狀況）| 原始 JSON 已存至 temp_data/")
    return embed


def build_score_notify_embed(changes: Sequence[Mapping[str, Any]]) -> discord.Embed:
    embed = discord.Embed(
        title="🔔 屏大新成績通知",
        description=f"偵測到 **{len(changes)}** 門科目成績更新！",
        color=COLOR_SUCCESS,
    )
    for c in changes[:15]:
        grade = score_to_grade(c.get("score"))
        grade_str = f"{grade.letter} ({grade.grade_point:.1f})" if grade else "-"
        old = c.get("old_score") or "尚未結算"
        embed.add_field(
            name=f"📘 {c['subj_CN']} ({c['subj_ID']})",
            value=f"分數：`{old}` → **`{c['score']}`** | 等第：`{grade_str}` | 學分：`{c.get('credits', '-')}`",
            inline=False,
        )
    return embed


def build_leave_notify_embed(changes: Sequence[Mapping[str, Any]]) -> discord.Embed:
    embed = discord.Embed(
        title="🔔 屏大請假／缺曠狀態異動通知",
        description=f"偵測到 **{len(changes)}** 筆假單狀態更新！",
        color=COLOR_WARNING,
    )
    for c in changes[:15]:
        raw = c.get("raw") or {}
        dt = _pick(raw, "EXCUSE_DT", "excuse_DT", default="-")
        kind = _pick(raw, "excuse_NAME", "EXCUSE_NAME", "EXCUSE_ID", default="假單")
        if c.get("change_type") == "new":
            val = f"新增紀錄｜目前狀態：`{c.get('status') or '待審核'}`"
        else:
            val = f"狀態變更：`{c.get('old_status') or '-'}` → **`{c.get('status') or '-'}`**"
        embed.add_field(name=f"📝 {dt} - {kind}", value=val, inline=False)
    return embed
