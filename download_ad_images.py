import sqlite3, requests, time, re
from pathlib import Path

WORKDIR = Path('.')
IMG_DIR = WORKDIR / 'netlify-deploy' / 'ad-images'
IMG_DIR.mkdir(parents=True, exist_ok=True)

conn = sqlite3.connect('meta_ads_dashboard.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute('SELECT row_key, image_url FROM ads WHERE image_url IS NOT NULL AND image_url != ""')
rows = cur.fetchall()
conn.close()

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
    'Referer': 'https://www.facebook.com/ads/library/',
})

def safe_name(key: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_-]', '_', key)

ok, fail, skip = 0, 0, 0
mapping = {}

for r in rows:
    key = safe_name(r['row_key'])
    out = IMG_DIR / f'{key}.jpg'
    mapping[r['row_key']] = f'ad-images/{key}.jpg'
    if out.exists() and out.stat().st_size > 500:
        skip += 1
        continue
    try:
        resp = session.get(r['image_url'], timeout=15)
        if resp.status_code == 200 and len(resp.content) > 500:
            out.write_bytes(resp.content)
            ok += 1
        else:
            fail += 1
            del mapping[r['row_key']]
    except Exception:
        fail += 1
        del mapping[r['row_key']]
    time.sleep(0.05)

print(f'다운로드 완료: 신규 {ok} / 기존유지 {skip} / 실패 {fail} (총 {len(rows)})')

import json
with open('image_local_map.json', 'w', encoding='utf-8') as f:
    json.dump(mapping, f, ensure_ascii=False)
print(f'로컬 매핑 저장: {len(mapping)}개 -> image_local_map.json')
