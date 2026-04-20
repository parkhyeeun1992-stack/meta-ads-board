import argparse
import base64
import hashlib
import json
import random
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

import requests

from meta_hospital_test import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    HEADERS,
    build_session,
    days_live,
    fetch_results,
    image_url,
    snapshot_text,
    start_timestamp,
)


WORKDIR = Path(__file__).resolve().parent
DB_PATH = WORKDIR / "meta_ads_dashboard.db"
ASSET_DIR = WORKDIR / "dashboard_assets"
DEFAULT_LIMIT_PER_CATEGORY = 500
DEFAULT_LIMIT_PER_SEARCH = 250
QUERY_SLEEP_RANGE_SECONDS = (0.6, 1.4)
ANALYSIS_SLEEP_SECONDS = 3
ANALYSIS_RETRY_SECONDS = 20
ANALYSIS_MAX_RETRIES = 3
DEFAULT_IMAGE_MIME = "image/jpeg"
RATE_LIMIT_ANALYSIS_MESSAGE = "⚠️ [이미지 분석 불가] API 요청 한도 초과(429)로 인해 분석이 누락되었습니다."

MEDIA_TYPE_IMAGE = "단일이미지(Image)"
MEDIA_TYPE_VIDEO = "영상(Video)"
MEDIA_TYPE_CAROUSEL = "캐러셀(Carousel)"
ETC_CATEGORY = "미분류(Etc)"
CLASSIFICATION_MIN_SCORE = 6
CLASSIFICATION_MARGIN = 4
LEAD_BODY_CHARS = 180

CATEGORY_CONFIG = {
    "강남언니": {
        "queries": ["강남언니", "강언", "강남언니 이벤트", "강남언니 성형", "강남언니 입점"],
        "signals": ["강남언니", "강언", "성형", "이벤트", "입점", "병원", "의원", "클리닉"],
        "exclusions": ["바비톡", "여신티켓"],
    },
    "바비톡": {
        "queries": ["바비톡", "바비톡 이벤트", "바비톡 성형", "바비톡 할인", "바비톡 후기"],
        "signals": ["바비톡", "이벤트", "할인", "후기", "성형", "병원", "의원", "클리닉"],
        "exclusions": ["강남언니", "여신티켓"],
    },
    "여신티켓": {
        "queries": ["여신티켓", "여티", "여신티켓 시술", "여신티켓 피부과", "여신티켓 예약"],
        "signals": ["여신티켓", "여티", "시술", "예약", "피부과", "병원", "의원", "클리닉"],
        "exclusions": ["강남언니", "바비톡"],
    },
    "남성제모": {
        "queries": ["남성제모", "젠틀맥스", "수염제모", "턱수염제모", "인중제모", "남자제모"],
        "signals": ["남성제모", "젠틀맥스", "수염제모", "제모", "피부과", "의원", "병원", "클리닉"],
        "exclusions": ["여성제모", "브라질리언", "비키니", "네일"],
    },
    "여성제모": {
        "queries": ["여성제모", "브라질리언", "레이저제모", "브라질리언제모", "비키니제모", "겨드랑이제모"],
        "signals": ["여성제모", "브라질리언", "레이저제모", "제모", "피부과", "의원", "병원", "클리닉"],
        "exclusions": ["남성제모", "수염제모", "헤어라인", "네일"],
    },
    "임플란트": {
        "queries": ["임플란트", "오스템", "네비게이션임플란트", "전체임플란트", "원데이임플란트", "올온포"],
        "signals": ["임플란트", "오스템", "네비게이션임플란트", "치과", "치아", "의원", "병원", "클리닉"],
        "exclusions": ["피부과", "안과", "성형외과", "네일"],
    },
    "라미네이트": {
        "queries": ["라미네이트", "무삭제라미네이트", "치아성형", "최소삭제라미네이트", "심미치과", "연예인치아"],
        "signals": ["라미네이트", "무삭제라미네이트", "치아성형", "치과", "치아", "의원", "병원", "클리닉"],
        "exclusions": ["피부과", "안과", "성형외과", "네일"],
    },
    "리프팅": {
        "queries": ["울쎄라", "써마지", "인모드", "슈링크", "실리프팅", "세르프", "리프팅"],
        "signals": ["리프팅", "울쎄라", "써마지", "인모드", "슈링크", "피부과", "의원", "병원", "클리닉"],
        "exclusions": ["헤어", "네일", "트리트먼트"],
    },
    "울쎄라": {
        "queries": ["울쎄라", "울쎄라 리프팅", "울쎄라 정품팁", "울쎄라 600샷", "프리미엄 리프팅"],
        "signals": ["울쎄라", "울쎄라 리프팅", "정품팁", "600샷", "리프팅", "피부과", "의원", "병원", "클리닉"],
        "exclusions": ["써마지", "인모드", "슈링크", "네일"],
    },
    "안면거상": {
        "queries": ["안면거상", "미니거상", "실리프팅", "안면거상술", "이마거상", "거상수술"],
        "signals": ["안면거상", "미니거상", "실리프팅", "거상", "성형외과", "의원", "병원", "클리닉"],
        "exclusions": ["안과", "치과", "네일"],
    },
    "피부/쁘띠": {
        "queries": ["리쥬란", "쥬베룩", "보톡스", "필러", "스킨부스터", "물광주사", "엑소좀"],
        "signals": ["리쥬란", "쥬베룩", "보톡스", "필러", "스킨부스터", "피부과", "의원", "병원", "클리닉"],
        "exclusions": ["성형외과", "안과", "치과", "네일"],
    },
    "스킨부스터": {
        "queries": ["스킨부스터", "리쥬란", "쥬베룩", "엑소좀", "샤넬주사", "피부 물광"],
        "signals": ["스킨부스터", "리쥬란", "쥬베룩", "엑소좀", "샤넬주사", "물광", "피부과", "의원", "병원", "클리닉"],
        "exclusions": ["울쎄라", "써마지", "인모드", "네일"],
    },
    "눈성형": {
        "queries": ["쌍꺼풀", "눈매교정", "앞트임", "상안검", "하안검", "눈재수술"],
        "signals": ["쌍꺼풀", "눈매교정", "앞트임", "눈성형", "성형외과", "의원", "병원", "클리닉"],
        "exclusions": ["안과", "피부과", "치과", "네일"],
    },
    "코성형": {
        "queries": ["코성형", "기능코", "자가늑", "코재수술", "복코", "매부리코"],
        "signals": ["코성형", "기능코", "자가늑", "코재수술", "성형외과", "의원", "병원", "클리닉"],
        "exclusions": ["안과", "피부과", "치과", "네일"],
    },
    "가슴성형": {
        "queries": ["가슴성형", "가슴수술", "모티바", "세빈", "멘토부스트", "가슴거상"],
        "signals": ["가슴성형", "모티바", "세빈", "가슴수술", "성형외과", "의원", "병원", "클리닉"],
        "exclusions": ["안과", "피부과", "치과", "네일"],
    },
    "시력교정": {
        "queries": ["스마일라식", "라섹", "렌즈삽입술", "라식", "ICL", "투데이라섹"],
        "signals": ["스마일라식", "라섹", "렌즈삽입술", "렌즈삽입", "안과", "의원", "병원", "클리닉"],
        "exclusions": ["눈성형", "쌍꺼풀", "상안검", "하안검"],
    },
}

CATEGORY_RULES = {
    "강남언니": {
        "primary": ["강남언니", "강남언니 이벤트", "강남언니 성형", "강남언니 입점", "강언"],
        "secondary": ["입점", "이벤트", "병원"],
        "exclusions": ["바비톡", "여신티켓"],
    },
    "바비톡": {
        "primary": ["바비톡", "바비톡 이벤트", "바비톡 성형", "바비톡 할인", "바비톡 후기"],
        "secondary": ["이벤트", "할인", "후기", "병원"],
        "exclusions": ["강남언니", "여신티켓"],
    },
    "여신티켓": {
        "primary": ["여신티켓", "여신티켓 시술", "여신티켓 피부과", "여신티켓 예약", "여티"],
        "secondary": ["시술", "예약", "병원"],
        "exclusions": ["강남언니", "바비톡"],
    },
    "남성제모": {
        "primary": ["남성제모", "남자제모", "수염제모", "턱수염제모", "인중제모", "젠틀맥스"],
        "secondary": ["제모", "피부과"],
        "exclusions": ["여성제모", "브라질리언", "비키니제모", "겨드랑이제모", "다리제모"],
    },
    "여성제모": {
        "primary": ["여성제모", "브라질리언", "브라질리언제모", "레이저제모", "비키니제모", "겨드랑이제모", "다리제모", "팔제모"],
        "secondary": ["제모", "피부과"],
        "exclusions": ["남성제모", "남자제모", "수염제모", "턱수염제모"],
    },
    "임플란트": {
        "primary": ["임플란트", "오스템", "네비게이션임플란트", "전체임플란트", "원데이임플란트"],
        "secondary": ["치과", "치아", "올온", "all-on"],
        "exclusions": ["피부과", "안과", "성형외과", "네일"],
    },
    "라미네이트": {
        "primary": ["라미네이트", "무삭제라미네이트", "치아성형", "최소삭제라미네이트"],
        "secondary": ["치아", "심미보철", "치과"],
        "exclusions": ["네일", "속눈썹", "성형외과", "안과", "피부과"],
    },
    "리프팅": {
        "primary": ["리프팅", "울쎄라", "써마지", "인모드", "슈링크", "세르프", "울쎄라피", "실리프팅"],
        "secondary": ["탄력", "주름", "피부과"],
        "exclusions": ["안면거상", "미니거상", "거상수술", "브라", "괄사", "입술성형", "필러", "보톡스", "리쥬란", "쥬베룩", "가슴수술", "가슴성형", "쌍꺼풀", "상안검", "하안검"],
    },
    "울쎄라": {
        "primary": ["울쎄라", "울쎄라 리프팅", "울쎄라 정품팁", "울쎄라 600샷"],
        "secondary": ["프리미엄 리프팅", "리프팅", "피부과"],
        "exclusions": ["써마지", "인모드", "슈링크", "안면거상"],
    },
    "안면거상": {
        "primary": ["안면거상", "미니거상", "실리프팅", "안면거상술", "거상수술"],
        "secondary": ["거상", "성형외과"],
        "exclusions": ["울쎄라", "써마지", "인모드", "슈링크", "라식", "라섹", "임플란트", "라미네이트"],
    },
    "피부/쁘띠": {
        "primary": ["리쥬란", "쥬베룩", "보톡스", "필러", "스킨부스터"],
        "secondary": ["물광", "엑소좀", "피부과", "포텐자"],
        "exclusions": ["울쎄라", "써마지", "인모드", "리프팅", "제모", "라식", "라섹", "임플란트", "라미네이트", "눈성형", "코성형", "가슴성형"],
    },
    "스킨부스터": {
        "primary": ["스킨부스터", "리쥬란", "쥬베룩", "엑소좀", "샤넬주사"],
        "secondary": ["피부 물광", "물광", "피부과"],
        "exclusions": ["울쎄라", "써마지", "인모드", "리프팅", "필러", "보톡스"],
    },
    "눈성형": {
        "primary": ["쌍꺼풀", "쌍커풀", "눈매교정", "앞트임", "눈성형", "트임", "눈재수술"],
        "secondary": ["상안검", "하안검", "성형외과"],
        "exclusions": ["안과", "라식", "라섹", "백내장", "가슴수술", "가슴성형", "입술성형", "필러", "리프팅", "안면거상"],
    },
    "코성형": {
        "primary": ["코성형", "기능코", "자가늑", "코수술", "코재수술", "휜코", "매부리코", "복코", "코끝수술"],
        "secondary": ["비중격", "성형외과"],
        "exclusions": ["안과", "피부과", "치과"],
    },
    "가슴성형": {
        "primary": ["가슴성형", "모티바", "세빈", "가슴수술", "가슴거상", "보형물", "가슴확대", "유방거상"],
        "secondary": ["성형외과"],
        "exclusions": ["브라", "속옷", "리프트업브라", "눈성형", "쌍꺼풀", "상안검", "하안검", "눈매교정", "트임", "코성형", "입술성형", "필러", "리프팅"],
    },
    "시력교정": {
        "primary": ["스마일라식", "라섹", "렌즈삽입술", "렌즈삽입", "라식", "icl"],
        "secondary": ["시력교정", "안과"],
        "exclusions": ["눈성형", "쌍꺼풀", "상안검", "하안검", "눈매교정", "트임"],
    },
}

FOOTER_SPLIT_MARKERS = [
    "📍 오시는 길",
    "오시는 길",
    "위치안내",
    "전화문의",
    "카카오톡",
    "진료과목",
    "프로필",
    "예약문의",
    "문의전화",
    "상담문의",
]

MEDICAL_CONTEXT_KEYWORDS = [
    "병원",
    "의원",
    "클리닉",
    "치과",
    "안과",
    "성형외과",
    "피부과",
    "hospital",
    "clinic",
    "medical",
    "dermatologist",
    "dental clinic",
]

PROVIDER_CONTEXT_KEYWORDS = [
    "병원",
    "의원",
    "클리닉",
    "hospital",
    "clinic",
    "medical",
    "dermatologist",
    "dental clinic",
]

COMMERCE_KEYWORDS = [
    "{{product",
    "공식몰",
    "결제",
    "주문",
    "배송",
    "스토어",
    "store",
    "세럼",
    "크림",
    "앰플",
    "선크림",
    "1+1",
    "세트",
    "브랜드",
    "입점",
    "자외선 차단",
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ensure_dirs() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def table_columns(conn: sqlite3.Connection, table_name: str) -> set:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, ddl_fragment: str) -> None:
    if column_name not in table_columns(conn, table_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {ddl_fragment}")


def init_db() -> None:
    ensure_dirs()
    with connect_db() as conn:
        existing_columns = table_columns(conn, "ads")
        if existing_columns and "row_key" not in existing_columns:
            conn.execute("DROP TABLE IF EXISTS ads")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ads (
                row_key TEXT PRIMARY KEY,
                ad_id TEXT NOT NULL,
                brand_name TEXT,
                category TEXT NOT NULL,
                query TEXT NOT NULL,
                page_name TEXT NOT NULL,
                title TEXT,
                body_text TEXT,
                image_url TEXT,
                asset_path TEXT,
                image_path TEXT,
                library_url TEXT NOT NULL,
                days_live INTEGER NOT NULL,
                days_active INTEGER,
                start_ts INTEGER NOT NULL,
                published_date TEXT,
                start_date TEXT,
                media_type TEXT,
                raw_snapshot TEXT,
                first_collected_at TEXT NOT NULL,
                last_collected_at TEXT NOT NULL,
                is_saved INTEGER NOT NULL DEFAULT 0,
                analysis_status TEXT NOT NULL DEFAULT 'pending',
                analysis_text TEXT,
                ai_analysis TEXT,
                analysis_error TEXT,
                analyzed_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_ads_category_start ON ads(category, start_ts);
            CREATE INDEX IF NOT EXISTS idx_ads_status ON ads(analysis_status, analyzed_at);

            CREATE TABLE IF NOT EXISTS analysis_cache (
                ad_id TEXT PRIMARY KEY,
                image_url TEXT,
                asset_path TEXT,
                mime_type TEXT,
                analysis_status TEXT NOT NULL,
                analysis_text TEXT,
                analysis_error TEXT,
                analyzed_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_analysis_cache_status ON analysis_cache(analysis_status, analyzed_at);
            """
        )
        ensure_column(conn, "ads", "brand_name", "brand_name TEXT")
        ensure_column(conn, "ads", "published_date", "published_date TEXT")
        ensure_column(conn, "ads", "start_date", "start_date TEXT")
        ensure_column(conn, "ads", "media_type", "media_type TEXT")
        ensure_column(conn, "ads", "image_path", "image_path TEXT")
        ensure_column(conn, "ads", "days_active", "days_active INTEGER")
        ensure_column(conn, "ads", "ai_analysis", "ai_analysis TEXT")
        ensure_column(conn, "ads", "is_saved", "is_saved INTEGER NOT NULL DEFAULT 0")
        backfill_ads_metadata(conn)
        conn.commit()


def library_url(ad_id: str) -> str:
    return f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=KR&id={ad_id}"


def score_candidate(category: str, page_name: str, text_blob: str) -> int:
    category_name, score, _ = classify_ad_category(page_name, "", text_blob)
    if category_name != category:
        return 0
    return score


def normalize_text(value: Optional[str]) -> str:
    return " ".join(str(value or "").lower().split())


def trim_footer_text(value: Optional[str]) -> str:
    text = str(value or "")
    cutoff = len(text)
    for marker in FOOTER_SPLIT_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            cutoff = min(cutoff, idx)
    return text[:cutoff].strip()


def keyword_count(text: str, keywords: List[str]) -> int:
    return sum(text.count(keyword.lower()) for keyword in keywords)


def first_keyword_position(text: str, keywords: List[str]) -> int:
    positions = [text.find(keyword.lower()) for keyword in keywords if keyword.lower() in text]
    return min(positions) if positions else 10**9


def classify_ad_category(page_name: str, title: str, body_text: str) -> Tuple[Optional[str], int, Dict[str, int]]:
    cleaned_body = trim_footer_text(body_text)
    title_text = normalize_text(f"{page_name} {title}")
    lead_text = normalize_text(f"{page_name} {title} {cleaned_body[:LEAD_BODY_CHARS]}")
    full_text = normalize_text(f"{page_name} {title} {cleaned_body}")
    medical_hits = keyword_count(full_text, MEDICAL_CONTEXT_KEYWORDS)
    provider_hits = keyword_count(full_text, PROVIDER_CONTEXT_KEYWORDS)
    commerce_hits = keyword_count(full_text, COMMERCE_KEYWORDS)
    scores: Dict[str, int] = {}
    ranked: List[Tuple[str, int, int, int]] = []

    if "{{product" in full_text:
        return None, 0, {}

    if any(keyword.lower() in full_text for keyword in CATEGORY_RULES["강남언니"]["primary"]):
        return "강남언니", max(CLASSIFICATION_MIN_SCORE, 26), {"강남언니": 26}
    if any(keyword.lower() in full_text for keyword in CATEGORY_RULES["바비톡"]["primary"]):
        return "바비톡", max(CLASSIFICATION_MIN_SCORE, 26), {"바비톡": 26}
    if any(keyword.lower() in full_text for keyword in CATEGORY_RULES["여신티켓"]["primary"]):
        return "여신티켓", max(CLASSIFICATION_MIN_SCORE, 26), {"여신티켓": 26}
    if any(keyword.lower() in full_text for keyword in CATEGORY_RULES["울쎄라"]["primary"]):
        return "울쎄라", max(CLASSIFICATION_MIN_SCORE, 24), {"울쎄라": 24}
    if any(keyword.lower() in full_text for keyword in CATEGORY_RULES["스킨부스터"]["primary"]):
        return "스킨부스터", max(CLASSIFICATION_MIN_SCORE, 24), {"스킨부스터": 24}
    if any(keyword.lower() in full_text for keyword in CATEGORY_RULES["남성제모"]["primary"]):
        return "남성제모", max(CLASSIFICATION_MIN_SCORE, 24), {"남성제모": 24}

    for category, rule in CATEGORY_RULES.items():
        title_primary = keyword_count(title_text, rule["primary"])
        lead_primary = keyword_count(lead_text, rule["primary"])
        full_primary = keyword_count(full_text, rule["primary"])
        title_secondary = keyword_count(title_text, rule["secondary"])
        lead_secondary = keyword_count(lead_text, rule["secondary"])
        full_secondary = keyword_count(full_text, rule["secondary"])
        exclusion_hits = keyword_count(full_text, rule["exclusions"])
        cross_lead_primary = 0
        cross_full_primary = 0

        for other_category, other_rule in CATEGORY_RULES.items():
            if other_category == category:
                continue
            cross_lead_primary += keyword_count(lead_text, other_rule["primary"])
            cross_full_primary += keyword_count(full_text, other_rule["primary"])

        if title_primary + lead_primary == 0 and full_primary < 2:
            scores[category] = -10**6
            continue

        keyword_position = first_keyword_position(full_text, rule["primary"])
        score = (
            title_primary * 18
            + lead_primary * 14
            + full_primary * 4
            + title_secondary * 5
            + lead_secondary * 3
            + full_secondary
            - exclusion_hits * 12
            - cross_lead_primary * 8
            - cross_full_primary * 2
        )
        if commerce_hits and medical_hits == 0:
            score -= commerce_hits * 18
        if medical_hits == 0 and category in {"시력교정", "임플란트", "라미네이트", "눈성형", "코성형", "가슴성형", "안면거상"}:
            score -= 12
        if category == "피부/쁘띠":
            skin_specific_primary = keyword_count(
                full_text,
                [keyword for keyword in rule["primary"] if keyword != "스킨부스터"],
            )
            if commerce_hits and provider_hits == 0:
                scores[category] = -10**6
                continue
            if commerce_hits and (medical_hits <= 1 or skin_specific_primary == 0):
                score -= 24
            if skin_specific_primary == 0 and title_primary + lead_primary <= 1:
                score -= 12
        if keyword_position > LEAD_BODY_CHARS:
            score -= 6
        scores[category] = score
        ranked.append((category, score, keyword_position, lead_primary + title_primary))

    ranked = [item for item in ranked if item[1] > -10**5]
    if not ranked:
        return None, 0, scores
    ranked.sort(key=lambda item: (item[1], -item[2], item[3]), reverse=True)
    best_category, best_score, _, _ = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else -10**9

    if best_score < CLASSIFICATION_MIN_SCORE:
        return None, 0, scores
    if second_score >= CLASSIFICATION_MIN_SCORE and best_score - second_score < CLASSIFICATION_MARGIN:
        return None, 0, scores
    return best_category, best_score, scores


def matches_category_by_keyword(category: str, page_name: str, title: str, body_text: str, query: Optional[str] = None) -> bool:
    full_text = normalize_text(f"{page_name} {title} {trim_footer_text(body_text)}")
    keywords = list(CATEGORY_RULES[category]["primary"]) + list(CATEGORY_RULES[category]["secondary"])
    if query:
        keywords.append(query)
    return any(keyword.lower() in full_text for keyword in keywords if keyword)


def published_date_from_timestamp(timestamp: int) -> str:
    return datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d")


def asset_identity_value(image_url_value: Optional[str]) -> str:
    raw_value = (image_url_value or "").strip()
    if not raw_value:
        return ""
    parsed = urlsplit(raw_value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def asset_identity_hash(image_url_value: Optional[str]) -> str:
    identity = asset_identity_value(image_url_value) or "no-asset"
    return hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]


def build_row_key(category: str, image_url_value: Optional[str]) -> str:
    return f"{category}::{asset_identity_hash(image_url_value)}"


def parse_start_date_value(start_date_value: Optional[str]) -> date:
    if not start_date_value:
        return date.max
    try:
        return datetime.strptime(start_date_value, "%Y-%m-%d").date()
    except ValueError:
        return date.max


def creative_priority_key(start_date_value: Optional[str], start_ts_value: Optional[int]) -> Tuple[date, int]:
    timestamp = start_ts_value if isinstance(start_ts_value, int) else 2**31 - 1
    return (parse_start_date_value(start_date_value), timestamp)


def iter_nested_items(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from iter_nested_items(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_nested_items(item)


def extract_video_asset_url(snapshot: Dict) -> Optional[str]:
    direct_candidates = [
        snapshot.get("video_url"),
        snapshot.get("video_hd_url"),
        snapshot.get("video_sd_url"),
        snapshot.get("playable_url"),
        snapshot.get("source"),
    ]
    for candidate in direct_candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    for video in snapshot.get("videos") or []:
        for key in ("video_url", "video_hd_url", "video_sd_url", "playable_url", "source"):
            candidate = video.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()

    for key, value in iter_nested_items(snapshot):
        if key in {"video_url", "video_hd_url", "video_sd_url", "playable_url", "source"} and isinstance(value, str) and value.strip():
            return value.strip()
    return None


def has_video_signal(snapshot: Dict) -> bool:
    display_format = str(snapshot.get("display_format") or "").upper()
    if display_format == "VIDEO":
        return True
    if snapshot.get("videos") or snapshot.get("video_preview_image_url"):
        return True
    if extract_video_asset_url(snapshot):
        return True
    for key, value in iter_nested_items(snapshot):
        if key in {"video_id", "video_ids"} and value:
            return True
        if key in {"video_data", "video_asset"} and value:
            return True
    return False


def has_carousel_signal(snapshot: Dict) -> bool:
    cards = snapshot.get("cards") or []
    if len(cards) > 1:
        return True
    for key, value in iter_nested_items(snapshot):
        if key == "ad_creative_link_captions" and isinstance(value, list) and len(value) > 1:
            return True
        if key == "child_attachments" and isinstance(value, list) and len(value) > 1:
            return True
    return False


def extract_asset_url(snapshot: Dict) -> Optional[str]:
    return extract_video_asset_url(snapshot) or image_url(snapshot)


def is_valid_candidate(candidate: Dict) -> bool:
    required_values = [
        candidate.get("ad_id"),
        candidate.get("brand_name"),
        candidate.get("category"),
        candidate.get("library_url"),
        candidate.get("start_date"),
        candidate.get("media_type"),
        candidate.get("image_url"),
        candidate.get("asset_url"),
    ]
    return all(bool(value) for value in required_values)


def dedupe_candidates_by_asset(candidates: List[Dict]) -> Tuple[List[Dict], int]:
    best_by_asset: Dict[str, Dict] = {}
    duplicates_removed = 0

    for candidate in candidates:
        asset_key = asset_identity_value(candidate.get("asset_url")) or "__no_asset__"
        incumbent = best_by_asset.get(asset_key)
        if incumbent is None:
            best_by_asset[asset_key] = candidate
            continue

        incumbent_key = creative_priority_key(incumbent.get("start_date"), incumbent.get("start_ts"))
        candidate_key = creative_priority_key(candidate.get("start_date"), candidate.get("start_ts"))
        if candidate_key < incumbent_key:
            best_by_asset[asset_key] = candidate
        duplicates_removed += 1

    deduped = sorted(
        best_by_asset.values(),
        key=lambda item: (-item["days_active"], item["start_ts"], item["ad_id"]),
    )
    return deduped, duplicates_removed


def compute_days_active(start_date_value: Optional[str]) -> Optional[int]:
    if not start_date_value:
        return None
    try:
        started_at = datetime.strptime(start_date_value, "%Y-%m-%d").date()
    except ValueError:
        return None
    return max((date.today() - started_at).days, 0)


def infer_media_type(snapshot: Dict) -> str:
    display_format = str(snapshot.get("display_format") or "").upper()
    images = snapshot.get("images") or []

    if has_video_signal(snapshot):
        return MEDIA_TYPE_VIDEO
    if has_carousel_signal(snapshot) or (display_format in {"CAROUSEL", "MULTI_IMAGES"} and (snapshot.get("cards") or [])):
        return MEDIA_TYPE_CAROUSEL
    if display_format == "IMAGE" or images or snapshot.get("original_image_url") or snapshot.get("resized_image_url"):
        return MEDIA_TYPE_IMAGE
    return MEDIA_TYPE_IMAGE


def extract_published_date(result: Dict) -> str:
    timestamp = result.get("start_date") or start_timestamp(result)
    return published_date_from_timestamp(timestamp)


def backfill_ads_metadata(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT
            row_key,
            start_ts,
            raw_snapshot,
            published_date,
            media_type,
            page_name,
            asset_path,
            image_path,
            days_live,
            analysis_text,
            ai_analysis,
            brand_name,
            start_date,
            days_active
        FROM ads
        WHERE
            published_date IS NULL OR
            media_type IS NULL OR
            brand_name IS NULL OR
            start_date IS NULL OR
            image_path IS NULL OR
            days_active IS NULL OR
            ai_analysis IS NULL
        """
    ).fetchall()

    for row in rows:
        snapshot = {}
        if row["raw_snapshot"]:
            try:
                snapshot = json.loads(row["raw_snapshot"])
            except json.JSONDecodeError:
                snapshot = {}

        published_date = row["published_date"] or published_date_from_timestamp(row["start_ts"])
        media_type = row["media_type"] or infer_media_type(snapshot)
        brand_name = row["brand_name"] or row["page_name"]
        start_date = row["start_date"] or published_date
        image_path = row["image_path"] or row["asset_path"]
        days_active = row["days_active"] or compute_days_active(start_date) or row["days_live"]
        ai_analysis = row["ai_analysis"] or row["analysis_text"]
        conn.execute(
            """
            UPDATE ads
            SET published_date = ?,
                media_type = ?,
                brand_name = ?,
                start_date = ?,
                image_path = ?,
                days_active = ?,
                ai_analysis = ?
            WHERE row_key = ?
            """,
            (
                published_date,
                media_type,
                brand_name,
                start_date,
                image_path,
                days_active,
                ai_analysis,
                row["row_key"],
            ),
        )


def collect_category(session: requests.Session, category: str, limit: int) -> Tuple[List[Dict], List[str], Dict[str, int]]:
    config = CATEGORY_CONFIG[category]
    candidates: List[Dict] = []
    failures: List[str] = []
    stats = {
        "raw_results": 0,
        "matched_ads": 0,
        "validated_ads": 0,
        "duplicates_removed": 0,
        "accepted_ads": 0,
    }

    for query in config["queries"]:
        time.sleep(random.uniform(*QUERY_SLEEP_RANGE_SECONDS))
        try:
            payload = fetch_results(session, query)
        except Exception as exc:
            failures.append(f"{category} 수집 실패({query}): {exc}")
            continue

        for edge in payload.get("edges", []):
            for result in edge.get("node", {}).get("collated_results", []):
                stats["raw_results"] += 1
                ad_id = str(result.get("ad_archive_id") or result.get("ad_id") or "")
                snapshot = result.get("snapshot") or {}
                render_url = image_url(snapshot)
                asset_url = extract_asset_url(snapshot)
                if not ad_id:
                    continue

                page_name = snapshot.get("page_name") or "알 수 없음"
                text_blob = snapshot_text(snapshot)
                title = snapshot.get("title") or ""
                classified_category, score, _ = classify_ad_category(page_name, title, text_blob)
                keyword_matched = matches_category_by_keyword(category, page_name, title, text_blob, query)
                if classified_category != category and not keyword_matched:
                    continue
                if classified_category == category and score < CLASSIFICATION_MIN_SCORE and not keyword_matched:
                    continue
                stats["matched_ads"] += 1

                candidate = {
                    "ad_id": ad_id,
                    "category": category,
                    "query": query,
                    "page_name": page_name,
                    "brand_name": page_name,
                    "title": title,
                    "body_text": text_blob,
                    "asset_url": asset_url,
                    "image_url": render_url,
                    "library_url": library_url(ad_id),
                    "days_live": days_live(result),
                    "days_active": compute_days_active(extract_published_date(result)) or days_live(result),
                    "start_ts": start_timestamp(result),
                    "published_date": extract_published_date(result),
                    "start_date": extract_published_date(result),
                    "media_type": infer_media_type(snapshot),
                    "raw_snapshot": json.dumps(snapshot, ensure_ascii=False),
                }
                if not is_valid_candidate(candidate):
                    continue
                stats["validated_ads"] += 1

                candidates.append(candidate)

    deduped_candidates, duplicates_removed = dedupe_candidates_by_asset(candidates)
    stats["duplicates_removed"] = duplicates_removed
    stats["accepted_ads"] = len(deduped_candidates[:limit])
    return deduped_candidates[:limit], failures, stats


def upsert_ads(conn: sqlite3.Connection, ads: Iterable[Dict]) -> int:
    saved = 0
    for ad in ads:
        row_key = build_row_key(ad["category"], ad.get("asset_url"))
        existing = conn.execute(
            """
            SELECT analysis_status, analysis_text, analysis_error, analyzed_at, first_collected_at, asset_path, is_saved,
                   ad_id, brand_name, category, query, page_name, title, body_text, image_url, library_url, days_live,
                   days_active, start_ts, published_date, start_date, media_type, raw_snapshot
            FROM ads
            WHERE row_key = ?
            LIMIT 1
            """,
            (row_key,),
        ).fetchone()
        first_collected_at = existing["first_collected_at"] if existing else now_iso()
        is_saved = existing["is_saved"] if existing else 0
        analysis_status = existing["analysis_status"] if existing else "pending"
        analysis_text = existing["analysis_text"] if existing else None
        analysis_error = existing["analysis_error"] if existing else None
        analyzed_at = existing["analyzed_at"] if existing else None
        asset_path = existing["asset_path"] if existing else None
        image_path = asset_path
        creative_fields = {
            "ad_id": ad["ad_id"],
            "brand_name": ad["brand_name"],
            "category": ad["category"],
            "query": ad["query"],
            "page_name": ad["page_name"],
            "title": ad["title"],
            "body_text": ad["body_text"],
            "image_url": ad["image_url"],
            "library_url": ad["library_url"],
            "days_live": ad["days_live"],
            "days_active": ad["days_active"],
            "start_ts": ad["start_ts"],
            "published_date": ad["published_date"],
            "start_date": ad["start_date"],
            "media_type": ad["media_type"],
            "raw_snapshot": ad["raw_snapshot"],
        }
        if existing:
            existing_key = creative_priority_key(existing["start_date"], existing["start_ts"])
            incoming_key = creative_priority_key(ad["start_date"], ad["start_ts"])
            if existing_key <= incoming_key:
                creative_fields.update(
                    {
                        "ad_id": existing["ad_id"],
                        "brand_name": existing["brand_name"],
                        "category": existing["category"],
                        "query": existing["query"],
                        "page_name": existing["page_name"],
                        "title": existing["title"],
                        "body_text": existing["body_text"],
                        "image_url": existing["image_url"],
                        "library_url": existing["library_url"],
                        "days_live": existing["days_live"],
                        "days_active": existing["days_active"],
                        "start_ts": existing["start_ts"],
                        "published_date": existing["published_date"],
                        "start_date": existing["start_date"],
                        "media_type": existing["media_type"],
                        "raw_snapshot": existing["raw_snapshot"],
                    }
                )

        conn.execute(
            """
            INSERT INTO ads (
                row_key, ad_id, brand_name, category, query, page_name, title, body_text, image_url, asset_path, image_path,
                library_url, days_live, days_active, start_ts, published_date, start_date, media_type, raw_snapshot,
                first_collected_at, last_collected_at, is_saved,
                analysis_status, analysis_text, ai_analysis, analysis_error, analyzed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(row_key) DO UPDATE SET
                brand_name = excluded.brand_name,
                category = excluded.category,
                query = excluded.query,
                page_name = excluded.page_name,
                title = excluded.title,
                body_text = excluded.body_text,
                image_url = excluded.image_url,
                image_path = COALESCE(excluded.image_path, ads.image_path),
                library_url = excluded.library_url,
                days_live = excluded.days_live,
                days_active = excluded.days_active,
                start_ts = excluded.start_ts,
                published_date = excluded.published_date,
                start_date = excluded.start_date,
                media_type = excluded.media_type,
                raw_snapshot = excluded.raw_snapshot,
                last_collected_at = excluded.last_collected_at
            """,
            (
                row_key,
                creative_fields["ad_id"],
                creative_fields["brand_name"],
                creative_fields["category"],
                creative_fields["query"],
                creative_fields["page_name"],
                creative_fields["title"],
                creative_fields["body_text"],
                creative_fields["image_url"],
                asset_path,
                image_path,
                creative_fields["library_url"],
                creative_fields["days_live"],
                creative_fields["days_active"],
                creative_fields["start_ts"],
                creative_fields["published_date"],
                creative_fields["start_date"],
                creative_fields["media_type"],
                creative_fields["raw_snapshot"],
                first_collected_at,
                now_iso(),
                is_saved,
                analysis_status,
                analysis_text,
                analysis_text,
                analysis_error,
                analyzed_at,
            ),
        )
        saved += 1
    conn.commit()
    return saved


def prune_category_ads(conn: sqlite3.Connection, category: str, ads: List[Dict]) -> None:
    valid_row_keys = {build_row_key(category, ad.get("asset_url")) for ad in ads}
    existing_rows = conn.execute(
        """
        SELECT row_key
        FROM ads
        WHERE category = ?
        """,
        (category,),
    ).fetchall()
    stale_row_keys = [row["row_key"] for row in existing_rows if row["row_key"] not in valid_row_keys]
    if not stale_row_keys:
        return

    conn.executemany(
        """
        DELETE FROM ads
        WHERE row_key = ?
        """,
        [(row_key,) for row_key in stale_row_keys],
    )
    conn.commit()


def collect_to_db(limit_per_category: int = DEFAULT_LIMIT_PER_CATEGORY) -> Dict[str, object]:
    init_db()
    session = build_session()
    summary = {
        "saved": 0,
        "counts": {},
        "failures": {},
        "search_results": {},
        "matched_ads": {},
        "validated_ads": {},
        "duplicates_removed": {},
    }
    with connect_db() as conn:
        for category in CATEGORY_CONFIG:
            ads, failures, stats = collect_category(session, category, limit_per_category)
            summary["counts"][category] = len(ads)
            summary["failures"][category] = failures
            summary["search_results"][category] = stats["raw_results"]
            summary["matched_ads"][category] = stats["matched_ads"]
            summary["validated_ads"][category] = stats["validated_ads"]
            summary["duplicates_removed"][category] = stats["duplicates_removed"]
            saved_count = upsert_ads(conn, ads)
            summary["saved"] += saved_count
            print(
                f"[{category}] 전체 수집 개수: {stats['validated_ads']} | 중복 제거 후 최종 개수: {len(ads)} | "
                f"검색 결과 수: {stats['raw_results']} | 중복 제거 수: {stats['duplicates_removed']} | upsert 수: {saved_count}"
            )
        summary["reindexed"] = reindex_ads(conn, delete_unclassified=False)
        print(
            f"[전체] 전체 수집 개수: {sum(summary['validated_ads'].values())} | "
            f"중복 제거 후 최종 개수: {sum(summary['counts'].values())}"
        )
    return summary


def build_search_queries(search_term: str) -> List[str]:
    normalized = " ".join((search_term or "").split()).strip()
    if not normalized:
        return []

    queries: List[str] = [normalized]
    collapsed = normalized.replace(" ", "")
    if collapsed and collapsed != normalized:
        queries.append(collapsed)

    for token in normalized.split():
        if len(token) >= 2:
            queries.append(token)

    deduped: List[str] = []
    seen = set()
    for query in queries:
        lowered = query.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(query)
    return deduped


def matches_search_term(search_term: str, page_name: str, title: str, body_text: str) -> bool:
    normalized_term = " ".join((search_term or "").split()).strip().lower()
    if not normalized_term:
        return False

    collapsed_term = normalized_term.replace(" ", "")
    haystacks = [
        (page_name or "").lower(),
        (title or "").lower(),
        (body_text or "").lower(),
    ]
    return any(
        normalized_term in haystack or (collapsed_term and collapsed_term in haystack.replace(" ", ""))
        for haystack in haystacks
    )


def collect_search_term(session: requests.Session, search_term: str, limit: int = DEFAULT_LIMIT_PER_SEARCH) -> Tuple[List[Dict], List[str], Dict[str, int]]:
    candidates: List[Dict] = []
    failures: List[str] = []
    stats = {
        "raw_results": 0,
        "matched_ads": 0,
        "validated_ads": 0,
        "duplicates_removed": 0,
        "accepted_ads": 0,
    }

    for query in build_search_queries(search_term):
        time.sleep(random.uniform(*QUERY_SLEEP_RANGE_SECONDS))
        try:
            payload = fetch_results(session, query)
        except Exception as exc:
            failures.append(f"{search_term} 수집 실패({query}): {exc}")
            continue

        for edge in payload.get("edges", []):
            for result in edge.get("node", {}).get("collated_results", []):
                stats["raw_results"] += 1
                ad_id = str(result.get("ad_archive_id") or result.get("ad_id") or "")
                snapshot = result.get("snapshot") or {}
                if not ad_id:
                    continue

                page_name = snapshot.get("page_name") or "알 수 없음"
                title = snapshot.get("title") or ""
                text_blob = snapshot_text(snapshot)
                if not matches_search_term(search_term, page_name, title, text_blob):
                    continue

                stats["matched_ads"] += 1
                classified_category, _, _ = classify_ad_category(page_name, title, text_blob)
                category = classified_category or ETC_CATEGORY
                render_url = image_url(snapshot)
                asset_url = extract_asset_url(snapshot)

                candidate = {
                    "ad_id": ad_id,
                    "category": category,
                    "query": query,
                    "page_name": page_name,
                    "brand_name": page_name,
                    "title": title,
                    "body_text": text_blob,
                    "asset_url": asset_url,
                    "image_url": render_url,
                    "library_url": library_url(ad_id),
                    "days_live": days_live(result),
                    "days_active": compute_days_active(extract_published_date(result)) or days_live(result),
                    "start_ts": start_timestamp(result),
                    "published_date": extract_published_date(result),
                    "start_date": extract_published_date(result),
                    "media_type": infer_media_type(snapshot),
                    "raw_snapshot": json.dumps(snapshot, ensure_ascii=False),
                }
                if not is_valid_candidate(candidate):
                    continue
                stats["validated_ads"] += 1
                candidates.append(candidate)

    deduped_candidates, duplicates_removed = dedupe_candidates_by_asset(candidates)
    stats["duplicates_removed"] = duplicates_removed
    stats["accepted_ads"] = len(deduped_candidates[:limit])
    return deduped_candidates[:limit], failures, stats


def fetch_now_to_db(search_terms: Iterable[str], limit_per_search: int = DEFAULT_LIMIT_PER_SEARCH) -> Dict[str, object]:
    init_db()
    session = build_session()
    normalized_terms = [str(term).strip() for term in search_terms if str(term or "").strip()]
    summary = {
        "saved": 0,
        "counts": {},
        "failures": {},
        "search_results": {},
        "matched_ads": {},
        "validated_ads": {},
        "duplicates_removed": {},
        "terms": normalized_terms,
    }

    with connect_db() as conn:
        for search_term in normalized_terms:
            ads, failures, stats = collect_search_term(session, search_term, limit_per_search)
            saved_count = upsert_ads(conn, ads)
            summary["saved"] += saved_count
            summary["counts"][search_term] = len(ads)
            summary["failures"][search_term] = failures
            summary["search_results"][search_term] = stats["raw_results"]
            summary["matched_ads"][search_term] = stats["matched_ads"]
            summary["validated_ads"][search_term] = stats["validated_ads"]
            summary["duplicates_removed"][search_term] = stats["duplicates_removed"]
        summary["reindexed"] = reindex_ads(conn, delete_unclassified=False)

    return summary


def reindex_ads(conn: sqlite3.Connection, delete_unclassified: bool = False) -> Dict[str, int]:
    rows = conn.execute(
        """
        SELECT
            row_key,
            ad_id,
            category,
            query,
            image_url,
            raw_snapshot,
            page_name,
            title,
            body_text,
            start_date,
            start_ts,
            days_active,
            last_collected_at
        FROM ads
        ORDER BY COALESCE(image_url, '') ASC, COALESCE(start_date, '') ASC, COALESCE(start_ts, 0) ASC, last_collected_at DESC
        """
    ).fetchall()

    candidates_by_asset: Dict[str, List[Tuple[sqlite3.Row, Optional[str], int]]] = {}
    for row in rows:
        new_category, score, _ = classify_ad_category(
            row["page_name"],
            row["title"] or "",
            row["body_text"] or "",
        )
        snapshot = {}
        if row["raw_snapshot"]:
            try:
                snapshot = json.loads(row["raw_snapshot"])
            except json.JSONDecodeError:
                snapshot = {}
        asset_key = asset_identity_hash(extract_asset_url(snapshot) or row["image_url"])
        candidates_by_asset.setdefault(asset_key, []).append((row, new_category, score))

    updated = 0
    deleted = 0
    kept = 0

    for asset_key, candidates in candidates_by_asset.items():
        representative = candidates[0][0]
        ad_id = representative["ad_id"]
        representative_snapshot = {}
        if representative["raw_snapshot"]:
            try:
                representative_snapshot = json.loads(representative["raw_snapshot"])
            except json.JSONDecodeError:
                representative_snapshot = {}
        image_url_value = extract_asset_url(representative_snapshot) or representative["image_url"]
        valid_candidates = [item for item in candidates if item[1]]
        if not valid_candidates:
            best_row = sorted(
                candidates,
                key=lambda item: (
                    parse_start_date_value(item[0]["start_date"]),
                    item[0]["start_ts"] or 2**31 - 1,
                    -(item[0]["days_active"] or 0),
                ),
            )[0][0]
            target_row_key = build_row_key(ETC_CATEGORY, image_url_value)
            rows_to_delete = [row["row_key"] for row, _, _ in candidates if row["row_key"] != best_row["row_key"]]
            if rows_to_delete:
                conn.executemany(
                    "DELETE FROM ads WHERE row_key = ?",
                    [(row_key,) for row_key in rows_to_delete],
                )
                deleted += len(rows_to_delete)
            if best_row["row_key"] != target_row_key or best_row["category"] != ETC_CATEGORY:
                conn.execute(
                    """
                    UPDATE ads
                    SET row_key = ?,
                        category = ?,
                        query = ?
                    WHERE ad_id = ? AND row_key = ?
                    """,
                    (
                        target_row_key,
                        ETC_CATEGORY,
                        ETC_CATEGORY,
                        ad_id,
                        best_row["row_key"],
                    ),
                )
                updated += 1
            else:
                kept += 1
            continue

        best_row, best_category, _ = sorted(
            valid_candidates,
            key=lambda item: (
                -item[2],
                parse_start_date_value(item[0]["start_date"]),
                -(item[0]["days_active"] or 0),
            ),
        )[0]

        earliest_row = sorted(
            candidates,
            key=lambda item: (
                parse_start_date_value(item[0]["start_date"]),
                item[0]["start_ts"] or 2**31 - 1,
                -(item[0]["days_active"] or 0),
            ),
        )[0][0]
        if earliest_row["row_key"] != best_row["row_key"]:
            best_row = earliest_row

        target_row_key = build_row_key(best_category, image_url_value)
        rows_to_delete = [row["row_key"] for row, _, _ in candidates if row["row_key"] != best_row["row_key"]]
        if rows_to_delete:
            conn.executemany(
                "DELETE FROM ads WHERE row_key = ?",
                [(row_key,) for row_key in rows_to_delete],
            )
            deleted += len(rows_to_delete)

        if best_row["row_key"] != target_row_key or best_row["category"] != best_category or best_row["query"] != CATEGORY_CONFIG[best_category]["queries"][0]:
            conn.execute(
                """
                UPDATE ads
                SET row_key = ?,
                    category = ?,
                    query = ?
                WHERE ad_id = ? AND row_key = ?
                """,
                (
                    target_row_key,
                    best_category,
                    CATEGORY_CONFIG[best_category]["queries"][0],
                    ad_id,
                    best_row["row_key"],
                ),
            )
            updated += 1
        else:
            kept += 1

    conn.commit()
    return {"updated": updated, "deleted": deleted, "kept": kept}


def image_request_session() -> requests.Session:
    session = build_session()
    session.headers.update(
        {
            **HEADERS,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Sec-Fetch-Dest": "image",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site",
        }
    )
    return session


def detect_mime(response: requests.Response) -> str:
    return response.headers.get("content-type", DEFAULT_IMAGE_MIME).split(";")[0].strip() or DEFAULT_IMAGE_MIME


def file_extension_for_mime(mime_type: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(mime_type, ".jpg")


def download_image_to_asset(
    session: requests.Session,
    ad_id: str,
    image_url_value: Optional[str],
) -> Tuple[Optional[bytes], Optional[str], Optional[str], Optional[str]]:
    if not image_url_value:
        return None, None, None, "이미지 URL 없음"

    try:
        response = session.get(image_url_value, timeout=30, allow_redirects=True)
        response.raise_for_status()
    except requests.RequestException as exc:
        return None, None, None, f"이미지 다운로드 실패: {exc}"

    content = response.content
    mime_type = detect_mime(response)
    if not mime_type.startswith("image/"):
        return None, None, None, "이미지 응답이 아님"
    if len(content) < 1024:
        return None, None, None, "이미지 응답이 너무 작음"

    extension = file_extension_for_mime(mime_type)
    asset_path = ASSET_DIR / f"{ad_id}{extension}"
    asset_path.write_bytes(content)
    return content, str(asset_path), mime_type, None


def build_gemini_payload(image_bytes: bytes, mime_type: str) -> Dict:
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    system_prompt = """
너는 병원 광고만 10년 다룬 수석 콘텐츠 디자이너야.
전달받은 이미지 파일을 직접 읽고 분석해.

1단계(검증): 이미지 속 가장 큰 글자 3단어와 배경색을 먼저 적어.
2단계(통찰): 이 디자인이 왜 클릭을 부르는지 디자인 심리학 관점에서 2줄 요약해.

절대 상상해서 쓰지 말고, 이미지가 안 보이면 '로드 실패'라고 솔직하게 말해.
""".strip()
    user_prompt = """
이미지 파일만 보고 한국어로 답해.
첫 줄은 가장 큰 글자 3단어와 배경색을 말해.
그 다음 2줄은 왜 클릭을 부르는지 직관적으로 분석해.
""".strip()
    return {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [
            {
                "parts": [
                    {"text": user_prompt},
                    {"inline_data": {"mime_type": mime_type, "data": encoded}},
                ]
            }
        ],
        "generationConfig": {"temperature": 0.2, "topP": 0.8},
    }


def call_gemini(payload: Dict) -> Tuple[Optional[str], Optional[str]]:
    if not GEMINI_API_KEY:
        return None, "GEMINI_API_KEY 없음"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    for attempt in range(ANALYSIS_MAX_RETRIES):
        try:
            response = requests.post(url, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            text = "\n".join(part.get("text", "") for part in parts if part.get("text")).strip()
            if not text:
                return None, "Gemini 응답 비어 있음"
            return text, None
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code == 429 and attempt < ANALYSIS_MAX_RETRIES - 1:
                time.sleep(ANALYSIS_RETRY_SECONDS)
                continue
            if status_code == 429:
                return RATE_LIMIT_ANALYSIS_MESSAGE, RATE_LIMIT_ANALYSIS_MESSAGE
            return None, f"Gemini 호출 실패: {exc}"
        except requests.RequestException as exc:
            if attempt < ANALYSIS_MAX_RETRIES - 1:
                time.sleep(ANALYSIS_RETRY_SECONDS)
                continue
            return None, f"Gemini 호출 실패: {exc}"
    return None, "Gemini 분석 실패"


def fetch_pending_ads(conn: sqlite3.Connection, limit: Optional[int] = None) -> List[sqlite3.Row]:
    sql = """
        SELECT *
        FROM ads
        WHERE COALESCE(analysis_status, 'pending') = 'pending'
        ORDER BY start_ts ASC, ad_id ASC
    """
    params: Tuple = ()
    if limit:
        sql += " LIMIT ?"
        params = (limit,)
    return list(conn.execute(sql, params).fetchall())


def update_analysis(
    conn: sqlite3.Connection,
    row_key: str,
    analysis_status: str,
    analysis_text: Optional[str],
    analysis_error: Optional[str],
    asset_path: Optional[str],
) -> None:
    conn.execute(
        """
        UPDATE ads
        SET analysis_status = ?,
            analysis_text = ?,
            ai_analysis = ?,
            analysis_error = ?,
            asset_path = COALESCE(?, asset_path),
            image_path = COALESCE(?, image_path),
            analyzed_at = ?
        WHERE row_key = ?
        """,
        (analysis_status, analysis_text, analysis_text, analysis_error, asset_path, asset_path, now_iso(), row_key),
    )
    conn.commit()


def fetch_cached_analysis(conn: sqlite3.Connection, ad_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        """
        SELECT *
        FROM analysis_cache
        WHERE ad_id = ?
        """,
        (ad_id,),
    ).fetchone()


def save_analysis_cache(
    conn: sqlite3.Connection,
    ad_id: str,
    image_url_value: Optional[str],
    asset_path: Optional[str],
    mime_type: Optional[str],
    analysis_status: str,
    analysis_text: Optional[str],
    analysis_error: Optional[str],
) -> None:
    conn.execute(
        """
        INSERT INTO analysis_cache (
            ad_id, image_url, asset_path, mime_type,
            analysis_status, analysis_text, analysis_error, analyzed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ad_id) DO UPDATE SET
            image_url = excluded.image_url,
            asset_path = COALESCE(excluded.asset_path, analysis_cache.asset_path),
            mime_type = COALESCE(excluded.mime_type, analysis_cache.mime_type),
            analysis_status = excluded.analysis_status,
            analysis_text = excluded.analysis_text,
            analysis_error = excluded.analysis_error,
            analyzed_at = excluded.analyzed_at
        """,
        (
            ad_id,
            image_url_value,
            asset_path,
            mime_type,
            analysis_status,
            analysis_text,
            analysis_error,
            now_iso(),
        ),
    )
    conn.commit()


def hydrate_from_cache(conn: sqlite3.Connection, row_key: str, cached_row: sqlite3.Row) -> None:
    conn.execute(
        """
        UPDATE ads
        SET analysis_status = ?,
            analysis_text = ?,
            ai_analysis = ?,
            analysis_error = ?,
            asset_path = COALESCE(?, asset_path),
            image_path = COALESCE(?, image_path),
            analyzed_at = ?
        WHERE row_key = ?
        """,
        (
            cached_row["analysis_status"],
            cached_row["analysis_text"],
            cached_row["analysis_text"],
            cached_row["analysis_error"],
            cached_row["asset_path"],
            cached_row["asset_path"],
            cached_row["analyzed_at"],
            row_key,
        ),
    )
    conn.commit()


def analyze_pending(limit: Optional[int] = None) -> Dict[str, object]:
    init_db()
    image_client = image_request_session()
    summary = {"processed": 0, "completed": 0, "failed": 0, "cached": 0}
    with connect_db() as conn:
        pending = fetch_pending_ads(conn, limit=limit)
        for row in pending:
            cached = fetch_cached_analysis(conn, row["ad_id"])
            if cached and cached["analysis_status"] != "pending":
                hydrate_from_cache(conn, row["row_key"], cached)
                summary["processed"] += 1
                summary["cached"] += 1
                if cached["analysis_status"] == "done":
                    summary["completed"] += 1
                else:
                    summary["failed"] += 1
                continue

            image_bytes, asset_path, mime_type, download_error = download_image_to_asset(
                image_client,
                row["ad_id"],
                row["image_url"],
            )
            if download_error or not image_bytes:
                update_analysis(conn, row["row_key"], "failed", None, download_error, asset_path)
                save_analysis_cache(
                    conn,
                    row["ad_id"],
                    row["image_url"],
                    asset_path,
                    mime_type,
                    "failed",
                    None,
                    download_error,
                )
                summary["processed"] += 1
                summary["failed"] += 1
                time.sleep(ANALYSIS_SLEEP_SECONDS)
                continue

            mime_type = mime_type or DEFAULT_IMAGE_MIME
            payload = build_gemini_payload(image_bytes, mime_type)
            analysis_text, error = call_gemini(payload)
            if analysis_text and not error:
                update_analysis(conn, row["row_key"], "done", analysis_text, None, asset_path)
                save_analysis_cache(
                    conn,
                    row["ad_id"],
                    row["image_url"],
                    asset_path,
                    mime_type,
                    "done",
                    analysis_text,
                    None,
                )
                summary["completed"] += 1
            elif analysis_text == RATE_LIMIT_ANALYSIS_MESSAGE:
                update_analysis(conn, row["row_key"], "rate_limited", analysis_text, RATE_LIMIT_ANALYSIS_MESSAGE, asset_path)
                save_analysis_cache(
                    conn,
                    row["ad_id"],
                    row["image_url"],
                    asset_path,
                    mime_type,
                    "rate_limited",
                    analysis_text,
                    RATE_LIMIT_ANALYSIS_MESSAGE,
                )
                summary["failed"] += 1
            else:
                update_analysis(conn, row["row_key"], "failed", None, error, asset_path)
                save_analysis_cache(
                    conn,
                    row["ad_id"],
                    row["image_url"],
                    asset_path,
                    mime_type,
                    "failed",
                    None,
                    error,
                )
                summary["failed"] += 1

            summary["processed"] += 1
            time.sleep(ANALYSIS_SLEEP_SECONDS)
    return summary


def dump_summary() -> Dict[str, object]:
    init_db()
    with connect_db() as conn:
        counts = {
            row["category"]: row["count"]
            for row in conn.execute(
                "SELECT category, COUNT(*) AS count FROM ads GROUP BY category ORDER BY category"
            ).fetchall()
        }
        status_counts = {
            row["analysis_status"]: row["count"]
            for row in conn.execute(
                "SELECT analysis_status, COUNT(*) AS count FROM ads GROUP BY analysis_status ORDER BY analysis_status"
            ).fetchall()
        }
        cache_counts = {
            row["analysis_status"]: row["count"]
            for row in conn.execute(
                """
                SELECT analysis_status, COUNT(*) AS count
                FROM analysis_cache
                GROUP BY analysis_status
                ORDER BY analysis_status
                """
            ).fetchall()
        }
    return {"db_path": str(DB_PATH), "counts": counts, "status_counts": status_counts, "cache_counts": cache_counts}


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init")

    collect_parser = subparsers.add_parser("collect")
    collect_parser.add_argument("--limit-per-category", type=int, default=DEFAULT_LIMIT_PER_CATEGORY)

    fetch_now_parser = subparsers.add_parser("fetch-now")
    fetch_now_parser.add_argument("--search-term", action="append", required=True)
    fetch_now_parser.add_argument("--limit-per-search", type=int, default=DEFAULT_LIMIT_PER_SEARCH)

    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument("--limit", type=int)

    reindex_parser = subparsers.add_parser("reindex")
    reindex_parser.add_argument("--keep-unclassified", action="store_true")

    subparsers.add_parser("summary")

    args = parser.parse_args()

    if args.command == "init":
        init_db()
        print(json.dumps({"db_path": str(DB_PATH), "status": "initialized"}, ensure_ascii=False, indent=2))
    elif args.command == "collect":
        print(json.dumps(collect_to_db(limit_per_category=args.limit_per_category), ensure_ascii=False, indent=2))
    elif args.command == "fetch-now":
        print(json.dumps(fetch_now_to_db(args.search_term, limit_per_search=args.limit_per_search), ensure_ascii=False, indent=2))
    elif args.command == "analyze":
        print(json.dumps(analyze_pending(limit=args.limit), ensure_ascii=False, indent=2))
    elif args.command == "reindex":
        init_db()
        with connect_db() as conn:
            summary = reindex_ads(conn, delete_unclassified=False)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    elif args.command == "summary":
        print(json.dumps(dump_summary(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
