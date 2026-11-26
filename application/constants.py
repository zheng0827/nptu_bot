"""Constants and API endpoint catalog reverse-engineered from NPTU mobile APK."""
from __future__ import annotations

from typing import Any

BASE_URL = "https://app.nptu.edu.tw:8443"
USER_AGENT = "Mozilla/5.0 ( compatible ) Android"
DEFAULT_TIMEOUT = 20.0

TIME_SLOTS: list[dict[str, str]] = [
    {"id": "M", "time": "07:00 - 07:50"},
    {"id": "01", "time": "08:00 - 08:50"},
    {"id": "02", "time": "09:00 - 09:50"},
    {"id": "03", "time": "10:10 - 11:00"},
    {"id": "04", "time": "11:10 - 12:00"},
    {"id": "N", "time": "12:10 - 13:00"},
    {"id": "05", "time": "13:30 - 14:20"},
    {"id": "06", "time": "14:30 - 15:20"},
    {"id": "07", "time": "15:40 - 16:30"},
    {"id": "08", "time": "16:40 - 17:30"},
    {"id": "09", "time": "17:35 - 18:25"},
    {"id": "A", "time": "18:30 - 19:15"},
    {"id": "B", "time": "19:20 - 20:05"},
    {"id": "C", "time": "20:10 - 20:55"},
    {"id": "D", "time": "21:00 - 21:45"},
]

LESSON_MAP: dict[str, str] = {
    "M": "M",
    "1": "01",
    "2": "02",
    "3": "03",
    "4": "04",
    "N": "N",
    "5": "05",
    "6": "06",
    "7": "07",
    "8": "08",
    "9": "09",
    "A": "A",
    "B": "B",
    "C": "C",
    "D": "D",
}

PHASE_MAP: dict[str, str] = {
    "-1": "尚未選課",
    "0": "尚未選課",
    "1": "獎勵預選",
    "2": "第一次選課",
    "3": "第二次選課",
    "4": "選課完成",
}

WEEK_MAP: dict[str, str] = {
    "1": "星期一",
    "2": "星期二",
    "3": "星期三",
    "4": "星期四",
    "5": "星期五",
    "6": "星期六",
    "7": "星期日",
}

LIBRARY_QUERY_TYPES: dict[str, str] = {
    "title": "書名",
    "author": "作者",
    "keyword": "關鍵字",
    "isbn": "ISBN",
}

# Verified against /appws/school/getLeaveBasicData & /appws/student/getStudentLeaveListForAsk
LEAVE_TYPE_MAP: dict[str, str] = {
    "B": "事假",
    "C": "病假",
    "F": "公假",
    "J": "生理假",
}

LEAVE_NAME_TO_ID: dict[str, str] = {
    "事假": "B",
    "病假": "C",
    "公假": "F",
    "生理假": "J",
    "B": "B",
    "C": "C",
    "F": "F",
    "J": "J",
}

# Map human-readable lesson names (e.g. "M", "01", "09", "A"~"D") to NPTU askLeave LESSON_ID
LEAVE_LESSON_NAME_TO_ID: dict[str, str] = {
    "M": "78",
    "01": "1",
    "1": "1",
    "02": "2",
    "2": "2",
    "03": "3",
    "3": "3",
    "04": "4",
    "4": "4",
    "N": "45",
    "05": "5",
    "5": "5",
    "06": "6",
    "6": "6",
    "07": "7",
    "7": "7",
    "08": "8",
    "8": "8",
    "09": "89",
    "9": "89",
    "A": "9",
    "B": "10",
    "C": "11",
    "D": "12",
    "78": "78",
    "45": "45",
    "89": "89",
    "10": "10",
    "11": "11",
    "12": "12",
}

ENCRYPTED_STUDENT_ENDPOINTS: set[str] = {
    "student_semesters",
    "student_courses",
    "student_scores",
    "student_score_alert",
    "student_reward",
    "student_leave_list",
    "student_leave_statistics",
    "student_leave_ask_list",
    "student_leave_delete",
    "student_leave_file",
    "student_leave_submit",
}

API_CATALOG: dict[str, dict[str, Any]] = {
    # OAuth
    "oauth_token": {"path": "/appws/oauth/oauthToken", "method": "GET"},
    "oauth_refresh": {"path": "/appws/oauth/oauthRefreshToken", "method": "GET"},
    "oauth_logout": {"path": "/appws/oauth/oauthLogout", "method": "GET"},
    # Student (encrypted, login required)
    "student_semesters": {"path": "/appws/student/getStudentScoreYearTerm", "method": "GET"},
    "student_courses": {"path": "/appws/student/getCourseList", "method": "GET"},
    "student_scores": {"path": "/appws/student/getScoreByYear", "method": "GET"},
    "student_score_alert": {"path": "/appws/student/getScoreAlertList", "method": "GET"},
    "student_reward": {"path": "/appws/student/getReward", "method": "GET"},
    "student_leave_list": {"path": "/appws/student/getLeaveList", "method": "GET"},
    "student_leave_statistics": {"path": "/appws/student/getLeaveStatistics", "method": "GET"},
    "student_leave_ask_list": {"path": "/appws/student/getStudentLeaveListForAsk", "method": "GET"},
    "student_leave_delete": {"path": "/appws/student/deleteLeave", "method": "GET", "mutating": True},
    "student_leave_file": {"path": "/appws/student/getStudentLeaveFile", "method": "GET"},
    "student_leave_submit": {"path": "/appws/student/askLeave", "method": "POST", "mutating": True},
    # Public School / Course / Classroom / Map (no login required)
    "leave_basic_data": {"path": "/appws/school/getLeaveBasicData", "method": "GET"},
    "course_departments": {"path": "/appws/school/getCourseDeptByYear/{year}", "method": "GET"},
    "course_query": {"path": "/appws/school/queryCourse/{year}/{term}", "method": "GET"},
    "course_detail": {"path": "/appws/school/getCoursePlanByOpenID/{open_ID}", "method": "GET"},
    "course_basic_data": {"path": "/appws/school/getCourseBasicData", "method": "GET"},
    "course_phase": {"path": "/appws/school/getCoursePhase", "method": "GET"},
    "course_year_term": {"path": "/appws/school/getCourseYearTerm", "method": "GET"},
    "location_list": {"path": "/appws/locationList", "method": "GET"},
    "poi": {"path": "/appws/mapPoi", "method": "GET"},
    "poi_type": {"path": "/appws/mapPoiType", "method": "GET"},
    "news_list": {"path": "/appws/newsList", "method": "GET"},
    # Public Library (no login required)
    "library_search_book": {"path": "/libws/libQueryBib", "method": "POST"},
    "library_book_detail": {"path": "/libws/libQueryItem", "method": "POST"},
    "library_open_time_lv1": {"path": "/libws/libOpenTimeLv1", "method": "POST"},
    "library_open_time_lv2": {"path": "/libws/libOpenTimeLv2", "method": "POST"},
    "library_news": {"path": "/appws/libNewsList/{page}", "method": "GET"},
}
