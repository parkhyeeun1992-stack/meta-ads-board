import argparse
import base64
import json
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

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
DEFAULT_LIMIT_PER_CATEGORY = 10
ANALYSIS_SLEEP_SECONDS = 3
ANALYSIS_RETRY_SECONDS = 20
ANALYSIS_MAX_RETRIES = 3
DEFAULT_IMAGE_MIME = "image/jpeg"
RATE_LIMIT_ANALYSIS_MESSAGE = "⚠️ [이미지 분석 불가] API 요청 한도 초과(429)로 인해 분석이 누락되었습니다."

MEDIA_TYPE_IMAGE = "단일이미지(Image)"
MEDIA_TYPE_VIDEO = "영상(Video)"
MEDIA_TYPE_CAROUSEL = "캐러셀(Carousel)"

CATEGORY_CONFIG = {
    "라미네이트": {
        "queries": ["라미네이트"],
        "signals": ["라미네이트", "치과", "치아", "심미", "미백", "의원", "병원", "클리닉"],
        "exclusions": ["네일", "속눈썹", "피부과", "안과", "성형외과"],
    },
    "임플란트": {
        "queries": ["임플란트"],
        "signals": ["임플란트", "치과", "치아", "의원", "병원", "클리닉"],
        "exclusions": ["피부과", "안과", "성형외과", "네일"],
    },
    "눈성형": {
        "queries": ["눈성형"],
        "signals": ["눈성형", "쌍꺼풀", "트임", "성형외과", "의원", "병원", "클리닉"],
        "exclusions": ["안과", "피부과", "치과", "네일"],
    },
    "코성형": {
        "queries": ["코성형"],
        "signals": ["코성형", "코재수술", "성형외과", "의원", "병원", "클리닉"],
        "exclusions": ["안과", "피부과", "치과", "네일"],
    },
    "가슴성형": {
        "queries": ["가슴성형"],
        "signals": ["가슴성형", "가슴확대", "성형외과", "의원", "병원", "클리닉"],
        "exclusions": ["피부과", "안과", "치과", "네일"],
    },
    "리프팅": {
        "queries": ["리프팅"],
        "signals": ["리프팅", "울쎄라", "써마지", "인모드", "슈링크", "피부과", "의원", "병원", "클리닉"],
        "exclusions": ["헤어", "네일", "트리트먼트"],
    },
    "안면거상": {
        "queries": ["안면거상"],
        "signals": ["안면거상", "거상", "리프팅", "성형외과", "의원", "병원", "클리닉"],
        "exclusions": ["안과", "피부과", "치과", "네일"],
    },
    "남성제모": {
        "queries": ["남성제모"],
        "signals": ["남성제모", "제모", "피부과", "의원", "병원", "클리닉"],
        "exclusions": ["여성의류", "네일", "헤어"],
    },
    "여성제모": {
        "queries": ["여성제모"],
        "signals": ["여성제모", "제모", "피부과", "의원", "병원", "클리닉"],
        "exclusions": ["남성의류", "네일", "헤어"],
    },
    "피부과": {
        "queries": ["피부과"],
        "signals": ["피부과", "리쥬란", "색소", "탄력", "여드름", "제모", "레이저", "의원", "병원", "클리닉"],
        "exclusions": ["안과", "치과", "성형외과", "네일"],
    },
    "안과": {
        "queries": ["안과"],
        "signals": ["안과", "라식", "라섹", "스마일라식", "렌즈삽입", "백내장", "병원", "의원", "클리닉"],
        "exclusions": ["성형외과", "치과", "피부과", "네일"],
    },
}


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
    config = CATEGORY_CONFIG[category]
    blob = f"{page_name} {text_blob}".lower()
    score = 0
    query_hits = sum(1 for term in config["queries"] if term.lower() in blob)
    signal_hits = sum(1 for term in config["signals"] if term.lower() in blob)
    exclusion_hits = sum(1 for term in config["exclusions"] if term.lower() in blob)
    score += query_hits * 5
    score += signal_hits * 2
    score -= exclusion_hits * 4
    if any(token in blob for token in ["병원", "의원", "클리닉"]):
        score += 2
    return score


def published_date_from_timestamp(timestamp: int) -> str:
    return datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d")


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
    cards = snapshot.get("cards") or []
    videos = snapshot.get("videos") or []
    images = snapshot.get("images") or []

    if display_format in {"CAROUSEL", "MULTI_IMAGES"} or len(cards) > 1:
        return MEDIA_TYPE_CAROUSEL
    if display_format == "VIDEO" or videos or snapshot.get("video_preview_image_url"):
        return MEDIA_TYPE_VIDEO
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


def collect_category(session: requests.Session, category: str, limit: int) -> Tuple[List[Dict], List[str]]:
    config = CATEGORY_CONFIG[category]
    seen_ids = set()
    seen_signatures = set()
    candidates: List[Dict] = []
    failures: List[str] = []

    for query in config["queries"]:
        try:
            payload = fetch_results(session, query)
        except Exception as exc:
            failures.append(f"{category} 수집 실패({query}): {exc}")
            continue

        for edge in payload.get("edges", []):
            for result in edge.get("node", {}).get("collated_results", []):
                ad_id = str(result.get("ad_archive_id") or result.get("ad_id") or "")
                if not ad_id or ad_id in seen_ids:
                    continue
                seen_ids.add(ad_id)

                snapshot = result.get("snapshot") or {}
                page_name = snapshot.get("page_name") or "알 수 없음"
                text_blob = snapshot_text(snapshot)
                score = score_candidate(category, page_name, f"{snapshot.get('title') or ''} {text_blob}")
                if score < 6:
                    continue

                signature = " ".join([page_name, text_blob[:120]]).strip().lower()
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)

                candidates.append(
                    {
                        "ad_id": ad_id,
                        "category": category,
                        "query": query,
                        "page_name": page_name,
                        "brand_name": page_name,
                        "title": snapshot.get("title") or "",
                        "body_text": text_blob,
                        "image_url": image_url(snapshot),
                        "library_url": library_url(ad_id),
                        "days_live": days_live(result),
                        "days_active": compute_days_active(extract_published_date(result)) or days_live(result),
                        "start_ts": start_timestamp(result),
                        "published_date": extract_published_date(result),
                        "start_date": extract_published_date(result),
                        "media_type": infer_media_type(snapshot),
                        "raw_snapshot": json.dumps(snapshot, ensure_ascii=False),
                    }
                )

    candidates.sort(key=lambda item: (-item["days_active"], item["start_ts"], item["ad_id"]))
    return candidates[:limit], failures


def upsert_ads(conn: sqlite3.Connection, ads: Iterable[Dict]) -> int:
    saved = 0
    for ad in ads:
        row_key = f"{ad['category']}::{ad['ad_id']}"
        existing = conn.execute(
            """
            SELECT analysis_status, analysis_text, analysis_error, analyzed_at, first_collected_at, asset_path, is_saved
            FROM ads
            WHERE row_key = ?
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
                ad["ad_id"],
                ad["brand_name"],
                ad["category"],
                ad["query"],
                ad["page_name"],
                ad["title"],
                ad["body_text"],
                ad["image_url"],
                asset_path,
                image_path,
                ad["library_url"],
                ad["days_live"],
                ad["days_active"],
                ad["start_ts"],
                ad["published_date"],
                ad["start_date"],
                ad["media_type"],
                ad["raw_snapshot"],
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
    valid_row_keys = {f"{category}::{ad['ad_id']}" for ad in ads}
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
    summary = {"saved": 0, "counts": {}, "failures": {}}
    with connect_db() as conn:
        for category in CATEGORY_CONFIG:
            ads, failures = collect_category(session, category, limit_per_category)
            prune_category_ads(conn, category, ads)
            summary["counts"][category] = len(ads)
            summary["failures"][category] = failures
            summary["saved"] += upsert_ads(conn, ads)
    return summary


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

    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument("--limit", type=int)

    subparsers.add_parser("summary")

    args = parser.parse_args()

    if args.command == "init":
        init_db()
        print(json.dumps({"db_path": str(DB_PATH), "status": "initialized"}, ensure_ascii=False, indent=2))
    elif args.command == "collect":
        print(json.dumps(collect_to_db(limit_per_category=args.limit_per_category), ensure_ascii=False, indent=2))
    elif args.command == "analyze":
        print(json.dumps(analyze_pending(limit=args.limit), ensure_ascii=False, indent=2))
    elif args.command == "summary":
        print(json.dumps(dump_summary(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
