import argparse
import base64
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import browser_cookie3
import requests

WORKDIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_PATH = os.path.join(WORKDIR, "ad_history.json")
ANALYZED_ADS_PATH = os.path.join(WORKDIR, "analyzed_ads.json")
SECRETS_PATH = os.path.join(WORKDIR, ".streamlit", "secrets.toml")
COOKIE_FILE = os.path.expanduser("~/Library/Application Support/Google/Chrome/Profile 6/Cookies")
BASE_URL = "https://www.facebook.com/ads/library/"


def load_local_secrets():
    if not os.path.exists(SECRETS_PATH):
        return {}

    secrets = {}
    for raw_line in open(SECRETS_PATH, "r", encoding="utf-8"):
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        secrets[key.strip()] = value.strip().strip('"').strip("'")
    return secrets


LOCAL_SECRETS = load_local_secrets()


def read_secret(name, default=""):
    return (os.getenv(name) or LOCAL_SECRETS.get(name) or default).strip()


WEBHOOK_URL = read_secret("WEBHOOK_URL")
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
KST = timezone(timedelta(hours=9))
GEMINI_API_KEY = read_secret("GEMINI_API_KEY")
GEMINI_MODEL = read_secret("GEMINI_MODEL", "gemini-2.5-flash") or "gemini-2.5-flash"
DEFAULT_THUMB = "https://dummyimage.com/1200x628/e5e7eb/111827.png&text=Meta"
CATEGORY_QUERIES = {
    "치과": ["치과"],
    "피부과": ["피부과"],
    "성형외과": ["성형외과"],
    "안과": ["안과"],
    "시술": ["시술"],
}
CATEGORY_SIGNALS = {
    "치과": ["치과", "임플란트", "교정", "라미네이트", "치아", "심미"],
    "피부과": ["피부과", "레이저", "여드름", "색소", "리쥬란", "탄력"],
    "성형외과": ["성형외과", "눈성형", "코성형", "가슴", "리프팅", "재수술"],
    "안과": ["안과", "라식", "라섹", "스마일라식", "렌즈삽입", "백내장"],
    "시술": ["시술", "보톡스", "필러", "리프팅", "인모드", "슈링크", "울쎄라"],
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


TARGET_CATEGORIES = ["치과", "피부과", "성형외과", "안과", "시술"]
TOTAL_SELECTION_COUNT = 10
MAX_CANDIDATES_PER_CATEGORY = 12


def norm(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def load_history():
    if not os.path.exists(HISTORY_PATH):
        return {"ads": {}}
    with open(HISTORY_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


def save_history(history):
    with open(HISTORY_PATH, "w", encoding="utf-8") as file:
        json.dump(history, file, ensure_ascii=False, indent=2)


def load_analyzed_ads(history=None):
    if os.path.exists(ANALYZED_ADS_PATH):
        with open(ANALYZED_ADS_PATH, "r", encoding="utf-8") as file:
            analyzed_ads = json.load(file)
    else:
        analyzed_ads = {"ads": {}}

    if history:
        for ad_id, record in history.get("ads", {}).items():
            analysis = (record.get("analysis") or [])[:3]
            if analysis and ad_id not in analyzed_ads["ads"]:
                analyzed_ads["ads"][ad_id] = {
                    "analysis": analysis,
                    "page_name": record.get("page_name", ""),
                    "updated_at": record.get("last_seen"),
                }
    return analyzed_ads


def save_analyzed_ads(analyzed_ads):
    with open(ANALYZED_ADS_PATH, "w", encoding="utf-8") as file:
        json.dump(analyzed_ads, file, ensure_ascii=False, indent=2)


def build_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        jar = browser_cookie3.chrome(cookie_file=COOKIE_FILE, domain_name=".facebook.com")
        session.cookies = jar
    except Exception:
        pass
    return session


def fetch_results(session, query):
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


def snapshot_text(snapshot):
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


def image_url(snapshot):
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


def library_url(ad_id):
    return f"{BASE_URL}?active_status=active&ad_type=all&country=KR&id={ad_id}"


def score_candidate(category, snapshot, query):
    text = snapshot_text(snapshot).lower()
    page_name = (snapshot.get("page_name") or "").lower()
    score = 0

    if query.lower() in text:
        score += 3
    if any(term in text for term in CATEGORY_SIGNALS[category]):
        score += 4
    if any(term in text for term in MEDICAL_SIGNALS):
        score += 3
    if any(term in page_name for term in CATEGORY_SIGNALS[category]):
        score += 2

    if any(token in text for token in ["올리브영", "샴푸", "트리트먼트", "헤어", "건강기능식품", "다이어트"]):
        score -= 10

    return score


def days_live(item):
    total_active_time = item.get("total_active_time")
    if total_active_time is not None:
        return max(1, int(round(total_active_time / 86400)))

    start_date = item.get("start_date")
    if start_date:
        return max(1, int((time.time() - start_date) // 86400))

    return 1


def start_timestamp(item):
    total_active_time = item.get("total_active_time")
    if total_active_time is not None:
        return int(time.time() - total_active_time)
    return item.get("start_date") or int(time.time())


def parse_lines(text):
    lines = []
    for raw_line in (text or "").replace("\r", "").split("\n"):
        cleaned = norm(re.sub(r"^[0-9]+[.)-]?\s*", "", raw_line))
        if cleaned:
            lines.append(cleaned)
    return lines


def clean_analysis_lines(lines):
    cleaned_lines = []
    for line in lines or []:
        cleaned = norm(line)
        if cleaned:
            cleaned_lines.append(cleaned)
    return cleaned_lines[:3]


def collect_candidates(session, category, query):
    results = []
    seen_ids = set()
    seen_signatures = set()

    data = fetch_results(session, query)
    for edge in data.get("edges", []):
        for item in edge.get("node", {}).get("collated_results", []):
            ad_id = item.get("ad_archive_id") or item.get("ad_id")
            if not ad_id:
                continue
            ad_id = str(ad_id)
            if ad_id in seen_ids:
                continue
            seen_ids.add(ad_id)

            snapshot = item.get("snapshot") or {}
            if score_candidate(category, snapshot, query) < 7:
                continue

            signature = norm(f"{snapshot.get('page_name')} {snapshot_text(snapshot)[:140]}").lower()
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)

            results.append(
                {
                    "category": category,
                    "ad_id": ad_id,
                    "page_name": snapshot.get("page_name") or "알 수 없음",
                    "title": snapshot.get("title") or "",
                    "text": snapshot_text(snapshot),
                    "thumb": image_url(snapshot) or DEFAULT_THUMB,
                    "days_live": days_live(item),
                    "start_ts": start_timestamp(item),
                    "snapshot": snapshot,
                }
            )

    results.sort(key=lambda candidate: (candidate["start_ts"], candidate["ad_id"]))
    return results[:MAX_CANDIDATES_PER_CATEGORY]


def select_items_by_age(category_candidates):
    selected = []
    selected_ids = set()

    for category in TARGET_CATEGORIES:
        for candidate in category_candidates.get(category, []):
            if candidate["ad_id"] in selected_ids:
                continue
            selected.append(candidate)
            selected_ids.add(candidate["ad_id"])
            break

    remaining = []
    for category in TARGET_CATEGORIES:
        for candidate in category_candidates.get(category, []):
            if candidate["ad_id"] in selected_ids:
                continue
            remaining.append(candidate)

    remaining.sort(key=lambda candidate: (candidate["start_ts"], candidate["ad_id"]))
    for candidate in remaining:
        if len(selected) >= TOTAL_SELECTION_COUNT:
            break
        selected.append(candidate)
        selected_ids.add(candidate["ad_id"])

    selected.sort(key=lambda candidate: (TARGET_CATEGORIES.index(candidate["category"]), candidate["start_ts"], candidate["ad_id"]))
    return selected[:TOTAL_SELECTION_COUNT]


def fallback_new_analysis(item):
    snapshot = item["snapshot"]
    text = norm(" ".join(filter(None, [item.get("title"), item.get("text"), item.get("page_name")])))
    display_format = snapshot.get("display_format") or ""
    category = item["category"]

    if any(token in text for token in ["전후", "before", "after", "비교"]):
        line1 = f"시각적 훅: {category} 카테고리에서 전후 대비를 첫 화면에 박아 결과 기대치를 즉시 띄우고, 변화 부위로 시선을 곧장 끌어옵니다."
    elif display_format in {"MULTI_IMAGES", "CAROUSEL"} or len(snapshot.get("images") or []) >= 2:
        line1 = f"시각적 훅: 첫 컷에서 고민 부위를 찌르고 다음 컷에서 해결 이미지를 넘기게 만드는 캐러셀 문법이라 정지력과 탐색 욕구가 같이 붙습니다."
    else:
        line1 = f"시각적 훅: 큰 헤드카피와 단일 메인 비주얼의 역할 분담이 선명해서 {category} 핵심 메시지가 1초 안에 읽히고 스크롤 이탈을 줄입니다."

    if any(token in text for token in ["혜택", "특가", "할인", "이벤트", "무료", "추가", "VAT", "부가세"]):
        line2 = "혜택 레이어링: 메인 오퍼 옆에 할인·추가 혜택·무료 요소를 붙여 체감 진입장벽을 낮추고, 가격 저항보다 상담 클릭 이유를 먼저 만듭니다."
    elif any(token in text for token in ["전문의", "원장", "책임", "사후관리", "정밀", "검사"]):
        line2 = "혜택 레이어링: 가격을 세게 미는 대신 의료진·검사·사후관리 근거를 겹쳐 놓아 '싼 곳'이 아니라 '안심되는 곳'이라는 해석을 먼저 심습니다."
    else:
        line2 = "혜택 레이어링: 혜택 문구를 한 번에 쏟지 않고 핵심 오퍼와 보조 설득 포인트를 나눠 배치해 읽는 부담은 줄이고 납득 포인트는 늘렸습니다."

    if any(token in text for token in ["블루", "blue", "안과", "치과", "의원", "클리닉"]):
        line3 = "디테일 전략: 포인트 컬러와 정보 강조 축을 제한해 의료 카테고리 특유의 신뢰 톤을 지키고, CTA 전에 핵심 문장부터 안정적으로 읽히게 정리했습니다."
    elif any(token in text for token in ["프리미엄", "리프팅", "성형", "동안"]):
        line3 = "디테일 전략: 프리미엄 무드가 필요한 카테고리답게 과한 색상 충돌을 피하고 강조 요소를 좁게 써서 고가 시술도 덜 부담스럽게 보이게 만듭니다."
    else:
        line3 = "디테일 전략: 텍스트 덩어리를 짧게 끊고 강조 순서를 분명히 잡아 정보량이 있어도 답답하지 않으며, 병원 광고에서 중요한 신뢰 흐름을 보존합니다."

    return [line1, line2, line3]


def gemini_new_analysis(item):
    if not GEMINI_API_KEY:
        return None, "GEMINI_API_KEY 없음"

    thumb = item.get("thumb")
    if not thumb or "dummyimage.com" in thumb:
        return None, "광고 썸네일 없음"

    try:
        image_response = requests.get(thumb, timeout=30, headers=IMAGE_HEADERS)
        image_response.raise_for_status()
    except requests.RequestException as exc:
        return None, f"썸네일 다운로드 실패: {exc}"

    mime_type = image_response.headers.get("content-type", "image/jpeg").split(";")[0].strip()
    encoded = base64.b64encode(image_response.content).decode("utf-8")
    system_prompt = """
너는 10년 차 병원 광고 수석 디자이너다.
광고 이미지를 직접 보고, 한국 병원 메타 광고 성과 관점에서만 판단한다.
반드시 정확히 3줄로만 답한다.
각 줄은 다음 접두어로 시작한다.
1. 시각적 훅:
2. 혜택 레이어링:
3. 디테일 전략:
이미지를 명확히 확인할 수 없으면 추측하지 말고 None만 답한다.
""".strip()
    prompt = f"""
카테고리: {item['category']}
페이지명: {item['page_name']}

이미지와 함께 텍스트 단서를 참고해 정확히 3줄로 분석해.
첫 줄은 시선을 멈추게 하는 화면 구조,
둘째 줄은 오퍼와 신뢰 요소의 겹침 방식,
셋째 줄은 폰트/컬러/정보정리 같은 세부 완성도를 다뤄.
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

    for attempt in range(3):
        try:
            response = requests.post(url, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            text = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            )
            lines = parse_lines(text)
            if len(lines) == 3 and all(":" in line for line in lines):
                return lines, None
            return None, "Gemini 형식 불일치"
        except requests.RequestException as exc:
            if attempt == 2:
                return None, f"Gemini 호출 실패: {exc}"
            time.sleep(2 + attempt)

    return None, "Gemini 분석 실패"


def cleaned_existing_analysis(record, item):
    lines = []
    for line in record.get("analysis") or []:
        cleaned = norm(re.sub(r"^[A-Za-z가-힣\s&\[\]]+:\s*", "", line))
        if cleaned:
            lines.append(cleaned)
    if not lines:
        return fallback_new_analysis(item)
    return lines[:3]


def update_history(history, selected_items):
    today = datetime.now(KST).strftime("%Y-%m-%d")
    failures = []
    counts = {"new": 0, "existing": 0}
    analyzed_ads = load_analyzed_ads(history)

    for item in selected_items:
        record = history["ads"].get(item["ad_id"])
        analyzed_record = analyzed_ads["ads"].get(item["ad_id"])
        if record is None:
            analysis, error = gemini_new_analysis(item)
            if error:
                failures.append(f"{item['category']} {item['ad_id']} 신규분석: {error}")
            item["analysis"] = clean_analysis_lines(analysis or fallback_new_analysis(item))
            history["ads"][item["ad_id"]] = {
                "category": item["category"],
                "page_name": item["page_name"],
                "first_seen": today,
                "last_seen": today,
                "days_live": item["days_live"],
                "analysis": item["analysis"],
            }
            analyzed_ads["ads"][item["ad_id"]] = {
                "analysis": item["analysis"],
                "page_name": item["page_name"],
                "updated_at": today,
            }
            item["is_new"] = True
            counts["new"] += 1
            continue

        record.update(
            {
                "category": item["category"],
                "page_name": item["page_name"],
                "last_seen": today,
                "days_live": item["days_live"],
            }
        )
        item["analysis"] = clean_analysis_lines(
            (analyzed_record or {}).get("analysis")
            or record.get("analysis")
            or cleaned_existing_analysis(record, item)
        )
        if item["analysis"] and not analyzed_record:
            analyzed_ads["ads"][item["ad_id"]] = {
                "analysis": item["analysis"],
                "page_name": item["page_name"],
                "updated_at": today,
            }
        record["analysis"] = item["analysis"]
        item["is_new"] = False
        counts["existing"] += 1

    save_analyzed_ads(analyzed_ads)
    return failures, counts


def format_item_text(item):
    header = f"*{'[NEW] ' if item['is_new'] else ''}{item['page_name']}*"
    lines = [header, f"게재 일수 {item['days_live']}일"]
    if item["is_new"]:
        lines.append(f"<{library_url(item['ad_id'])}|Meta Ads Library 원본>")
    lines.extend(clean_analysis_lines(item["analysis"]))
    return "\n".join(lines)


def build_blocks(grouped_items):
    blocks = []
    first_category = True
    for category in TARGET_CATEGORIES:
        items = grouped_items.get(category) or []
        if not items:
            continue
        if not first_category:
            blocks.append({"type": "divider"})
        first_category = False
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*#{category}*"}})
        for item in items:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": format_item_text(item)[:2900]},
                    "accessory": {
                        "type": "image",
                        "image_url": item.get("thumb") or DEFAULT_THUMB,
                        "alt_text": item["page_name"][:100] or "meta-ad",
                    },
                }
            )
    return blocks


def send_to_slack(blocks, summary):
    payload = {
        "text": summary,
        "blocks": blocks,
    }
    response = requests.post(WEBHOOK_URL, json=payload, timeout=30)
    response.raise_for_status()
    return response.text.strip()


def main(dry_run=False):
    session = build_session()
    history = load_history()
    history.setdefault("ads", {})

    category_candidates = {}
    failures = []
    for category in TARGET_CATEGORIES:
        query = CATEGORY_QUERIES[category][0]
        try:
            category_candidates[category] = collect_candidates(session, category, query)
        except Exception as exc:
            category_candidates[category] = []
            failures.append(f"{category} 수집 실패: {exc}")

    selected_items = select_items_by_age(category_candidates)
    update_failures, counts = update_history(history, selected_items)
    failures.extend(update_failures)
    save_history(history)

    grouped_items = defaultdict(list)
    for item in selected_items:
        grouped_items[item["category"]].append(item)

    sent = None
    if not dry_run:
        blocks = build_blocks(grouped_items)
        try:
            sent = send_to_slack(
                blocks,
                f"병원 고효율 소재 분석 · 수집 {len(selected_items)}개 / 신규 {counts['new']}개 / 기존 {counts['existing']}개",
            )
        except Exception as exc:
            failures.append(f"Slack 전송 실패: {exc}")

    print(
        json.dumps(
            {
                "dry_run": dry_run,
                "selected_count": len(selected_items),
                "new_count": counts["new"],
                "existing_count": counts["existing"],
                "failure_count": len(failures),
                "failures": failures,
                "selected_ids": [item["ad_id"] for item in selected_items],
                "grouped_counts": {category: len(grouped_items.get(category, [])) for category in TARGET_CATEGORIES},
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
