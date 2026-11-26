"""NPTU official 4.0 GPA & Grade Score conversion and statistics calculator.

Official NPTU Grade Score & Grade Point Table:
- A: 4.0 | 80~100 | converted 100-point: 90
- B: 3.0 | 70~79  | converted 100-point: 75 (Graduate passing standard)
- C: 2.0 | 60~69  | converted 100-point: 65 (Undergraduate passing standard)
- D: 1.0 | 50~59  | converted 100-point: 55
- E: 0.0 | 1~49   | converted 100-point: 49
- X: 0.0 | 0      | converted 100-point: 0
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

LETTER_TO_POINT: dict[str, tuple[float, int]] = {
    "A": (4.0, 90),
    "B": (3.0, 75),
    "C": (2.0, 65),
    "D": (1.0, 55),
    "E": (0.0, 49),
    "X": (0.0, 0),
}


@dataclass(frozen=True)
class GradeConversion:
    letter: str
    grade_point: float
    converted_score: int


def score_to_grade(raw_score: Any) -> GradeConversion | None:
    """Convert a 100-point numeric score or letter grade into NPTU GradeConversion."""
    if raw_score is None:
        return None
    text = str(raw_score).strip().upper()
    if not text or text in {"-", "尚未結算", "N/A"}:
        return None

    if text in LETTER_TO_POINT:
        gp, conv = LETTER_TO_POINT[text]
        return GradeConversion(letter=text, grade_point=gp, converted_score=conv)

    try:
        numeric = float(text)
    except ValueError:
        return None

    if numeric >= 80:
        return GradeConversion(letter="A", grade_point=4.0, converted_score=90)
    if numeric >= 70:
        return GradeConversion(letter="B", grade_point=3.0, converted_score=75)
    if numeric >= 60:
        return GradeConversion(letter="C", grade_point=2.0, converted_score=65)
    if numeric >= 50:
        return GradeConversion(letter="D", grade_point=1.0, converted_score=55)
    if numeric > 0:
        return GradeConversion(letter="E", grade_point=0.0, converted_score=49)
    return GradeConversion(letter="X", grade_point=0.0, converted_score=0)


def _parse_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _is_passed(record: Mapping[str, Any], numeric_score: float | None, grade: GradeConversion | None) -> bool:
    pass_txt = str(record.get("pass_TXT") or "").strip()
    if pass_txt:
        if any(tok in pass_txt for tok in ("及格", "通過", "Y", "Pass", "PASS", "是")):
            if not any(tok in pass_txt for tok in ("不及格", "未通過", "不通過")):
                return True
        if any(tok in pass_txt for tok in ("不及格", "未通過", "不通過", "N", "Fail", "FAIL", "否")):
            return False
    if numeric_score is not None:
        return numeric_score >= 60
    if grade is not None:
        return grade.letter in {"A", "B", "C"}
    return False


@dataclass
class ScoreSummary:
    total_courses: int = 0
    graded_courses: int = 0
    attempted_credits: float = 0.0
    earned_credits: float = 0.0
    weighted_score_avg: float | None = None
    gpa: float | None = None
    grade_counts: dict[str, int] = field(
        default_factory=lambda: {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0, "X": 0}
    )


def summarize_scores(records: Iterable[Mapping[str, Any]]) -> ScoreSummary:
    """Compute weighted average, earned/attempted credits, NPTU 4.0 GPA, and grade distribution."""
    summary = ScoreSummary()
    weighted_score_sum = 0.0
    weighted_score_credits = 0.0
    weighted_gp_sum = 0.0
    weighted_gp_credits = 0.0

    for rec in records:
        summary.total_courses += 1
        credits = _parse_float(rec.get("credits"), 0.0)
        summary.attempted_credits += credits

        raw_score = rec.get("score")
        grade = score_to_grade(raw_score)
        numeric_score: float | None = None
        if raw_score is not None and str(raw_score).strip() != "":
            try:
                numeric_score = float(str(raw_score).strip())
            except ValueError:
                numeric_score = None

        if grade is not None:
            summary.graded_courses += 1
            summary.grade_counts[grade.letter] = summary.grade_counts.get(grade.letter, 0) + 1
            if credits > 0:
                weighted_gp_sum += grade.grade_point * credits
                weighted_gp_credits += credits
                score_for_avg = numeric_score if numeric_score is not None else float(grade.converted_score)
                weighted_score_sum += score_for_avg * credits
                weighted_score_credits += credits
            if _is_passed(rec, numeric_score, grade):
                summary.earned_credits += credits

    if weighted_score_credits > 0:
        summary.weighted_score_avg = round(weighted_score_sum / weighted_score_credits, 2)
    if weighted_gp_credits > 0:
        summary.gpa = round(weighted_gp_sum / weighted_gp_credits, 2)

    return summary
