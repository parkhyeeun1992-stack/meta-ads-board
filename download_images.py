import sqlite3, requests, time, browser_cookie3
from pathlib import Path

img_dir = Path('react-dashboard/public/ad-images')
img_dir.mkdir(parents=True, exist_ok=True)

conn = sqlite3.connect('meta_ads_dashboard.db')
conn.row_factory = sqlite3.Row
ads = conn.execute('SELECT row_key, image_url FROM ads WHERE image_url IS NOT NULL').fetchall()
conn.close()

session = requests.Session()
cookie_file = Path.home() / 'Library/Application Support/Google/Chrome/Profile 6/Cookies'
try:
    jar = browser_cookie3.chrome(cookie_file=str(cookie_file), domain_name='.facebook.com')
    session.cookies = jar
    print('쿠키 로드 성공!')
except Exception as e:
    print('쿠키 실패:', e)

session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/137.0.0.0 Safari/537.36',
    'Referer': 'https://www.facebook.com/ads/library/',
})

ok, fail = 0, 0
for ad in ads:
    key = ad['row_key'].replace('::', '_').replace('/', '_')
    out = img_dir / f'{key}.jpg'
    if out.exists():
        ok += 1
        continue
    try:
        r = session.get(ad['image_url'], timeout=15)
        if r.status_code == 200 and len(r.content) > 500:
            out.write_bytes(r.content)
            ok += 1
        else:
            fail += 1
    except:
        fail += 1
    time.sleep(0.2)
    if (ok + fail) % 100 == 0:
        print(f'진행중... 성공:{ok} 실패:{fail}')

print(f'이미지 다운로드 완료! 성공:{ok} 실패:{fail}')
