import html
import json
import os
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd
import streamlit as st
from streamlit_option_menu import option_menu

from meta_dashboard_pipeline import (
    DB_PATH,
    build_gemini_payload,
    call_gemini,
    connect_db,
    download_image_to_asset,
    fetch_cached_analysis,
    file_extension_for_mime,
    image_request_session,
    init_db,
    save_analysis_cache,
)


WORKDIR = Path(__file__).resolve().parent

CATEGORY_ORDER = [
    "남성제모",
    "여성제모",
    "임플란트",
    "라미네이트",
    "리프팅",
    "안면거상",
    "피부/쁘띠",
    "눈성형",
    "코성형",
    "가슴성형",
    "시력교정",
]
DISPLAY_STEP = 10
COLLECT_STATUS_PATH = WORKDIR / "collect_job_status.json"
COLLECT_LOG_PATH = WORKDIR / "collect_job.log"

NAV_OPTIONS = ["메인 갤러리", "내 보드"]

MEDIA_TYPE_LABELS = {
    "단일이미지(Image)": "단일이미지",
    "영상(Video)": "영상",
    "캐러셀(Carousel)": "캐러셀",
}

RANK_BADGES = ["🥇", "🥈", "🥉"]


@st.cache_data(ttl=30)
def load_ads() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        data = pd.read_sql_query(
            """
            SELECT
                row_key,
                ad_id,
                category,
                brand_name,
                page_name,
                title,
                body_text,
                image_url,
                asset_path,
                library_url,
                days_live,
                days_active,
                start_date,
                published_date,
                media_type,
                is_saved,
                analysis_status,
                analysis_text,
                analysis_error,
                analyzed_at,
                last_collected_at
            FROM ads
            ORDER BY category, days_live DESC, published_date ASC, last_collected_at DESC
            """,
            conn,
        )

    if data.empty:
        return data

    data["published_date"] = pd.to_datetime(data["published_date"], errors="coerce")
    data["published_date_only"] = data["published_date"].dt.date
    data["start_date"] = pd.to_datetime(data["start_date"], errors="coerce")
    data["start_date_only"] = data["start_date"].dt.date
    data["media_type_display"] = data["media_type"].map(MEDIA_TYPE_LABELS).fillna("단일이미지")
    data["search_blob"] = (
        data[["page_name", "title", "body_text"]]
        .fillna("")
        .agg(" ".join, axis=1)
        .str.lower()
    )
    data["is_saved"] = data["is_saved"].fillna(0).astype(int)
    return data


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        @import url("https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css");

        html, body, [class*="css"], [data-testid="stAppViewContainer"] {
            font-family: "Pretendard", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
        }
        [data-testid="stHeader"] {
            display: none !important;
        }
        [data-testid="collapsedControl"] {
            display: none !important;
        }
        [data-testid="stSidebarCollapseButton"],
        button[title="Collapse sidebar"],
        button[title="Expand sidebar"],
        button[aria-label="Collapse sidebar"],
        button[aria-label="Expand sidebar"] {
            display: none !important;
            visibility: hidden !important;
            pointer-events: none !important;
        }
        section[data-testid="stSidebar"] {
            min-width: 320px !important;
            max-width: 320px !important;
            width: 320px !important;
            transform: translateX(0) !important;
            visibility: visible !important;
            position: relative !important;
            left: 0 !important;
            margin-left: 0 !important;
        }
        section[data-testid="stSidebar"][aria-expanded="false"] {
            min-width: 320px !important;
            max-width: 320px !important;
            width: 320px !important;
            transform: translateX(0) !important;
            left: 0 !important;
            margin-left: 0 !important;
            visibility: visible !important;
        }
        section[data-testid="stSidebar"][aria-expanded="false"] > div {
            width: 320px !important;
            margin-left: 0 !important;
        }
        .stApp {
            background: #ffffff;
        }
        .block-container {
            max-width: 1540px;
            padding-top: 0.25rem;
            padding-bottom: 2.8rem;
        }
        [data-testid="stSidebar"] {
            background: #FFFFFF;
            border-right: 1px solid rgba(15, 23, 42, 0.02);
        }
        [data-testid="stSidebar"] > div:first-child {
            padding-top: 0.75rem;
        }
        [data-testid="stSidebar"] form {
            background: transparent !important;
            border: none !important;
            border-radius: 0 !important;
            padding: 0 !important;
            box-shadow: none !important;
        }
        [data-testid="stSidebar"] .stTextInput input,
        [data-testid="stSidebar"] .stDateInput input,
        [data-testid="stSidebar"] [data-baseweb="select"] > div {
            border-radius: 14px;
            background: #ffffff;
            border: 1px solid #e5e8eb;
        }
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] .stMarkdown,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span {
            color: #191f28;
        }
        .stButton > button[kind="primary"],
        .stDownloadButton > button[kind="primary"] {
            background: #3182F6 !important;
            border-color: #3182F6 !important;
        }
        [data-testid="stSidebar"] .stButton > button[kind="primary"] {
            width: 100%;
            border-radius: 12px;
            min-height: 46px;
            font-weight: 700;
            box-shadow: none;
        }
        [data-testid="stSidebar"] [data-testid="stDivider"] {
            margin: 1rem 0 1.05rem 0;
        }
        [data-testid="stSidebar"] [data-testid="stDivider"] hr {
            border-color: #F2F4F6;
        }
        [data-testid="stSidebar"] .stForm {
            border: none !important;
        }
        [data-testid="stTabs"] [role="tablist"] {
            overflow-x: auto;
            overflow-y: hidden;
            flex-wrap: nowrap;
            white-space: nowrap;
            scrollbar-width: thin;
            gap: 0.55rem;
            margin-bottom: 1rem;
            padding-bottom: 0.2rem;
        }
        [data-testid="stTabs"] [role="tab"] {
            border-radius: 999px;
            padding: 0.52rem 1rem;
            border: 1px solid #dde7f3;
            background: #ffffff;
            color: #4b5563;
            flex: 0 0 auto;
        }
        [data-testid="stTabs"] [aria-selected="true"] {
            background: #eef5ff;
            border-color: rgba(28, 126, 255, 0.25);
            color: #1C7EFF;
        }
        [data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #e8ecf2;
            border-radius: 18px;
            padding: 0.75rem 1rem;
            box-shadow: 0 10px 22px rgba(15, 23, 42, 0.04);
        }
        [data-testid="stMetricLabel"] {
            color: #64748b;
        }
        [data-testid="stMetricValue"] {
            color: #0f172a;
        }
        .board-header {
            padding: 0.4rem 0 1.2rem 0;
            margin-bottom: 0.2rem;
            text-align: center;
        }
        .board-title {
            margin: 0;
            color: #0f172a;
            font-size: 2.1rem;
            font-weight: 800;
            letter-spacing: -0.03em;
        }
        .gallery-empty {
            background: #f8fafc;
            border: 1px dashed #cbd5e1;
            border-radius: 18px;
            padding: 1rem 1.1rem;
            color: #64748b;
        }
        .gallery-card {
            background: #ffffff;
            border: 1px solid #e8ecf2;
            border-radius: 18px;
            overflow: hidden;
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
            margin-bottom: 1rem;
        }
        .gallery-card-body {
            padding: 0.7rem 0.8rem 0.9rem 0.8rem;
        }
        .gallery-card-title {
            color: #0f172a;
            font-size: 0.88rem;
            font-weight: 700;
            line-height: 1.45;
            margin-bottom: 0.18rem;
        }
        .gallery-card-meta {
            color: #6B7684;
            font-size: 0.76rem;
            line-height: 1.45;
            margin-bottom: 0.18rem;
        }
        .gallery-card-days {
            color: #6B7684;
            font-size: 0.76rem;
            line-height: 1.45;
            margin-bottom: 0.7rem;
        }
        .tab-caption {
            color: #64748b;
            margin-bottom: 0.85rem;
        }
        .modal-section-title {
            color: #0f172a;
            font-size: 1.05rem;
            font-weight: 700;
            margin: 0 0 0.5rem 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def normalize_date_range(selected_range: Union[Tuple[date, date], date]) -> Tuple[date, date]:
    if isinstance(selected_range, tuple):
        if len(selected_range) == 2:
            return selected_range
        if len(selected_range) == 1:
            return selected_range[0], selected_range[0]
    return selected_range, selected_range


def read_collect_status() -> Dict[str, object]:
    if not COLLECT_STATUS_PATH.exists():
        return {}
    try:
        return json.loads(COLLECT_STATUS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def is_collect_running(status: Dict[str, object]) -> bool:
    pid = status.get("pid")
    if not pid or status.get("status") != "running":
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def refresh_collect_cache_if_needed(status: Dict[str, object]) -> None:
    finished_at = status.get("finished_at")
    if status.get("status") == "done" and finished_at and st.session_state.get("last_collect_finished_at") != finished_at:
        st.session_state.last_collect_finished_at = finished_at
        st.cache_data.clear()


def start_collect_job(limit_per_category: int = 100) -> None:
    COLLECT_LOG_PATH.touch(exist_ok=True)
    with COLLECT_LOG_PATH.open("a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [sys.executable, str(WORKDIR / "meta_dashboard_collect_job.py"), "--limit-per-category", str(limit_per_category)],
            cwd=str(WORKDIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    COLLECT_STATUS_PATH.write_text(
        json.dumps(
            {
                "status": "running",
                "pid": process.pid,
                "started_at": date.today().isoformat(),
                "finished_at": None,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def render_collect_controls() -> None:
    status = read_collect_status()
    running = is_collect_running(status)
    refresh_collect_cache_if_needed(status)

    st.sidebar.divider()
    st.sidebar.markdown("##### 데이터 수집")
    if running:
        st.sidebar.info("최신 데이터 수집이 서버에서 실행 중입니다.")
    elif status.get("status") == "done":
        st.sidebar.success("최근 수집 작업이 완료되었습니다.")
    elif status.get("status") == "failed":
        st.sidebar.error("최근 수집 작업이 실패했습니다.")
    else:
        st.sidebar.caption("서버에서 직접 Meta 광고 데이터를 다시 수집합니다.")

    if st.sidebar.button(
        "최신 데이터 수집 시작",
        type="primary",
        use_container_width=True,
        disabled=running,
    ):
        start_collect_job(limit_per_category=100)
        st.rerun()

    if status.get("summary"):
        summary = status["summary"]
        total = sum(summary.get("counts", {}).values())
        st.sidebar.caption(f"최근 수집 결과: {total}개")
    if COLLECT_LOG_PATH.exists():
        st.sidebar.caption(f"로그 파일: {COLLECT_LOG_PATH.name}")


def initialize_filter_state(default_start: date, default_end: date, default_types: List[str]) -> None:
    st.session_state.setdefault("nav_menu", NAV_OPTIONS[0])
    st.session_state.setdefault("applied_start_date", default_start)
    st.session_state.setdefault("applied_end_date", default_end)
    st.session_state.setdefault("applied_media_types", default_types)
    st.session_state.setdefault("selected_category", CATEGORY_ORDER[0])
    st.session_state.setdefault("last_selected_category", st.session_state.selected_category)
    st.session_state.setdefault("display_limit", DISPLAY_STEP)
    st.session_state.setdefault("last_nav_menu", st.session_state.nav_menu)
    if st.session_state.selected_category not in CATEGORY_ORDER:
        st.session_state.selected_category = CATEGORY_ORDER[0]
        st.session_state.last_selected_category = CATEGORY_ORDER[0]


def reset_display_limit() -> None:
    st.session_state.display_limit = DISPLAY_STEP


def render_sidebar(default_start: date, default_end: date, default_types: List[str]) -> None:
    selected_menu = option_menu(
        menu_title=None,
        options=NAV_OPTIONS,
        icons=["grid", "bookmark-heart"],
        default_index=NAV_OPTIONS.index(st.session_state.nav_menu),
        styles={
            "container": {
                "padding": "0",
                "background-color": "transparent",
                "border": "none",
            },
            "icon": {
                "color": "#4E5968",
                "font-size": "16px",
            },
            "nav-link": {
                "font-size": "15px",
                "font-weight": "400",
                "color": "#4E5968",
                "padding": "12px 14px",
                "margin": "2px 0",
                "border-radius": "8px",
                "background-color": "transparent",
                "--hover-color": "#F2F4F6",
            },
            "nav-link-selected": {
                "background-color": "#E8F3FF",
                "color": "#3182F6",
                "font-weight": "700",
            },
        },
    )
    if selected_menu != st.session_state.last_nav_menu:
        reset_display_limit()
        st.session_state.last_nav_menu = selected_menu
    st.session_state.nav_menu = selected_menu
    st.sidebar.divider()

    with st.sidebar.form("filter_form", clear_on_submit=False):
        st.markdown("##### 필터")
        selected_range = st.date_input(
            "날짜 범위",
            value=(st.session_state.applied_start_date, st.session_state.applied_end_date),
            min_value=default_start,
            max_value=default_end,
        )
        selected_types = st.multiselect(
            "광고 유형",
            options=default_types,
            default=st.session_state.applied_media_types,
        )
        submitted = st.form_submit_button("확인", type="primary", use_container_width=True)

    if submitted:
        normalized_start, normalized_end = normalize_date_range(selected_range)
        st.session_state.applied_start_date = normalized_start
        st.session_state.applied_end_date = normalized_end
        st.session_state.applied_media_types = selected_types or default_types
        reset_display_limit()


def filter_ads(
    data: pd.DataFrame,
    start_date: date,
    end_date: date,
    selected_types: List[str],
    saved_only: bool = False,
) -> pd.DataFrame:
    filtered = data.copy()
    filtered = filtered[filtered["start_date_only"].between(start_date, end_date, inclusive="both")]
    if selected_types:
        filtered = filtered[filtered["media_type_display"].isin(selected_types)]
    if saved_only:
        filtered = filtered[filtered["is_saved"] == 1]
    return filtered


def rank_label(rank: int) -> str:
    badge = RANK_BADGES[rank - 1] if rank <= len(RANK_BADGES) else "🏅"
    return f"{badge} {rank}위"


def render_header(nav_menu: str) -> None:
    title = "오늘의 AI 추천 광고" if nav_menu == "메인 갤러리" else "내 보드"
    st.markdown(
        f"""
        <div class="board-header">
            <div class="board-title">{title}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def image_source_for(record: pd.Series) -> str:
    image_url = record.get("image_url")
    if isinstance(image_url, str) and image_url:
        return image_url
    asset_path = record.get("asset_path")
    if isinstance(asset_path, str) and asset_path:
        return asset_path
    return ""


def live_days(record: pd.Series) -> int:
    days_active = record.get("days_active")
    if pd.notna(days_active):
        return max(1, int(days_active))
    published = record.get("published_date")
    if pd.notna(published):
        return max(1, (date.today() - published.date()).days + 1)
    days_live = record.get("days_live")
    if pd.notna(days_live):
        return max(1, int(days_live))
    return 1


def get_record_by_row_key(data: pd.DataFrame, row_key: str) -> Optional[pd.Series]:
    matched = data[data["row_key"] == row_key]
    if matched.empty:
        return None
    return matched.iloc[0]


def update_saved_state(row_key: str, is_saved: bool) -> None:
    with connect_db() as conn:
        conn.execute(
            """
            UPDATE ads
            SET is_saved = ?
            WHERE row_key = ?
            """,
            (1 if is_saved else 0, row_key),
        )
        conn.commit()
    st.cache_data.clear()


def update_analysis_rows(
    ad_id: str,
    analysis_status: str,
    analysis_text: Optional[str],
    analysis_error: Optional[str],
    asset_path: Optional[str],
) -> None:
    with connect_db() as conn:
        conn.execute(
            """
            UPDATE ads
            SET analysis_status = ?,
                analysis_text = ?,
                analysis_error = ?,
                asset_path = COALESCE(?, asset_path),
                analyzed_at = CURRENT_TIMESTAMP
            WHERE ad_id = ?
            """,
            (analysis_status, analysis_text, analysis_error, asset_path, ad_id),
        )
        conn.commit()
    st.cache_data.clear()


def get_image_payload(record: pd.Series) -> Tuple[Optional[bytes], Optional[str], Optional[str], Optional[str]]:
    asset_path = record.get("asset_path")
    if isinstance(asset_path, str) and asset_path and Path(asset_path).exists():
        content = Path(asset_path).read_bytes()
        suffix = Path(asset_path).suffix.lower()
        mime_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }.get(suffix, "image/jpeg")
        return content, asset_path, mime_type, None

    image_client = image_request_session()
    return download_image_to_asset(image_client, record["ad_id"], record["image_url"])


def analyze_image_on_demand(record: pd.Series) -> Tuple[Optional[str], Optional[str]]:
    with connect_db() as conn:
        cached = fetch_cached_analysis(conn, record["ad_id"])
        if cached and cached["analysis_status"] == "done" and cached["analysis_text"]:
            return cached["analysis_text"], None

    image_bytes, asset_path, mime_type, download_error = get_image_payload(record)
    if download_error or not image_bytes:
        update_analysis_rows(record["ad_id"], "failed", None, download_error, asset_path)
        with connect_db() as conn:
            save_analysis_cache(
                conn,
                record["ad_id"],
                record["image_url"],
                asset_path,
                mime_type,
                "failed",
                None,
                download_error,
            )
        return None, download_error

    mime_type = mime_type or "image/jpeg"
    payload = build_gemini_payload(image_bytes, mime_type)
    analysis_text, error = call_gemini(payload)

    if analysis_text and not error:
        update_analysis_rows(record["ad_id"], "done", analysis_text, None, asset_path)
        with connect_db() as conn:
            save_analysis_cache(
                conn,
                record["ad_id"],
                record["image_url"],
                asset_path,
                mime_type,
                "done",
                analysis_text,
                None,
            )
        return analysis_text, None

    update_analysis_rows(record["ad_id"], "failed", None, error, asset_path)
    with connect_db() as conn:
        save_analysis_cache(
            conn,
            record["ad_id"],
            record["image_url"],
            asset_path,
            mime_type,
            "failed",
            None,
            error,
        )
    return None, error


def close_dialog() -> None:
    if "view_ad" in st.query_params:
        del st.query_params["view_ad"]


@st.dialog("광고 상세 보기", width="large")
def show_ad_dialog(record: pd.Series) -> None:
    image_bytes, asset_path, mime_type, download_error = get_image_payload(record)
    published_date = (
        record["published_date"].strftime("%Y-%m-%d")
        if pd.notna(record["published_date"])
        else "-"
    )

    left_col, right_col = st.columns([1.1, 0.9], gap="large")
    with left_col:
        image_source = asset_path or image_source_for(record)
        if image_source:
            st.image(image_source, use_container_width=True)
        else:
            st.warning("이미지를 불러오지 못했습니다.")

    with right_col:
        st.markdown(f"### {record['page_name']}")
        st.write(f"게재일시: `{published_date}`")
        st.write(f"광고 유형: `{record['media_type_display']}`")
        st.write(f"게재일수: `{int(record['days_live'])}일`")
        st.link_button("광고 원본 보기", record["library_url"], use_container_width=True)
        st.markdown("<div class='modal-section-title'>AI 디자인 킥</div>", unsafe_allow_html=True)
        if record.get("analysis_text"):
            st.success(record["analysis_text"])
        elif record.get("analysis_error"):
            st.warning(record["analysis_error"])
        else:
            st.info("아직 분석하지 않았습니다. 아래 버튼으로 필요할 때만 분석하세요.")

    st.divider()
    btn_col1, btn_col2, btn_col3, btn_col4 = st.columns([1, 1, 1, 0.8], gap="small")

    with btn_col1:
        extension = file_extension_for_mime(mime_type or "image/jpeg")
        download_name = f"{record['ad_id']}{extension}"
        st.download_button(
            "이미지 저장",
            data=image_bytes if image_bytes else b"",
            file_name=download_name,
            mime=mime_type or "application/octet-stream",
            use_container_width=True,
            disabled=image_bytes is None or download_error is not None,
        )

    with btn_col2:
        if record["is_saved"]:
            st.button("보드 저장됨", disabled=True, use_container_width=True)
        else:
            if st.button("보드 저장", use_container_width=True):
                update_saved_state(record["row_key"], True)
                st.success("내 보드에 저장했습니다.")
                st.rerun()

    with btn_col3:
        if st.button("이미지 분석", use_container_width=True, type="primary"):
            with st.spinner("제미나이가 이미지를 읽고 효율 포인트를 분석하는 중입니다..."):
                analysis_text, error = analyze_image_on_demand(record)
            if analysis_text:
                st.success(analysis_text)
            else:
                st.error(error or "이미지 분석에 실패했습니다.")
            st.rerun()

    with btn_col4:
        if st.button("닫기", use_container_width=True):
            close_dialog()
            st.rerun()


def maybe_open_dialog(data: pd.DataFrame) -> None:
    row_key = st.query_params.get("view_ad")
    if not row_key:
        return
    record = get_record_by_row_key(data, row_key)
    if record is None:
        close_dialog()
        return
    show_ad_dialog(record)


def render_native_card(record: pd.Series, rank: int) -> None:
    started_date = (
        record["start_date"].strftime("%Y.%m.%d")
        if pd.notna(record["start_date"])
        else (
            record["published_date"].strftime("%Y.%m.%d")
            if pd.notna(record["published_date"])
            else "-"
        )
    )
    running_days = live_days(record)
    with st.container(border=False):
        st.markdown("<div class='gallery-card'>", unsafe_allow_html=True)
        image_source = image_source_for(record)
        if image_source:
            st.image(image_source, use_container_width=True)
        st.markdown("<div class='gallery-card-body'>", unsafe_allow_html=True)
        st.markdown(
            f"<div class='gallery-card-title'>{rank_label(rank)} {record['page_name']}</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div class='gallery-card-meta'>{record['media_type_display']}</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div class='gallery-card-days'>📅 게재 {running_days}일 ({started_date})</div>",
            unsafe_allow_html=True,
        )
        if st.button(
            "상세 보기 및 AI 분석",
            key=f"open_detail_{record['row_key']}",
            use_container_width=True,
        ):
            st.query_params["view_ad"] = record["row_key"]
            st.rerun()
        st.markdown("</div></div>", unsafe_allow_html=True)


def render_gallery(nav_menu: str, data: pd.DataFrame) -> None:
    category_counts = {
        category: int(len(data[data["category"].eq(category)]))
        for category in CATEGORY_ORDER
    }
    selected_category = st.segmented_control(
        "카테고리",
        options=CATEGORY_ORDER,
        default=st.session_state.selected_category,
        format_func=lambda category: f"{category} ({category_counts.get(category, 0)})",
        selection_mode="single",
        label_visibility="collapsed",
        key="selected_category",
    )

    if not selected_category:
        selected_category = CATEGORY_ORDER[0]

    if selected_category != st.session_state.last_selected_category:
        reset_display_limit()
        st.session_state.last_selected_category = selected_category

    sorted_df = (
        data[data["category"].eq(selected_category)]
        .sort_values(["days_active", "start_date", "last_collected_at"], ascending=[False, True, False])
        .reset_index(drop=True)
    )
    if sorted_df.empty:
        message = "내 보드에 저장된 광고가 없습니다." if nav_menu == "내 보드" else "필터 조건에 맞는 광고가 없습니다."
        st.markdown(f"<div class='gallery-empty'>{html.escape(message)}</div>", unsafe_allow_html=True)
        return

    display_count = min(int(st.session_state.display_limit), len(sorted_df))
    category_df = sorted_df.iloc[:display_count]

    st.markdown(
        f"<div class='tab-caption'>{selected_category} 카테고리 광고 {display_count} / {len(sorted_df)}개</div>",
        unsafe_allow_html=True,
    )
    cols = st.columns(5)
    for index, (_, row) in enumerate(category_df.iterrows()):
        with cols[index % 5]:
            render_native_card(row, index + 1)

    if len(sorted_df) > display_count:
        _, center_col, _ = st.columns([1, 1.6, 1])
        with center_col:
            if st.button(
                f"소재 더보기 ({display_count}/{len(sorted_df)})",
                key=f"load_more_{nav_menu}_{selected_category}",
                use_container_width=True,
            ):
                st.session_state.display_limit = int(st.session_state.display_limit) + DISPLAY_STEP
                st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="경쟁사 광고 갤러리",
        page_icon="📌",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    init_db()
    inject_styles()

    if not DB_PATH.exists():
        st.error("DB 파일이 아직 없습니다. 먼저 수집 파이프라인을 실행해 주세요.")
        return

    data = load_ads()
    if data.empty:
        st.info("아직 저장된 광고가 없습니다.")
        return

    valid_dates = data["start_date_only"].dropna()
    if valid_dates.empty:
        st.error("게시일시 데이터가 비어 있습니다. 수집 파이프라인을 다시 실행해 주세요.")
        return

    default_start = valid_dates.min()
    default_end = valid_dates.max()
    default_types = list(MEDIA_TYPE_LABELS.values())

    initialize_filter_state(default_start, default_end, default_types)
    render_sidebar(default_start, default_end, default_types)
    render_collect_controls()

    filtered = filter_ads(
        data,
        st.session_state.applied_start_date,
        st.session_state.applied_end_date,
        st.session_state.applied_media_types,
        saved_only=st.session_state.nav_menu == "내 보드",
    )

    render_header(st.session_state.nav_menu)
    render_gallery(st.session_state.nav_menu, filtered)
    maybe_open_dialog(load_ads())


if __name__ == "__main__":
    main()
