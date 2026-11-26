"""High-resolution dark-theme schedule PNG renderer (ported from nptu.js)."""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

from application.constants import LESSON_MAP, TIME_SLOTS

_CANDIDATE_FONTS = [
    # Windows (Microsoft JhengHei Bold / Regular)
    r"C:\Windows\Fonts\msjhbd.ttc",
    r"C:\Windows\Fonts\msjh.ttc",
    r"C:\Windows\Fonts\kaiu.ttf",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    # Linux Noto CJK / WenQuanYi
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _resolve_font_path() -> str | None:
    custom = os.getenv("SCHEDULE_FONT_PATH", "").strip()
    if custom and Path(custom).exists():
        return custom
    for candidate in _CANDIDATE_FONTS:
        if Path(candidate).exists():
            return candidate
    return None


def _load_font(font_path: str | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if font_path:
        try:
            return ImageFont.truetype(font_path, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: float) -> list[str]:
    if not text:
        return []
    lines: list[str] = []
    current = text[0]
    for ch in text[1:]:
        bbox = draw.textbbox((0, 0), current + ch, font=font)
        if (bbox[2] - bbox[0]) < max_width:
            current += ch
        else:
            lines.append(current)
            current = ch
    lines.append(current)
    return lines


def _draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    start: tuple[float, float],
    end: tuple[float, float],
    fill: str,
    width: int = 3,
    dash: int = 12,
    gap: int = 12,
) -> None:
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    dist = (dx * dx + dy * dy) ** 0.5
    if dist == 0:
        return
    ux, uy = dx / dist, dy / dist
    pos = 0.0
    while pos < dist:
        seg_end = min(pos + dash, dist)
        draw.line(
            [(x1 + ux * pos, y1 + uy * pos), (x1 + ux * seg_end, y1 + uy * seg_end)],
            fill=fill,
            width=width,
        )
        pos += dash + gap


def render_schedule_png(course_data: Sequence[Mapping[str, Any]]) -> bytes:
    """Render NPTU course records into a high-resolution dark-mode PNG buffer."""
    has_weekend = any(str(c.get("week_ID", "")) in {"6", "7"} for c in course_data)
    days = (
        ["時間 / 星期", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        if has_weekend
        else ["時間 / 星期", "星期一", "星期二", "星期三", "星期四", "星期五"]
    )

    slot_index = {slot["id"]: idx for idx, slot in enumerate(TIME_SLOTS)}
    max_period_idx = 9
    for c in course_data:
        raw_id = str(c.get("lesson_ID", "")).strip()
        norm_id = LESSON_MAP.get(raw_id, raw_id)
        idx = slot_index.get(norm_id, -1)
        if idx > max_period_idx:
            max_period_idx = idx

    active_slots = TIME_SLOTS[: max_period_idx + 1]
    margin = 80
    width = 2048
    cols = len(days)
    rows = len(active_slots) + 1
    cell_width = (width - margin * 2) / cols
    cell_height = 240
    height = margin * 2 + rows * cell_height

    img = Image.new("RGB", (width, height), "#181A1F")
    draw = ImageDraw.Draw(img)
    font_path = _resolve_font_path()

    header_font = _load_font(font_path, 48 if not has_weekend else 38)
    slot_id_font = _load_font(font_path, 58)
    slot_time_font = _load_font(font_path, 28)

    # Dashed grid
    for i in range(1, cols + 1):
        x = margin + i * cell_width
        _draw_dashed_line(draw, (x, margin + cell_height), (x, height - margin), "#282C34")
    for i in range(1, rows + 1):
        y = margin + i * cell_height
        _draw_dashed_line(draw, (margin + cell_width, y), (width - margin, y), "#282C34")

    # Top header bar
    draw.rounded_rectangle(
        [margin, margin, width - margin, margin + cell_height],
        radius=40,
        fill="#21252B",
    )
    for i, label in enumerate(days):
        cx = margin + i * cell_width + cell_width / 2
        cy = margin + cell_height / 2
        draw.text((cx, cy), label, fill="#E5E9F0", font=header_font, anchor="mm")

    # Left time column
    draw.rounded_rectangle(
        [margin, margin + cell_height + 16, margin + cell_width - 16, height - margin],
        radius=40,
        fill="#21252B",
    )
    for i, slot in enumerate(active_slots):
        cx = margin + cell_width / 2 - 8
        cy = margin + (i + 1) * cell_height + cell_height / 2
        draw.text((cx, cy - 25), slot["id"], fill="#FFFFFF", font=slot_id_font, anchor="mm")
        draw.text((cx, cy + 35), slot["time"], fill="#8B92A5", font=slot_time_font, anchor="mm")

    # Group consecutive slots of the same course on the same day
    grouped: dict[str, dict[str, Any]] = {}
    for c in course_data:
        try:
            week_idx = int(str(c.get("week_ID", "")).strip())
        except ValueError:
            continue
        if week_idx < 1 or week_idx > cols - 1:
            continue
        raw_id = str(c.get("lesson_ID", "")).strip()
        norm_id = LESSON_MAP.get(raw_id, raw_id)
        if norm_id not in slot_index or slot_index[norm_id] > max_period_idx:
            continue
        row_idx = slot_index[norm_id] + 1
        open_id = str(c.get("plan_OPEN_ID") or c.get("subj_CNAME") or row_idx)
        key = f"{week_idx}_{open_id}"
        if key not in grouped:
            grouped[key] = {
                **dict(c),
                "weekIdx": week_idx,
                "startRow": row_idx,
                "endRow": row_idx,
                "span": 1,
            }
        else:
            grouped[key]["startRow"] = min(grouped[key]["startRow"], row_idx)
            grouped[key]["endRow"] = max(grouped[key]["endRow"], row_idx)
            grouped[key]["span"] = grouped[key]["endRow"] - grouped[key]["startRow"] + 1

    required_color = "#3A5B7C"
    elective_color = "#417865"
    title_size = 36 if has_weekend else 44
    room_size = 26 if has_weekend else 32
    title_font = _load_font(font_path, title_size)
    room_font = _load_font(font_path, room_size)
    title_lh = title_size + 14
    room_lh = room_size + 12

    for course in grouped.values():
        must_txt = str(course.get("must_TXT") or "")
        divs_cname = str(course.get("divs_CNAME") or "")
        is_elective = (must_txt == "選") or ("選" in divs_cname)
        card_color = elective_color if is_elective else required_color

        x = margin + course["weekIdx"] * cell_width + 12
        y = margin + course["startRow"] * cell_height + 12
        card_w = cell_width - 24
        card_h = course["span"] * cell_height - 24
        cx = x + card_w / 2
        cy = y + card_h / 2

        radius = min(48, card_w / 2, card_h / 2)
        draw.rounded_rectangle([x, y, x + card_w, y + card_h], radius=radius, fill=card_color)

        subj_name = str(course.get("subj_CNAME") or course.get("subj_CN") or "未命名課程")
        room_raw = str(course.get("room_CNAME") or "未定").split("(")[0].strip()

        title_lines = _wrap_text(draw, subj_name, title_font, card_w - 44)
        room_lines = _wrap_text(draw, room_raw, room_font, card_w - 44)

        total_h = len(title_lines) * title_lh + len(room_lines) * room_lh + 10
        cur_y = cy - total_h / 2 + title_lh / 2

        for line in title_lines:
            draw.text((cx, cur_y), line, fill="#FFFFFF", font=title_font, anchor="mm")
            cur_y += title_lh
        cur_y += 10
        for line in room_lines:
            draw.text((cx, cur_y), line, fill="#A8B1C2", font=room_font, anchor="mm")
            cur_y += room_lh

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
