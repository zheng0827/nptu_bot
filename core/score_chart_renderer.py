"""High-resolution dark-theme semester score average & GPA trend line chart renderer (Pillow)."""
from __future__ import annotations

import io
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw

from core.gpa import ScoreSummary
from core.schedule_renderer import _draw_dashed_line, _load_font, _resolve_font_path


def render_score_trend_png(
    points: Sequence[Mapping[str, Any]],
    overall: ScoreSummary,
    student_name: str = "",
) -> bytes:
    """Render a chronological line chart of semester weighted score averages and NPTU 4.0 GPA.

    Each point dict expects:
      - label: str (e.g., "113-1")
      - avg: float (weighted score average 0..100)
      - gpa: float | None (NPTU 4.0 GPA)
      - credits: float (earned credits)
    """
    width, height = 1600, 920
    img = Image.new("RGBA", (width, height), "#181A1F")
    draw = ImageDraw.Draw(img, "RGBA")
    font_path = _resolve_font_path()

    title_font = _load_font(font_path, 42)
    sub_font = _load_font(font_path, 26)
    axis_font = _load_font(font_path, 24)
    val_font = _load_font(font_path, 26)
    gpa_font = _load_font(font_path, 21)

    # Top header card
    draw.rounded_rectangle([60, 40, width - 60, 170], radius=28, fill="#21252B")
    title_text = "歷年學期成績平均趨勢折線圖"
    if student_name:
        title_text = f"{student_name} — {title_text}"
    draw.text((100, 82), title_text, fill="#E5E9F0", font=title_font, anchor="lm")

    overall_avg = f"{overall.weighted_score_avg:.2f}" if overall.weighted_score_avg is not None else "-"
    overall_gpa = f"{overall.gpa:.2f}" if overall.gpa is not None else "-"
    sub_text = (
        f"總加權平均：{overall_avg}    |    總 GPA：{overall_gpa} / 4.00    |    "
        f"實得學分：{overall.earned_credits:g} / {overall.attempted_credits:g}    |    "
        f"統計學期數：{len(points)}"
    )
    draw.text((100, 134), sub_text, fill="#9BA3B4", font=sub_font, anchor="lm")

    # Chart card container
    card_left, card_top, card_right, card_bottom = 60, 200, width - 60, height - 50
    draw.rounded_rectangle([card_left, card_top, card_right, card_bottom], radius=28, fill="#21252B")

    # Plot area bounds
    plot_left = 170
    plot_right = width - 140
    plot_top = 275
    plot_bottom = height - 155
    plot_w = plot_right - plot_left
    plot_h = plot_bottom - plot_top

    if not points:
        draw.text(
            ((plot_left + plot_right) / 2, (plot_top + plot_bottom) / 2),
            "尚無可繪製的已結算學期成績",
            fill="#8B92A5",
            font=title_font,
            anchor="mm",
        )
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()

    avgs = [float(p["avg"]) for p in points]
    min_avg = min(avgs)
    # Smart Y-axis floor (keep readable 10-point ticks, max is always 100)
    y_min = max(0, int((min_avg - 10) // 10) * 10)
    if y_min > 60:
        y_min = 60
    y_max = 100
    y_span = max(10, y_max - y_min)

    def _y_for_score(val: float) -> float:
        clamped = max(y_min, min(y_max, val))
        return plot_bottom - ((clamped - y_min) / y_span) * plot_h

    # Horizontal gridlines & Y-axis labels
    tick_step = 10 if y_span <= 60 else 20
    for tick in range(y_min, y_max + 1, tick_step):
        y = _y_for_score(float(tick))
        line_color = "#3B4252" if tick == 60 else "#2D323E"
        _draw_dashed_line(draw, (plot_left, y), (plot_right, y), line_color, width=2, dash=10, gap=10)
        draw.text((plot_left - 24, y), str(tick), fill="#8B92A5", font=axis_font, anchor="rm")

    # Overall average reference line
    if overall.weighted_score_avg is not None:
        ref_y = _y_for_score(overall.weighted_score_avg)
        _draw_dashed_line(draw, (plot_left, ref_y), (plot_right, ref_y), "#F39C12", width=3, dash=14, gap=8)
        draw.text(
            (plot_right + 16, ref_y),
            f"總均 {overall.weighted_score_avg:.1f}",
            fill="#F39C12",
            font=gpa_font,
            anchor="lm",
        )

    # Compute point coordinates
    n = len(points)
    coords: list[tuple[float, float]] = []
    for idx, p in enumerate(points):
        if n == 1:
            x = (plot_left + plot_right) / 2
        else:
            x = plot_left + (idx / (n - 1)) * plot_w
        y = _y_for_score(float(p["avg"]))
        coords.append((x, y))

    # Translucent area fill under the line
    if len(coords) >= 2:
        polygon = [(coords[0][0], plot_bottom), *coords, (coords[-1][0], plot_bottom)]
        draw.polygon(polygon, fill=(79, 195, 247, 36))

    # Main trend line
    if len(coords) >= 2:
        draw.line(coords, fill="#4FC3F7", width=6, joint="curve")

    # Vertical tick guides, X-axis labels, data points & value annotations
    for idx, (x, y) in enumerate(coords):
        p = points[idx]
        _draw_dashed_line(draw, (x, plot_bottom), (x, y), "#2C3340", width=2, dash=6, gap=6)

        # Glowing outer ring + inner dot
        draw.ellipse([x - 14, y - 14, x + 14, y + 14], fill=(79, 195, 247, 70))
        draw.ellipse([x - 8, y - 8, x + 8, y + 8], fill="#4FC3F7", outline="#FFFFFF", width=3)

        # Score value above point
        avg_label = f"{float(p['avg']):.2f}"
        label_y = y - 28 if y > plot_top + 45 else y + 32
        draw.text((x, label_y), avg_label, fill="#FFFFFF", font=val_font, anchor="mm")

        # GPA sub-label
        if p.get("gpa") is not None:
            gpa_y = label_y - 26 if y > plot_top + 45 else label_y + 26
            draw.text((x, gpa_y), f"GPA {float(p['gpa']):.2f}", fill="#2ECC71", font=gpa_font, anchor="mm")

        # X-axis semester label
        draw.text((x, plot_bottom + 34), str(p["label"]), fill="#E5E9F0", font=axis_font, anchor="mm")

    # Axes border lines
    draw.line([(plot_left, plot_top), (plot_left, plot_bottom), (plot_right, plot_bottom)], fill="#4C566A", width=3)

    # Legend (top-right inside chart card)
    draw.ellipse([plot_right - 360, 224, plot_right - 344, 240], fill="#4FC3F7")
    draw.text((plot_right - 332, 232), "學期加權平均", fill="#E5E9F0", font=gpa_font, anchor="lm")
    draw.line([(plot_right - 170, 232), (plot_right - 135, 232)], fill="#F39C12", width=4)
    draw.text((plot_right - 125, 232), "總加權平均線", fill="#F39C12", font=gpa_font, anchor="lm")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()
