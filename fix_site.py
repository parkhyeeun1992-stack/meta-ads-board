import json, sqlite3
from datetime import date, datetime

TODAY = date.today().strftime('%Y.%m.%d')

def compute_days_active(start_date_str, fallback):
    try:
        d = datetime.strptime((start_date_str or '')[:10], '%Y-%m-%d').date()
        return max((date.today() - d).days, 0)
    except Exception:
        return fallback

try:
    with open('image_local_map.json', 'r', encoding='utf-8') as f:
        LOCAL_MAP = json.load(f)
except FileNotFoundError:
    LOCAL_MAP = {}

conn = sqlite3.connect('meta_ads_dashboard.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute('SELECT * FROM ads WHERE image_url IS NOT NULL AND image_url != ""')
rows = cur.fetchall()
conn.close()

ads = []
for r in rows:
    img = r['image_url'] or ''
    if any(x in img for x in ['p_40x40','p_50x50','p_60x60','s60x60','s40x40','_s.jpg','profile_pic']):
        continue
    if len(img) < 100:
        continue
    # 메타 CDN 원본 링크는 시간이 지나면 만료되어 엑박이 뜨므로,
    # download_ad_images.py로 로컬에 받아둔 이미지가 있으면 그걸 우선 사용한다.
    local_img = LOCAL_MAP.get(r['row_key'])
    ads.append({
        'id': r['row_key'],
        'category': (r['category'] or '').strip(),
        'brand_name': r['brand_name'] or '',
        'page_name': r['page_name'] or '',
        'imageUrl': local_img or img,
        'videoUrl': r['video_url'] or '',
        'library_url': r['library_url'] or '',
        'start_date': str(r['start_date'] or '')[:10],
        'days_active': compute_days_active(r['start_date'], int(r['days_active'] or 30)),
        'media_type': r['media_type'] or 'image',
    })

ads.sort(key=lambda a: a['days_active'], reverse=True)

print(f'광고 {len(ads)}개')

cats = list(dict.fromkeys(a['category'] for a in ads if a['category']))
by_cat = {}
for a in ads:
    c = a['category']
    if c not in by_cat: by_cat[c] = []
    by_cat[c].append(a)

tabs = ''.join(f'<button class="tab-btn" onclick="showCat(this,\'{c}\')" id="tab-{c}">{c} ({len(by_cat.get(c,[]))})</button>' for c in cats)
ads_json = json.dumps(ads, ensure_ascii=False)
first_cat = cats[0]

with open('netlify-deploy/index.html', 'w', encoding='utf-8') as f:
    f.write(f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>고효율 메타 광고 생존 보드</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#f8fafc;color:#1e293b}}
.layout{{display:flex;min-height:100vh}}
.sidebar{{width:200px;min-width:200px;background:white;border-right:1px solid #e2e8f0;padding:20px;position:sticky;top:0;height:100vh}}
.sidebar a{{display:block;padding:8px 12px;border-radius:8px;font-size:14px;color:#374151;text-decoration:none;margin-bottom:4px;cursor:pointer}}
.sidebar a.active{{background:#eff6ff;color:#3b82f6}}
.main{{flex:1;padding:24px}}
h1{{font-size:26px;font-weight:700;text-align:center;margin-bottom:12px}}
.notice{{background:white;border:1px solid #e2e8f0;border-radius:8px;padding:10px 16px;font-size:13px;color:#64748b;margin-bottom:20px;text-align:center}}
.notice a{{color:#3b82f6}}
.tabs-wrap{{overflow-x:auto;margin-bottom:20px}}
.tabs{{display:flex;gap:8px;width:max-content}}
.tab-btn{{padding:7px 14px;border-radius:999px;border:1px solid #e2e8f0;cursor:pointer;font-size:13px;background:white;color:#374151;white-space:nowrap}}
.tab-btn.active{{background:#3b82f6;color:white;border-color:#3b82f6}}
.media-filter{{display:flex;gap:8px;margin-bottom:16px}}
.media-btn{{padding:6px 14px;border-radius:8px;border:1px solid #e2e8f0;cursor:pointer;font-size:13px;background:white;color:#374151}}
.media-btn.active{{background:#1e293b;color:white;border-color:#1e293b}}
.play-icon{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:44px;height:44px;border-radius:50%;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center}}
.play-icon::after{{content:'';border-style:solid;border-width:8px 0 8px 14px;border-color:transparent transparent transparent white;margin-left:3px}}
.grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:16px}}
.card{{background:white;border-radius:12px;overflow:hidden;border:1px solid #e2e8f0;transition:.2s}}
.card:hover{{box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.card-img{{position:relative;height:240px;background:#f1f5f9;overflow:hidden;display:flex;align-items:center;justify-content:center}}
.card-img img{{width:100%;height:100%;object-fit:contain;display:block}}
.badge{{position:absolute;top:8px;left:8px;color:white;font-size:11px;font-weight:600;padding:3px 8px;border-radius:999px}}
.card-body{{padding:12px}}
.card-brand{{display:flex;align-items:center;gap:6px;margin-bottom:6px}}
.brand-icon{{width:24px;height:24px;border-radius:6px;background:#3b82f6;color:white;font-size:10px;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0}}
.brand-name{{font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.card-meta{{font-size:11px;color:#94a3b8;margin-bottom:10px}}
.card-btns{{display:flex;gap:6px}}
.btn{{flex:1;padding:6px;border-radius:6px;font-size:12px;border:none;cursor:pointer}}
.btn-outline{{background:#f1f5f9;color:#374151}}
.btn-outline:hover{{background:#e2e8f0}}
.btn-ai{{background:#eff6ff;color:#3b82f6}}
.btn-ai:hover{{background:#dbeafe}}
.modal-overlay{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:1000;align-items:center;justify-content:center}}
.modal-overlay.open{{display:flex}}
.modal{{background:white;border-radius:16px;width:94%;max-width:1100px;max-height:94vh;overflow-y:auto;position:relative}}
.modal-close{{position:absolute;top:16px;right:16px;background:#f1f5f9;border:none;border-radius:50%;width:32px;height:32px;font-size:18px;cursor:pointer;z-index:2}}
.modal-save-icon{{position:absolute;top:16px;right:60px;background:#f1f5f9;border:none;border-radius:50%;width:32px;height:32px;cursor:pointer;display:flex;align-items:center;justify-content:center;z-index:2}}
.modal-img{{width:100%;max-height:640px;object-fit:contain;background:#f8fafc}}
.modal-body{{padding:24px}}
.modal-title{{font-size:18px;font-weight:700;margin-bottom:8px}}
.modal-meta{{font-size:13px;color:#64748b;margin-bottom:16px}}
.modal-btns{{display:flex;gap:8px}}
.modal-btn{{flex:1;padding:10px;border-radius:8px;font-size:14px;border:none;cursor:pointer;font-weight:500;text-align:center;text-decoration:none;display:block}}
.modal-btn-outline{{background:#f1f5f9;color:#374151}}
.modal-btn-ai{{background:#3b82f6;color:white}}
.modal-btn-saved{{background:#3b82f6;color:white;border:1px solid #3b82f6}}
.toast{{position:fixed;bottom:28px;left:50%;transform:translateX(-50%) translateY(20px);background:#1e293b;color:white;padding:11px 20px;border-radius:999px;font-size:13px;font-weight:500;box-shadow:0 6px 20px rgba(0,0,0,.2);z-index:2000;opacity:0;pointer-events:none;transition:opacity .25s,transform .25s}}
.toast.show{{opacity:1;transform:translateX(-50%) translateY(0)}}
.modal-video{{width:100%;max-height:640px;background:#000;display:none}}
.ai-modal-box{{max-width:640px}}
.ai-src-row{{display:flex;gap:12px;align-items:center;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px;margin-bottom:16px}}
.ai-src-thumb{{width:56px;height:56px;object-fit:cover;border-radius:8px;background:#f1f5f9;flex-shrink:0}}
.ai-key-row{{display:none}}
.ai-key-row input{{flex:1;padding:8px 10px;border:1px solid #e2e8f0;border-radius:8px;font-size:13px}}
.ai-key-save{{padding:8px 14px;border-radius:8px;border:none;background:#1e293b;color:white;font-size:13px;cursor:pointer;white-space:nowrap}}
.ai-section{{margin-bottom:22px}}
.ai-section-title{{font-size:14px;font-weight:700;margin-bottom:10px;color:#1e293b}}
.ai-label{{display:block;font-size:12px;color:#64748b;margin:10px 0 4px}}
.ai-text-input{{width:100%;padding:9px 10px;border:1px solid #e2e8f0;border-radius:8px;font-size:13px}}
.ai-textarea{{width:100%;min-height:70px;padding:9px 10px;border:1px solid #e2e8f0;border-radius:8px;font-size:13px;font-family:inherit;resize:vertical}}
.ai-action-btn{{width:100%;margin-top:12px;padding:11px;border-radius:8px;border:1px solid #e2e8f0;background:#f8fafc;color:#374151;font-size:13px;font-weight:600;cursor:pointer}}
.ai-action-btn:disabled{{opacity:.6;cursor:default}}
.ai-action-btn-primary{{background:#3b82f6;color:white;border-color:#3b82f6}}
.ai-result-box{{margin-top:14px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:14px;font-size:13px;line-height:1.6;white-space:pre-wrap;color:#374151}}
.ai-plan-field{{margin-bottom:10px}}
.ai-plan-field b{{display:block;font-size:12px;color:#3b82f6;margin-bottom:3px}}
</style>
</head>
<body>
<div class="layout">
<div class="sidebar">
  <div style="font-size:13px;font-weight:600;color:#64748b;margin-bottom:12px">메뉴</div>
  <a class="active" id="nav-main-gallery" onclick="showMainGallery()">메인 갤러리</a>
  <a id="nav-my-board" onclick="showMyBoard()">내 보드</a>
</div>
<div class="main">
  <h1>고효율 메타 광고 생존 보드</h1>
  <div class="notice">📅 마지막 업데이트: {TODAY} · 이 보드는 매주 월요일 오전 11시 자동으로 업데이트됩니다. 최신 소재는 <a href="https://www.facebook.com/ads/library" target="_blank">메타 광고 라이브러리</a>에서 직접 확인해주세요. <button id="manual-update-btn" onclick="triggerManualUpdate()" style="margin-left:4px;padding:5px 12px;border-radius:999px;border:none;background:#eff6ff;color:#3b82f6;font-size:12px;font-weight:600;cursor:pointer">🔄 지금 업데이트</button>
  </div>
  <div class="tabs-wrap"><div class="tabs">{tabs}</div></div>
  <div class="media-filter">
    <button class="media-btn active" id="mf-all" onclick="setMediaFilter('all')">전체</button>
    <button class="media-btn" id="mf-image" onclick="setMediaFilter('image')">🖼 이미지만</button>
    <button class="media-btn" id="mf-video" onclick="setMediaFilter('video')">▶ 동영상만</button>
  </div>
  <div class="grid" id="grid"></div>
</div>
</div>
<div class="toast" id="toast"></div>
<div class="modal-overlay" id="modal" onclick="if(event.target===this)closeModal()">
  <div class="modal">
    <button class="modal-close" onclick="closeModal()">✕</button>
    <img class="modal-img" id="modal-img" src="">
    <video class="modal-video" id="modal-video" controls></video>
    <div class="modal-body">
      <div class="modal-title" id="modal-title"></div>
      <div class="modal-meta" id="modal-meta"></div>
      <div class="modal-btns">
        <a class="modal-btn modal-btn-outline" id="modal-link" href="#" target="_blank">🔗 메타 원본 링크 보기</a>
        <button class="modal-btn modal-btn-outline" id="modal-save-btn" onclick="toggleSaveCurrent()">🔖 내 보드 저장</button>
        <button class="modal-btn modal-btn-ai" id="modal-ai-btn" onclick="openAiPlanModalFromDetail()">✨ AI소재 기획 (beta)</button>
      </div>
    </div>
  </div>
</div>
<div class="modal-overlay" id="ai-modal" onclick="if(event.target===this)closeAiModal()">
  <div class="modal ai-modal-box">
    <button class="modal-close" onclick="closeAiModal()">✕</button>
    <div class="modal-body">
      <div class="modal-title">✨ AI소재 기획 (beta)</div>
      <div class="ai-src-row">
        <img id="ai-src-img" class="ai-src-thumb" src="">
        <div>
          <div id="ai-src-brand" style="font-weight:600;font-size:14px"></div>
          <div id="ai-src-meta" style="font-size:12px;color:#94a3b8"></div>
        </div>
      </div>

      <div class="ai-key-row" style="display:none">
        <input id="ai-key-input" type="password">
        <button class="ai-key-save" onclick="saveGeminiKey()">저장</button>
        <span id="ai-key-status"></span>
      </div>

      <div class="ai-section">
        <div class="ai-section-title">1. 기존 소재 디자인 분석</div>
        <button class="ai-action-btn" id="ai-analyze-btn" onclick="runDesignAnalysis()">🔍 이 소재가 왜 효율이 좋았는지 분석하기</button>
        <div id="ai-analysis-box" class="ai-result-box" style="display:none"></div>
      </div>

      <div class="ai-section">
        <div class="ai-section-title">2. 새 소재 기획하기</div>
        <label class="ai-label">시술명</label>
        <input id="ai-procedure-input" class="ai-text-input" placeholder="예: 라미네이트, 임플란트, 눈성형...">
        <label class="ai-label">원하는 내용/컨셉</label>
        <textarea id="ai-content-input" class="ai-textarea" placeholder="예: 20대 여성 타겟, 자연스러운 라인 강조, 병원 로고 없이 심플하게..."></textarea>
        <button class="ai-action-btn ai-action-btn-primary" id="ai-generate-btn" onclick="runNewPlan()">✨ 새 소재 기획안 생성</button>
        <div id="ai-plan-box" class="ai-result-box" style="display:none"></div>
      </div>
    </div>
  </div>
</div>
<script>
const ADS = {ads_json};
let catAds = [];
let currentCat = '{first_cat}';
let mediaFilter = 'all';
let viewMode = 'gallery'; // 'gallery' | 'saved'
let savedIds = new Set(JSON.parse(localStorage.getItem('saved_ads') || '[]'));

function persistSavedIds() {{
  localStorage.setItem('saved_ads', JSON.stringify(Array.from(savedIds)));
}}

function showMainGallery() {{
  viewMode = 'gallery';
  document.getElementById('nav-main-gallery').classList.add('active');
  document.getElementById('nav-my-board').classList.remove('active');
  document.querySelector('.tabs-wrap').style.display = '';
  document.querySelector('.media-filter').style.display = '';
  renderGrid();
}}

function showMyBoard() {{
  viewMode = 'saved';
  document.getElementById('nav-main-gallery').classList.remove('active');
  document.getElementById('nav-my-board').classList.add('active');
  document.querySelector('.tabs-wrap').style.display = 'none';
  document.querySelector('.media-filter').style.display = 'none';
  renderGrid();
}}

function setMediaFilter(mode) {{
  mediaFilter = mode;
  document.querySelectorAll('.media-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('mf-' + mode).classList.add('active');
  renderGrid();
}}

function showCat(btn, cat) {{
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  currentCat = cat;
  renderGrid();
}}

function renderGrid() {{
  let list;
  if (viewMode === 'saved') {{
    list = ADS.filter(a => savedIds.has(a.id));
  }} else {{
    list = ADS.filter(a => a.category === currentCat);
    if (mediaFilter !== 'all') list = list.filter(a => a.media_type === mediaFilter);
  }}
  catAds = list;
  if (viewMode === 'saved' && catAds.length === 0) {{
    document.getElementById('grid').innerHTML = '<div style="grid-column:1/-1;text-align:center;color:#94a3b8;padding:60px 0;font-size:14px">아직 저장한 소재가 없어요. 소재 상세보기에서 "🔖 내 보드 저장"을 눌러보세요.</div>';
    return;
  }}
  document.getElementById('grid').innerHTML = catAds.map((a,i) => {{
    const img = a.imageUrl || '';
    const isVideo = a.media_type === 'video';
    const days = a.days_active || 30;
    const bg = days >= 40 ? 'rgba(34,197,94,.9)' : 'rgba(249,115,22,.9)';
    const brand = (a.brand_name || a.page_name || '??').substring(0,2).toUpperCase();
    const lib = a.library_url || '';
    return '<div class="card">'
      + '<div class="card-img">'
      + '<img src="' + img + '" onerror="this.closest(\\'.card\\').remove()">'
      + (isVideo ? '<div class="play-icon"></div>' : '')
      + '<span class="badge" style="background:' + bg + '">⬆ ' + days + '일 생존</span>'
      + '</div>'
      + '<div class="card-body">'
      + '<div class="card-brand"><div class="brand-icon">' + brand + '</div>'
      + '<div class="brand-name">' + (a.brand_name || a.page_name || '') + '</div></div>'
      + '<div class="card-meta">유형: ' + (isVideo ? '동영상(Video)' : '단일이미지(Image)') + ' · (' + a.start_date + ')</div>'
      + '<div class="card-btns">'
      + '<button class="btn btn-outline" onclick="event.stopPropagation();openModal(' + i + ')">자세히 보기</button>'
      + '<button class="btn btn-ai" onclick="event.stopPropagation();openAiPlanModal(' + i + ')">✨ AI소재 기획 (beta)</button>'
      + '</div></div></div>';
  }}).join('');
}}
let currentModalIdx = -1;
function openModal(idx) {{
  currentModalIdx = idx;
  const a = catAds[idx];
  if (!a) return;
  const imgEl = document.getElementById('modal-img');
  const vidEl = document.getElementById('modal-video');
  if (a.media_type === 'video' && a.videoUrl) {{
    imgEl.style.display = 'none';
    vidEl.style.display = 'block';
    vidEl.src = a.videoUrl;
    vidEl.poster = a.imageUrl || '';
  }} else {{
    vidEl.pause();
    vidEl.removeAttribute('src');
    vidEl.style.display = 'none';
    imgEl.style.display = 'block';
    imgEl.src = a.imageUrl || '';
  }}
  document.getElementById('modal-title').textContent = a.brand_name || a.page_name || '';
  document.getElementById('modal-meta').textContent = '유형: ' + (a.media_type === 'video' ? '동영상' : '이미지') + ' · 게재 시작: ' + a.start_date + ' · ' + a.days_active + '일 생존';
  document.getElementById('modal-link').href = a.library_url || '#';
  updateSaveButton(a.id);
  document.getElementById('modal').classList.add('open');
}}
function updateSaveButton(id) {{
  const btn = document.getElementById('modal-save-btn');
  const saved = savedIds.has(id);
  btn.textContent = saved ? '✅ 내 보드에 저장됨' : '🔖 내 보드 저장';
  btn.classList.toggle('modal-btn-saved', saved);
}}
function toggleSaveCurrent() {{
  const a = catAds[currentModalIdx];
  if (!a) return;
  if (savedIds.has(a.id)) {{
    savedIds.delete(a.id);
    showToast('내 보드에서 삭제되었습니다');
  }} else {{
    savedIds.add(a.id);
    showToast('내 보드에 저장되었습니다');
  }}
  persistSavedIds();
  updateSaveButton(a.id);
  if (viewMode === 'saved') renderGrid();
}}
let toastTimer = null;
function showToast(msg) {{
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2000);
}}
function closeModal() {{
  document.getElementById('modal-video').pause();
  document.getElementById('modal').classList.remove('open');
}}

/* ===== AI소재 기획 (beta) ===== */
const GEMINI_MODEL = 'gemini-2.5-flash';
const AI_PROXY_URL = '/.netlify/functions/gemini-proxy';
let aiCurrentAd = null;
let aiAnalysisText = '';

async function callGeminiProxy(requestBody) {{
  const res = await fetch(AI_PROXY_URL, {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ model: GEMINI_MODEL, requestBody }})
  }});
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || ('요청 실패 (' + res.status + ')'));
  return data;
}}

function openAiPlanModal(idx) {{
  aiCurrentAd = catAds[idx];
  if (!aiCurrentAd) return;
  openAiModalCommon();
}}

function openAiPlanModalFromDetail() {{
  aiCurrentAd = catAds[currentModalIdx];
  if (!aiCurrentAd) return;
  closeModal();
  openAiModalCommon();
}}

function openAiModalCommon() {{
  const a = aiCurrentAd;
  document.getElementById('ai-src-img').src = a.imageUrl || '';
  document.getElementById('ai-src-brand').textContent = a.brand_name || a.page_name || '';
  document.getElementById('ai-src-meta').textContent = (a.days_active || 0) + '일 생존 · ' + a.start_date;
  document.getElementById('ai-analysis-box').style.display = 'none';
  document.getElementById('ai-analysis-box').innerHTML = '';
  document.getElementById('ai-plan-box').style.display = 'none';
  document.getElementById('ai-plan-box').innerHTML = '';
  document.getElementById('ai-procedure-input').value = '';
  document.getElementById('ai-content-input').value = '';
  aiAnalysisText = '';
  document.getElementById('ai-modal').classList.add('open');
}}

function closeAiModal() {{
  document.getElementById('ai-modal').classList.remove('open');
}}

async function imageUrlToBase64(url) {{
  const res = await fetch(url);
  const blob = await res.blob();
  const mime = blob.type || 'image/jpeg';
  const base64 = await new Promise((resolve, reject) => {{
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(',')[1]);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  }});
  return {{ base64, mime }};
}}

async function runDesignAnalysis() {{
  const btn = document.getElementById('ai-analyze-btn');
  const box = document.getElementById('ai-analysis-box');
  btn.disabled = true;
  btn.textContent = '분석 중...';
  box.style.display = 'block';
  box.textContent = '이미지를 불러와 분석하고 있습니다...';
  try {{
    const {{ base64, mime }} = await imageUrlToBase64(aiCurrentAd.imageUrl);
    const prompt = '이 이미지는 병원/시술 광고 소재야. 이 소재가 ' + (aiCurrentAd.days_active||0) + '일간 계속 노출될 만큼 효율이 좋았다고 가정하고, 광고 기획자 관점에서 디자인적으로 분석해줘.\\n1) 후킹 카피와 문구 특징\\n2) 톤앤매너(색감, 분위기)\\n3) 레이아웃/구도 특징\\n4) 핵심 소구 포인트\\n5) 왜 효율이 좋았을지 가설\\n한국어로 간결하게 불릿으로 정리해줘.';
    const data = await callGeminiProxy({{
      contents: [{{ parts: [ {{ inline_data: {{ mime_type: mime, data: base64 }} }}, {{ text: prompt }} ] }}],
      generationConfig: {{ temperature: 0.5 }}
    }});
    aiAnalysisText = data?.candidates?.[0]?.content?.parts?.[0]?.text || '분석 결과를 받지 못했습니다.';
    box.textContent = aiAnalysisText;
  }} catch (err) {{
    box.textContent = '분석 실패: ' + (err.message || '알 수 없는 오류') + '\\n\\n잠시 후 다시 시도해주세요.';
  }} finally {{
    btn.disabled = false;
    btn.textContent = '🔍 이 소재가 왜 효율이 좋았는지 분석하기';
  }}
}}

async function runNewPlan() {{
  const procedure = document.getElementById('ai-procedure-input').value.trim();
  const content = document.getElementById('ai-content-input').value.trim();
  const box = document.getElementById('ai-plan-box');
  if (!procedure) {{ alert('시술명을 입력해주세요.'); return; }}
  const btn = document.getElementById('ai-generate-btn');
  btn.disabled = true;
  btn.textContent = '기획 중...';
  box.style.display = 'block';
  box.textContent = '새 소재를 기획하고 있습니다...';
  try {{
    if (!aiAnalysisText) {{
      box.textContent = '먼저 위 1번 "디자인 분석하기"를 실행해주세요. 자동으로 분석을 진행할게요...';
      await runDesignAnalysis();
      box.style.display = 'block';
      box.textContent = '분석 완료. 새 소재를 기획하고 있습니다...';
    }}
    const prompt = '너는 병원/시술 광고 기획 전문가다.\\n\\n[기존 효율 좋은 소재 디자인 분석]\\n' + aiAnalysisText + '\\n\\n[새로 기획할 조건]\\n시술명: ' + procedure + '\\n원하는 내용/컨셉: ' + (content || '(특별한 지정 없음, 기존 소재의 성공 요인을 최대한 살려서)') + '\\n\\n위 분석의 성공 요인(디자인/카피 패턴)을 유지하면서, 새 시술/컨셉에 맞는 광고 소재 기획안 1개를 만들어라.\\nJSON만 반환:\\n{{\\"hookCopy\\":\\"메인 후킹 카피\\",\\"subCopy\\":\\"보조 카피\\",\\"designGuide\\":\\"레이아웃/색감/구도 가이드\\",\\"imagePrompt\\":\\"Midjourney/Firefly용 영문 이미지 생성 프롬프트\\"}}';
    const data = await callGeminiProxy({{
      contents: [{{ parts: [{{ text: prompt }}] }}],
      generationConfig: {{ temperature: 0.85, responseMimeType: 'application/json' }}
    }});
    const raw = data?.candidates?.[0]?.content?.parts?.[0]?.text;
    if (!raw) throw new Error('응답 없음');
    const plan = JSON.parse(raw);
    renderPlan(box, plan);
  }} catch (err) {{
    box.innerHTML = '';
    box.textContent = '기획 실패: ' + (err.message || '알 수 없는 오류') + '\\n\\n잠시 후 다시 시도해주세요.';
  }} finally {{
    btn.disabled = false;
    btn.textContent = '✨ 새 소재 기획안 생성';
  }}
}}

function renderPlan(box, plan) {{
  box.innerHTML =
    '<div class="ai-plan-field"><b>메인 후킹 카피</b>' + (plan.hookCopy||'') + '</div>' +
    '<div class="ai-plan-field"><b>보조 카피</b>' + (plan.subCopy||'') + '</div>' +
    '<div class="ai-plan-field"><b>디자인 가이드</b>' + (plan.designGuide||'') + '</div>' +
    '<div class="ai-plan-field"><b>이미지 생성 프롬프트</b>' + (plan.imagePrompt||'') + '</div>';
}}

document.getElementById('tab-{first_cat}').click();

async function triggerManualUpdate() {{
  const btn = document.getElementById('manual-update-btn');
  if (btn.disabled) return;
  if (!confirm('메타에서 최신 광고를 다시 수집해서 사이트를 업데이트할까요? 3~5분 정도 걸려요.')) return;
  btn.disabled = true;
  btn.textContent = '⏳ 업데이트 요청 중...';
  try {{
    const res = await fetch('/.netlify/functions/trigger-update', {{ method: 'POST' }});
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '요청 실패');
    btn.textContent = '✅ 업데이트 시작됨 (3~5분 후 새로고침)';
  }} catch (err) {{
    btn.textContent = '🔄 지금 업데이트';
    btn.disabled = false;
    alert('업데이트 요청 실패: ' + (err.message || '알 수 없는 오류'));
  }}
}}
</script>
</body>
</html>''')

print('완료!')
