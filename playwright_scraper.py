import asyncio, sqlite3, re, json
from datetime import datetime
from playwright.async_api import async_playwright

def decode_js_str(s):
    """메타 페이지 본문 안의 \\uXXXX 유니코드 이스케이프를 실제 한글로 디코딩"""
    try:
        return json.loads(f'"{s}"')
    except Exception:
        return s

CATEGORIES = {
    "남성제모": ["남성제모"],
    "여성제모": ["여성제모"],
    "임플란트": ["임플란트"],
    "라미네이트": ["라미네이트"],
    "리프팅": ["올쎄라"],
    "올쎄라": ["울쎄라"],
    "스킨부스터": ["스킨부스터"],
    "코성형": ["코성형"],
    "피부/쁘띠": ["보톡스 필러"],
    "눈성형": ["눈성형"],
}

async def scrape():
    conn = sqlite3.connect('meta_ads_dashboard.db')
    cur = conn.cursor()
    cur.execute('DROP TABLE IF EXISTS ads')
    cur.execute('''CREATE TABLE ads (
        row_key TEXT PRIMARY KEY,
        ad_id TEXT, brand_name TEXT, page_name TEXT,
        title TEXT, body_text TEXT, category TEXT,
        start_date TEXT, days_active INTEGER,
        media_type TEXT, image_url TEXT, video_url TEXT, library_url TEXT,
        ai_analysis TEXT, is_saved INTEGER DEFAULT 0)''')
    conn.commit()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(locale='ko-KR')
        page = await ctx.new_page()
        total = 0

        for category, queries in CATEGORIES.items():
            for query in queries:
                url = f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=KR&q={query}&search_type=keyword_unordered&media_type=all"
                print(f"수집중: {category} - {query}")
                try:
                    # 스크롤 시 메타가 추가로 쏘는 GraphQL 응답 본문도 같이 모아야
                    # 30개 제한을 넘어 60개까지 확보할 수 있다 (초기 페이지 HTML만으론 부족함).
                    response_bodies = []

                    async def capture_response(resp):
                        try:
                            if 'graphql' in resp.url.lower() and resp.request.method == 'POST':
                                response_bodies.append(await resp.text())
                        except Exception:
                            pass

                    def on_response(resp):
                        asyncio.create_task(capture_response(resp))

                    page.on('response', on_response)

                    await page.goto(url, timeout=30000)
                    await page.wait_for_timeout(5000)

                    # 메타 광고 라이브러리는 스크롤해야 추가 광고가 더 로드되는 무한스크롤 구조.
                    # 60개를 확보하기 위해 여러 번 스크롤하며 로드를 유도한다.
                    for _ in range(8):
                        await page.mouse.wheel(0, 4000)
                        await page.wait_for_timeout(1200)
                    await page.wait_for_timeout(1500)

                    page.remove_listener('response', on_response)

                    # 초기 페이지 HTML + 스크롤 중 잡은 모든 GraphQL 응답 본문을 합쳐서 파싱
                    html = (await page.content()) + '\n'.join(response_bodies)
                    id_matches = list(re.finditer(r'"ad_archive_id":"(\d+)"', html))

                    results = []
                    seen_ids = set()
                    for idx, m in enumerate(id_matches):
                        archive_id = m.group(1)
                        if archive_id in seen_ids:
                            continue
                        seen_ids.add(archive_id)

                        # 다음 ad_archive_id 등장 전까지를 이 광고의 블록으로 간주
                        block_end = id_matches[idx + 1].start() if idx + 1 < len(id_matches) else m.start() + 6000
                        block = html[m.start():block_end]

                        img_match = re.search(r'"resized_image_url":"([^"]+)"', block) \
                            or re.search(r'"original_image_url":"([^"]+)"', block)

                        media_type = 'image'
                        src = ''
                        video_src = ''

                        if img_match and len(img_match.group(1)) >= 100:
                            src = img_match.group(1).replace('\\/', '/')
                        else:
                            # 이미지가 없으면 동영상 광고인지 확인 (썸네일 + 재생 URL)
                            preview_match = re.search(r'"video_preview_image_url":"([^"]+)"', block)
                            video_match = re.search(r'"video_hd_url":"([^"]+)"', block) \
                                or re.search(r'"video_sd_url":"([^"]+)"', block)
                            if not preview_match or not video_match:
                                continue  # 이미지도 영상도 못 찾으면 스킵
                            src = preview_match.group(1).replace('\\/', '/')
                            video_src = video_match.group(1).replace('\\/', '/')
                            media_type = 'video'
                            if len(src) < 50:
                                continue

                        page_name_match = re.search(r'"page_name":"([^"]*)"', block)
                        page_name = decode_js_str(page_name_match.group(1)) if page_name_match else query

                        # 메타가 내려주는 실제 광고 시작일(유닉스 타임스탬프). 없으면 오늘 날짜로 대체.
                        start_ts_match = re.search(r'"start_date":(\d+)', block)
                        if start_ts_match:
                            real_start_date = datetime.fromtimestamp(int(start_ts_match.group(1))).strftime('%Y-%m-%d')
                        else:
                            real_start_date = datetime.now().strftime('%Y-%m-%d')

                        lib_url = f"https://www.facebook.com/ads/library/?id={archive_id}"
                        results.append({
                            'archive_id': archive_id,
                            'src': src,
                            'videoSrc': video_src,
                            'mediaType': media_type,
                            'libUrl': lib_url,
                            'pageName': page_name,
                            'startDate': real_start_date,
                        })

                    count = 0
                    for r in results[:60]:
                        src = r['src']
                        video_src = r['videoSrc']
                        media_type = r['mediaType']
                        lib_url = r['libUrl']
                        page_name = r['pageName']
                        start_date = r['startDate']
                        days_active = max((datetime.now().date() - datetime.strptime(start_date, '%Y-%m-%d').date()).days, 0)
                        row_key = f"{category}_{r['archive_id']}"
                        cur.execute('''INSERT OR REPLACE INTO ads
                            (row_key, ad_id, brand_name, page_name, title, body_text,
                             category, start_date, days_active, media_type, image_url, video_url,
                             library_url, ai_analysis, is_saved)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (row_key, r['archive_id'], page_name, page_name, "", "",
                             category, start_date, days_active,
                             media_type, src, video_src, lib_url, "", 0))
                        count += 1
                        total += 1

                    conn.commit()
                    print(f"  → {count}개 수집 (library_url 포함)")
                except Exception as e:
                    print(f"  → 오류: {e}")

                await asyncio.sleep(2)

        await browser.close()
        conn.close()
        print(f"\n총 {total}개 수집 완료!")

asyncio.run(scrape())
