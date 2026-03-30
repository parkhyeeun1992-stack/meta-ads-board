import argparse
import base64
import copy
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import browser_cookie3
import requests


WORKDIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_PATH = os.path.join(WORKDIR, "ad_history.json")
ANALYZED_ADS_PATH = os.path.join(WORKDIR, "analyzed_ads.json")
COOKIE_FILE = os.path.expanduser("~/Library/Application Support/Google/Chrome/Profile 6/Cookies")
BASE_URL = "https://www.facebook.com/ads/library/"
SECRETS_PATH = os.path.join(WORKDIR, ".streamlit", "secrets.toml")


def load_local_secrets() -> Dict[str, str]:
    if not os.path.exists(SECRETS_PATH):
        return {}

    secrets: Dict[str, str] = {}
    for raw_line in open(SECRETS_PATH, "r", encoding="utf-8"):
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        secrets[key.strip()] = value.strip().strip('"').strip("'")
    return secrets


LOCAL_SECRETS = load_local_secrets()


def read_secret(name: str, default: str = "") -> str:
    return (os.getenv(name) or LOCAL_SECRETS.get(name) or default).strip()


WEBHOOK_URL = read_secret("WEBHOOK_URL")
SLACK_BOT_TOKEN = read_secret("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = read_secret("SLACK_CHANNEL_ID")
GEMINI_API_KEY = read_secret("GEMINI_API_KEY")
GEMINI_MODEL = read_secret("GEMINI_MODEL", "gemini-2.5-flash") or "gemini-2.5-flash"
KST = timezone(timedelta(hours=9))
DEFAULT_THUMB = "https://dummyimage.com/1200x628/e5e7eb/111827.png&text=Meta"
MAX_FAILURE_LINES = 5
GEMINI_INTER_CALL_SLEEP = 3
GEMINI_RATE_LIMIT_SLEEP = 15
GEMINI_MAX_RETRIES = 3
RATE_LIMIT_ANALYSIS_MESSAGE = "💬 [소재분석]: ⚠️ [이미지 분석 불가] API 요청 한도 초과(429)로 인해 분석이 누락되었습니다."
_IMAGE_SESSION: Optional[requests.Session] = None

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": "https://www.facebook.com/ads/library/",
}

IMAGE_HEADERS = {
    **HEADERS,
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
}

CATEGORY_QUERIES = {
    "치과": ["치과"],
    "피부과": ["피부과"],
    "성형외과": ["성형외과"],
    "안과": ["안과"],
    "시술": ["시술"],
}

CATEGORY_SIGNALS = {
    "치과": ["치과", "임플란트", "교정", "라미네이트", "치아", "심미"],
    "피부과": ["피부과", "레이저", "여드름", "색소", "리쥬란", "탄력", "제모"],
    "성형외과": ["성형외과", "눈성형", "코성형", "가슴성형", "재수술", "안면거상", "리프팅"],
    "안과": ["안과", "라식", "라섹", "스마일라식", "렌즈삽입", "백내장"],
    "시술": ["시술", "보톡스", "필러", "인모드", "슈링크", "울쎄라", "써마지"],
}

MEDICAL_SIGNALS = [
    "병원",
    "의원",
    "클리닉",
    "치과",
    "피부과",
    "성형외과",
    "안과",
    "전문의",
    "원장",
    "수술",
    "시술",
]

NON_MEDICAL_SIGNALS = [
    "올리브영",
    "샴푸",
    "헤어",
    "건강기능식품",
    "영양제",
    "다이어트",
    "화장품",
    "에스테틱 제품",
]


def norm(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def today_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def load_history() -> Dict:
    if not os.path.exists(HISTORY_PATH):
        return {"ads": {}}
    with open(HISTORY_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


def save_history(history: Dict) -> None:
    with open(HISTORY_PATH, "w", encoding="utf-8") as file:
        json.dump(history, file, ensure_ascii=False, indent=2)


def load_analyzed_ads(history: Optional[Dict] = None) -> Dict:
    if os.path.exists(ANALYZED_ADS_PATH):
        with open(ANALYZED_ADS_PATH, "r", encoding="utf-8") as file:
            analyzed_ads = json.load(file)
    else:
        analyzed_ads = {"ads": {}}

    if history:
        for ad_id, record in history.get("ads", {}).items():
            analysis = record.get("analysis")
            if analysis and ad_id not in analyzed_ads["ads"]:
                analyzed_ads["ads"][ad_id] = {
                    "analysis": analysis[:3],
                    "page_name": record.get("page_name", ""),
                    "updated_at": record.get("last_seen") or today_kst(),
                }
    return analyzed_ads


def save_analyzed_ads(analyzed_ads: Dict) -> None:
    with open(ANALYZED_ADS_PATH, "w", encoding="utf-8") as file:
        json.dump(analyzed_ads, file, ensure_ascii=False, indent=2)


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        jar = browser_cookie3.chrome(cookie_file=COOKIE_FILE, domain_name=".facebook.com")
        session.cookies = jar
    except Exception:
        pass
    return session


def image_session() -> requests.Session:
    global _IMAGE_SESSION
    if _IMAGE_SESSION is None:
        _IMAGE_SESSION = build_session()
        _IMAGE_SESSION.headers.update(IMAGE_HEADERS)
    return _IMAGE_SESSION


def fetch_results(session: requests.Session, query: str) -> Dict:
    url = (
        BASE_URL
        + "?active_status=active&ad_type=all&country=KR&is_targeted_country=false"
        + "&media_type=all&search_type=keyword_unordered&q="
        + requests.utils.quote(query)
    )
    response = session.get(
        url,
        timeout=30,
        headers={
            **HEADERS,
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Upgrade-Insecure-Requests": "1",
        },
    )
    response.raise_for_status()

    text = response.text
    needle = '"search_results_connection":'
    start = text.find(needle)
    if start < 0:
        raise RuntimeError("Meta Ads Library 응답에서 search_results_connection을 찾지 못했습니다.")

    start += len(needle)
    payload, _ = json.JSONDecoder().raw_decode(text[start:])
    return payload


def snapshot_text(snapshot: Dict) -> str:
    return norm(
        " ".join(
            filter(
                None,
                [
                    snapshot.get("page_name"),
                    snapshot.get("title"),
                    (snapshot.get("body") or {}).get("text"),
                    snapshot.get("link_description"),
                    " ".join(snapshot.get("page_categories") or []),
                ],
            )
        )
    )


def image_url(snapshot: Dict) -> Optional[str]:
    videos = snapshot.get("videos") or []
    for video in videos:
        preview = video.get("video_preview_image_url")
        if preview:
            return preview

    preview = snapshot.get("video_preview_image_url")
    if preview:
        return preview

    cards = snapshot.get("cards") or []
    for card in cards:
        preview = (
            card.get("original_image_url")
            or card.get("resized_image_url")
            or card.get("video_preview_image_url")
            or ((card.get("video_data") or {}).get("video_preview_image_url"))
        )
        if preview:
            return preview

    images = snapshot.get("images") or []
    if images:
        return images[0].get("original_image_url") or images[0].get("resized_image_url")

    extra_images = snapshot.get("extra_images") or []
    if extra_images:
        return extra_images[0].get("original_image_url") or extra_images[0].get("resized_image_url")
    return None


def library_url(ad_id: str) -> str:
    return f"{BASE_URL}?active_status=active&ad_type=all&country=KR&id={ad_id}"


def days_live(item: Dict) -> int:
    total_active_time = item.get("total_active_time")
    if total_active_time is not None:
        return max(1, int(round(total_active_time / 86400)))

    start_date = item.get("start_date")
    if start_date:
        return max(1, int((time.time() - start_date) // 86400))

    return 1


def start_timestamp(item: Dict) -> int:
    total_active_time = item.get("total_active_time")
    if total_active_time is not None:
        return int(time.time() - total_active_time)
    return item.get("start_date") or int(time.time())


def badge_for(days: int, is_new: bool) -> str:
    if is_new:
        return "🆕 [NEW]"
    if days >= 100:
        return "👑 [LEGEND]"
    if days >= 30:
        return "🎖️ [RUNNER]"
    return ""


def score_candidate(category: str, snapshot: Dict, query: str) -> int:
    text = snapshot_text(snapshot).lower()
    page_name = (snapshot.get("page_name") or "").lower()
    score = 0

    if query.lower() in text:
        score += 4
    if any(term in text for term in CATEGORY_SIGNALS[category]):
        score += 4
    if any(term in text for term in MEDICAL_SIGNALS):
        score += 3
    if any(term in page_name for term in CATEGORY_SIGNALS[category]):
        score += 2
    if any(term in text for term in NON_MEDICAL_SIGNALS):
        score -= 10

    return score


def fallback_analysis(candidate: Dict) -> List[str]:
    snapshot = candidate["snapshot"]
    text = snapshot_text(snapshot)
    title = snapshot.get("title") or ""
    page_name = candidate["page_name"]
    display_format = snapshot.get("display_format") or ""

    if any(token in text.lower() for token in ["before", "after", "전후", "비교"]):
        line1 = "레이아웃 & 비주얼 훅: 전후 컷의 밝기 대비를 크게 벌려 결과 면에 눈이 먼저 꽂히고, 가장 달라진 부위를 다시 보게 만드는 정지력이 있습니다."
    elif display_format in {"MULTI_IMAGES", "CAROUSEL"} or len(snapshot.get("images") or []) >= 2:
        line1 = "레이아웃 & 비주얼 훅: 첫 장에서 고민 부위를 찌르고 다음 장에서 해결 장면을 넘기게 만드는 캐러셀 구성이라, 시선이 가장 센 컷에서 멈춘 뒤 자연스럽게 다음 장으로 이어집니다."
    else:
        line1 = "레이아웃 & 비주얼 훅: 메인 비주얼 옆 큰 헤드카피가 시술명과 오퍼 축을 한 번에 읽히게 해 첫 1초에 어디를 봐야 하는지가 명확합니다."

    if any(token in text for token in ["혜택", "특가", "이벤트", "추가", "무료", "정품", "후기", "인증"]):
        line2 = "신뢰 & 가성비 레이어링: 가격 숫자 근처에 후기·인증·추가혜택을 붙여 둬 '지금 문의하면 덜 손해 본다'는 감각을 만들고 가격 저항을 낮춥니다."
    elif any(token in text for token in ["전문의", "원장", "정밀", "사후관리", "책임", "관리"]):
        line2 = "신뢰 & 가성비 레이어링: 의료진·정밀검사·사후관리 문구를 가격보다 먼저 보이게 두어, 할인보다 안전 근거가 먼저 쌓이는 구조로 상담 진입 저항을 줄입니다."
    else:
        line2 = "신뢰 & 가성비 레이어링: 정보 덩어리를 두세 층으로 나눠 둬 한 번에 다 읽지 않아도 납득 포인트가 남고, 가격 저항이 급하게 튀지 않습니다."

    color_signal = f"{title} {text} {page_name}".lower()
    if any(token in color_signal for token in ["블루", "파랑", "청", "안과", "스마일라식", "비앤빛"]):
        line3 = "브랜딩 & 가독성: 블루 포인트를 타이틀과 CTA 축에만 묶어 써 의료 신뢰 바이브를 유지하고, 텍스트가 많아도 화면이 탁해지지 않습니다."
    elif any(token in color_signal for token in ["프리미엄", "리프팅", "성형", "동안", "탄력"]):
        line3 = "브랜딩 & 가독성: 베이지나 골드 계열 포인트를 강조 문구에만 얹는 톤이 프리미엄 병원 무드를 살리면서도 텍스트를 탁하게 만들지 않습니다."
    else:
        line3 = "브랜딩 & 가독성: 포인트 컬러를 가격이나 핵심 헤드라인 한 군데에만 몰아 읽는 순서를 고정하고, 병원 고유 바이브도 비교적 선명하게 남깁니다."

    return [line1, line2, line3]


def parse_gemini_lines(text: str) -> List[str]:
    cleaned = text.strip().replace("\r", "")
    cleaned = re.sub(r"^```(?:json|text)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    lines = []
    for raw_line in cleaned.split("\n"):
        line = norm(re.sub(r"^[0-9]+[.)-]?\s*", "", raw_line))
        if not line:
            continue
        line = re.sub(r"^[•\-]\s*", "", line)
        lines.append(line)
    return lines[:3]


def analysis_needs_refresh(lines: List[str]) -> bool:
    if not lines or len(lines) < 3:
        return True
    expected_prefixes = [
        "레이아웃 & 비주얼 훅:",
        "신뢰 & 가성비 레이어링:",
        "브랜딩 & 가독성:",
    ]
    return any(not lines[idx].startswith(prefix) for idx, prefix in enumerate(expected_prefixes))


def gemini_analysis(candidate: Dict) -> Tuple[Optional[List[str]], Optional[str]]:
    if not GEMINI_API_KEY:
        return None, "Gemini 미설정으로 신규 소재 분석 생략"

    thumb = candidate.get("thumb")
    if not thumb or "dummyimage.com" in thumb:
        return None, "썸네일 부재로 신규 소재 분석 생략"

    try:
        image_response = image_session().get(thumb, timeout=30, headers=IMAGE_HEADERS, allow_redirects=True)
        image_response.raise_for_status()
    except requests.RequestException as exc:
        return None, f"썸네일 다운로드 실패: {exc}"

    mime_type = image_response.headers.get("content-type", "image/jpeg").split(";")[0].strip()
    encoded = base64.b64encode(image_response.content).decode("utf-8")
    system_prompt = """
너는 병원 광고를 10년 동안 기획한 수석 콘텐츠 디자이너다. 첨부 이미지를 직접 보고 한국어 3줄만 작성해.

출력 형식은 아래 3줄을 정확히 지켜.
1. 레이아웃 & 비주얼 훅: 실제 이미지에서 가장 먼저 시선이 꽂히는 위치, 핵심 카피, 모델/시술 부위/구도, 화면 분할을 짚어.
2. 신뢰 & 가성비 레이어링: 가격 저항을 낮추는 숫자, 혜택, 인증, 후기, 원장/전문의, 전후 비교, CTA 배치 같은 시각 요소를 짚어.
3. 브랜딩 & 가독성: 실제 포인트 컬러, 배경 톤, 폰트 굵기, 병원 분위기, 텍스트 읽는 순서를 짚어.

뻔한 템플릿 문장은 금지하고 실제 보이는 요소만 말해. 줄 수는 정확히 3줄만. 이미지가 안 보이면 '로드 실패'라고만 답해.
""".strip()
    prompt = """
첨부된 광고 이미지만 보고 한국어 3줄로 답해.
각 줄은 반드시 아래 접두어로 시작해.
- 레이아웃 & 비주얼 훅:
- 신뢰 & 가성비 레이어링:
- 브랜딩 & 가독성:
""".strip()

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type, "data": encoded}},
                ]
            }
        ],
        "generationConfig": {"temperature": 0.2, "topP": 0.8},
    }

    for attempt in range(GEMINI_MAX_RETRIES):
        try:
            response = requests.post(url, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            parts = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [])
            )
            text = "\n".join(part.get("text", "") for part in parts if part.get("text"))
            lines = parse_gemini_lines(text)
            if any("로드 실패" in line for line in lines):
                return None, "Gemini가 이미지 로드 실패를 반환함"
            if len(lines) == 1 and "로드 실패" in lines[0]:
                return None, "Gemini가 이미지 로드 실패를 반환함"
            if len(lines) >= 3:
                return lines[:3], None
            return None, "Gemini 응답이 3줄 형식을 지키지 않음"
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code == 429:
                if attempt == GEMINI_MAX_RETRIES - 1:
                    return [RATE_LIMIT_ANALYSIS_MESSAGE], None
                time.sleep(GEMINI_RATE_LIMIT_SLEEP)
                continue
            if attempt == GEMINI_MAX_RETRIES - 1:
                return None, f"Gemini 호출 실패: {exc}"
            time.sleep(2 + attempt)
        except requests.RequestException as exc:
            if attempt == GEMINI_MAX_RETRIES - 1:
                return None, f"Gemini 호출 실패: {exc}"
            time.sleep(2 + attempt)

    return None, "Gemini 분석 실패"


def collect_category(session: requests.Session, category: str, queries: List[str]) -> Tuple[List[Dict], List[str]]:
    seen_ids = set()
    seen_signatures = set()
    candidates = []
    failures = []

    for query in queries:
        try:
            data = fetch_results(session, query)
        except Exception as exc:
            failures.append(f"수집 실패({query}): {exc}")
            continue

        for edge in data.get("edges", []):
            for item in edge.get("node", {}).get("collated_results", []):
                ad_id = item.get("ad_archive_id") or item.get("ad_id")
                if not ad_id or ad_id in seen_ids:
                    continue
                seen_ids.add(ad_id)

                snapshot = item.get("snapshot") or {}
                if score_candidate(category, snapshot, query) < 7:
                    continue

                signature = norm((snapshot.get("page_name") or "") + " " + snapshot_text(snapshot)[:140]).lower()
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)

                candidates.append(
                    {
                        "category": category,
                        "query": query,
                        "ad_id": str(ad_id),
                        "page_name": snapshot.get("page_name") or "알 수 없음",
                        "title": snapshot.get("title") or "",
                        "text": snapshot_text(snapshot),
                        "thumb": image_url(snapshot) or DEFAULT_THUMB,
                        "display_format": snapshot.get("display_format") or "",
                        "days_live": days_live(item),
                        "start_ts": start_timestamp(item),
                        "snapshot": snapshot,
                    }
                )

    candidates.sort(key=lambda item: (item["start_ts"], item["ad_id"]))
    return candidates[:10], failures


def update_history_and_annotate(history: Dict, analyzed_ads: Dict, category_results: Dict[str, List[Dict]], category_failures: Dict[str, List[str]]) -> None:
    today = today_kst()

    for category, items in category_results.items():
        for item in items:
            ad_id = item["ad_id"]
            record = history["ads"].get(ad_id)
            is_new = record is None
            analyzed_record = analyzed_ads["ads"].get(ad_id)
            analysis = analyzed_record.get("analysis")[:3] if analyzed_record and analyzed_record.get("analysis") else None
            gemini_error = None

            if is_new and (not analysis or analysis_needs_refresh(analysis)):
                analysis, gemini_error = gemini_analysis(item)
                if GEMINI_API_KEY:
                    time.sleep(GEMINI_INTER_CALL_SLEEP)
                if analysis:
                    analyzed_ads["ads"][ad_id] = {
                        "analysis": analysis[:3],
                        "page_name": item["page_name"],
                        "updated_at": today,
                    }
                elif gemini_error:
                    category_failures[category].append(gemini_error)

            if is_new:
                if not analysis:
                    analysis = fallback_analysis(item)

                record = {
                    "category": category,
                    "page_name": item["page_name"],
                    "first_seen": today,
                    "last_seen": today,
                    "days_live": item["days_live"],
                    "badge": badge_for(item["days_live"], True),
                    "analysis": analysis[:3],
                }
                history["ads"][ad_id] = record
            else:
                record.update(
                    {
                        "category": category,
                        "page_name": item["page_name"],
                        "last_seen": today,
                        "days_live": item["days_live"],
                        "badge": badge_for(item["days_live"], False),
                    }
                )
                if analysis:
                    record["analysis"] = analysis[:3]
                elif not record.get("analysis"):
                    record["analysis"] = fallback_analysis(item)

            item["is_new"] = record.get("first_seen") == today
            if item["is_new"]:
                record["badge"] = "🆕 [NEW]"
            item["badge"] = record.get("badge", "")
            item["analysis"] = (record.get("analysis") or fallback_analysis(item))[:3]


def rank_icon(rank: int) -> str:
    return {
        1: "🥇",
        2: "🥈",
        3: "🥉",
        4: "4️⃣",
        5: "5️⃣",
        6: "6️⃣",
        7: "7️⃣",
        8: "8️⃣",
        9: "9️⃣",
        10: "🔟",
    }[rank]


def item_headline(rank: int, item: Dict) -> str:
    badge = f"{item['badge']} " if item.get("badge") else ""
    return f"{rank_icon(rank)} {rank}위 {badge}{item['page_name']} | 📅 게재 {item['days_live']}일"


def formatted_analysis(item: Dict) -> str:
    analysis = item["analysis"][:3]
    if not analysis:
        return "분석 데이터가 없습니다."
    return "\n".join(line.strip() for line in analysis if line and line.strip())


def make_item_section(rank: int, item: Dict) -> Dict:
    lines = [
        item_headline(rank, item),
        formatted_analysis(item),
        f"🔗 <{library_url(item['ad_id'])}|원본 보기>",
    ]
    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": "\n".join(lines)[:2900]},
        "accessory": {
            "type": "image",
            "image_url": item["thumb"],
            "alt_text": item["page_name"][:100] or "meta-ad",
        },
    }


def make_main_blocks(category: str, items: List[Dict], failures: List[str]) -> List[Dict]:
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*#{category} Meta 생존소재*"}},
        {"type": "divider"},
    ]

    if items:
        for rank, item in enumerate(items[:3], start=1):
            blocks.append(make_item_section(rank, item))
            if rank < min(3, len(items)):
                blocks.append({"type": "divider"})
    else:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "수집 결과 없음"}})

    footer_lines = []
    if failures:
        footer_lines.append("*실패 메모*")
        footer_lines.extend(f"• {message}" for message in failures[:MAX_FAILURE_LINES])

    if footer_lines:
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(footer_lines)[:2900]}})
    return blocks


def make_thread_blocks(items: List[Dict]) -> List[Dict]:
    blocks = []
    for rank, item in enumerate(items[3:10], start=4):
        lines = [
            item_headline(rank, item),
            formatted_analysis(item),
            f"🔗 <{library_url(item['ad_id'])}|원본 보기>",
        ]
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(lines)[:2900]},
                "accessory": {
                    "type": "image",
                    "image_url": item["thumb"],
                    "alt_text": item["page_name"][:100] or "meta-ad",
                },
            }
        )
        if rank < min(10, len(items)):
            blocks.append({"type": "divider"})
    return blocks


def post_webhook(payload: Dict) -> Dict:
    response = requests.post(WEBHOOK_URL, json=payload, timeout=30)
    response.raise_for_status()
    return {"ok": response.text.strip() == "ok", "raw": response.text.strip()}


def post_chat_message(blocks: List[Dict], text: str, thread_ts: Optional[str] = None) -> Dict:
    if not SLACK_BOT_TOKEN or not SLACK_CHANNEL_ID:
        raise RuntimeError("Slack bot token/channel 미설정")

    payload = {"channel": SLACK_CHANNEL_ID, "text": text, "blocks": blocks}
    if thread_ts:
        payload["thread_ts"] = thread_ts

    response = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
            "Content-Type": "application/json; charset=utf-8",
        },
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack API error: {data}")
    return data


def send_category_messages(category_results: Dict[str, List[Dict]], category_failures: Dict[str, List[str]], dry_run: bool = False) -> Dict:
    if dry_run:
        return {
            category: {
                "main_blocks": len(make_main_blocks(category, items, category_failures[category])),
                "thread_blocks": len(make_thread_blocks(items)) if len(items) > 3 else 0,
            }
            for category, items in category_results.items()
        }

    sent = {}
    for category, items in category_results.items():
        thread_ready = bool(SLACK_BOT_TOKEN and SLACK_CHANNEL_ID)
        if len(items) > 3 and not thread_ready:
            category_failures[category].append("Webhook만으로는 thread_ts를 확보할 수 없어 4~10위를 스레드로 전송하지 못함")
        if items:
            category_failures[category].append("Slack Block Kit 제약으로 썸네일 자체 클릭 링크는 불가해 원본 Meta 링크를 텍스트로 함께 제공함")

        main_blocks = make_main_blocks(category, items, category_failures[category])
        main_payload = {"text": f"#{category} Meta 생존소재", "blocks": main_blocks}
        try:
            main_response = post_chat_message(main_blocks, f"#{category} Meta 생존소재") if thread_ready else post_webhook(main_payload)
        except Exception as exc:
            category_failures[category].append(f"Slack 메인 메시지 전송 실패: {exc}")
            sent[category] = {"main_error": str(exc)}
            continue
        sent[category] = {"main": main_response}

        if len(items) <= 3:
            continue

        thread_blocks = make_thread_blocks(items)
        if thread_ready:
            thread_ts = main_response.get("ts")
            try:
                sent[category]["thread"] = post_chat_message(thread_blocks, f"#{category} 4위~10위", thread_ts=thread_ts)
            except Exception as exc:
                category_failures[category].append(f"Slack 스레드 전송 실패: {exc}")
                sent[category]["thread_error"] = str(exc)
        else:
            try:
                sent[category]["thread"] = post_webhook({"text": f"#{category} 4위~10위", "blocks": thread_blocks})
            except Exception as exc:
                category_failures[category].append(f"Slack 스레드 전송 실패: {exc}")
                sent[category]["thread_error"] = str(exc)

    return sent


def main(dry_run: bool = False) -> None:
    session = build_session()
    persisted_history = load_history()
    persisted_analyzed_ads = load_analyzed_ads(persisted_history)
    history = copy.deepcopy(persisted_history) if dry_run else persisted_history
    analyzed_ads = copy.deepcopy(persisted_analyzed_ads) if dry_run else persisted_analyzed_ads
    category_results: Dict[str, List[Dict]] = {}
    category_failures: Dict[str, List[str]] = {category: [] for category in CATEGORY_QUERIES}

    for category, queries in CATEGORY_QUERIES.items():
        items, failures = collect_category(session, category, queries)
        category_results[category] = items
        category_failures[category].extend(failures)

    update_history_and_annotate(history, analyzed_ads, category_results, category_failures)
    if not dry_run:
        save_history(history)
        save_analyzed_ads(analyzed_ads)
    sent = send_category_messages(category_results, category_failures, dry_run=dry_run)
    collected = sum(len(items) for items in category_results.values())
    new_count = sum(1 for items in category_results.values() for item in items if item.get("is_new"))
    failure_count = sum(len(messages) for messages in category_failures.values())

    print(
        json.dumps(
            {
                "dry_run": dry_run,
                "date": today_kst(),
                "counts": {category: len(items) for category, items in category_results.items()},
                "summary": {
                    "collected": collected,
                    "new": new_count,
                    "reused": collected - new_count,
                    "failures": failure_count,
                },
                "failures": category_failures,
                "sent": sent,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
