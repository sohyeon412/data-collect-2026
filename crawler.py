import asyncio
import csv
import json
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# ── 설정 ──────────────────────────────────────────────────────────────────────
QUERIES_CSV   = "queries_500.csv"
OUTPUT_CSV    = "results.csv"
PROGRESS_JSON = "progress.json"          # 재시작용 체크포인트

# 딜레이 범위 (초) ― 깃액션에서 여러 날 돌릴 때 봇 감지 회피
DELAY_BETWEEN_QUERIES = (18, 45)         # 쿼리 사이
DELAY_BETWEEN_SCROLL  = (1.2, 3.5)      # 스크롤 사이
DELAY_TYPING          = (60, 160)        # 타이핑 딜레이 (ms)

# 구글 검색 URL
GOOGLE_SEARCH = "https://www.google.com/search?q={query}&hl=ko&gl=KR"

# ── 유저에이전트 풀 ────────────────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

# ── 뷰포트 풀 ─────────────────────────────────────────────────────────────────
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 800},
]

# ── 진행상황 저장/불러오기 ─────────────────────────────────────────────────────
def load_progress() -> set:
    if Path(PROGRESS_JSON).exists():
        with open(PROGRESS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"[재시작] 이미 완료된 쿼리 {len(data['done'])}개 건너뜀")
        return set(data["done"])
    return set()

def save_progress(done_ids: set):
    with open(PROGRESS_JSON, "w", encoding="utf-8") as f:
        json.dump({"done": list(done_ids), "updated": datetime.now().isoformat()}, f, ensure_ascii=False)

# ── 쿼리 불러오기 ──────────────────────────────────────────────────────────────
def load_queries() -> list[dict]:
    with open(QUERIES_CSV, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

# ── CSV 결과 저장 ──────────────────────────────────────────────────────────────
FIELDNAMES = [
    "id", "query", "category",
    "has_ai_overview",
    "ai_overview_urls",          # | 구분 문자열
    "seo_top10_urls",            # | 구분 문자열
    "overlap_count",             # 겹치는 URL 수
    "overlap_ratio",             # 겹치는 비율 (ai_urls 기준)
    "crawled_at",
]

def init_csv():
    if not Path(OUTPUT_CSV).exists():
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()

def append_result(row: dict):
    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=FIELDNAMES).writerow(row)

# ── URL 정규화 ─────────────────────────────────────────────────────────────────
def normalize_url(url: str) -> str:
    url = re.sub(r"https?://", "", url)
    url = re.sub(r"www\.", "", url)
    url = url.rstrip("/").split("?")[0].split("#")[0]
    return url.lower()

def extract_domain(url: str) -> str:
    url = normalize_url(url)
    return url.split("/")[0]

# ── raw HTML 파싱 ──────────────────────────────────────────────────────────────
def parse_html(html: str) -> tuple[bool, list[str], list[str]]:
    """
    JS 렌더링된 DOM HTML에서 AI 개요 URL과 SEO 상위 10개 URL을 한 번에 추출.
    """
    soup = BeautifulSoup(html, "html.parser")

    # ── AI 개요 ──
    ai_urls = []
    ai_container = soup.find(attrs={"data-attrid": "SrpGenSumSummary"})
    if ai_container:
        for a in ai_container.find_all("a", href=True):
            href = a["href"]
            if href.startswith("http") and "google.com" not in href:
                ai_urls.append(href)

    seen = set()
    unique_ai = []
    for u in ai_urls:
        n = normalize_url(u)
        if n not in seen:
            seen.add(n)
            unique_ai.append(u)

    # ── SEO 상위 10개 ──
    seo_urls = []
    for a in soup.select('div.yuRUbf a[jsname="UWckNb"]'):
        href = a.get("href", "")
        if href.startswith("http") and "google.com" not in href and "youtube.com" not in href:
            seo_urls.append(href)

    seen = set()
    unique_seo = []
    for u in seo_urls:
        n = normalize_url(u)
        if n not in seen:
            seen.add(n)
            unique_seo.append(u)
        if len(unique_seo) >= 10:
            break

    return (len(unique_ai) > 0, unique_ai, unique_seo)

# ── 인간처럼 마우스 움직이기 ──────────────────────────────────────────────────
async def human_mouse_move(page):
    vp = page.viewport_size
    if not vp:
        return
    for _ in range(random.randint(2, 5)):
        x = random.randint(100, vp["width"] - 100)
        y = random.randint(100, vp["height"] - 100)
        await page.mouse.move(x, y)
        await asyncio.sleep(random.uniform(0.1, 0.4))

# ── 인간처럼 스크롤 ───────────────────────────────────────────────────────────
async def human_scroll(page):
    for _ in range(random.randint(2, 4)):
        delta = random.randint(300, 700)
        await page.mouse.wheel(0, delta)
        await asyncio.sleep(random.uniform(*DELAY_BETWEEN_SCROLL))

# ── 쿼리 1개 처리 ─────────────────────────────────────────────────────────────
async def process_query(page, query_row: dict) -> dict:
    qid      = query_row["id"]
    query    = query_row["query"]
    category = query_row["category"]

    search_url = GOOGLE_SEARCH.format(query=query)
    print(f"  [{qid}] 검색: {query}")

    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
    except Exception as e:
        print(f"  [{qid}] goto 실패: {e}")
        return _empty_row(qid, query, category)

    # JS 렌더링 대기
    await asyncio.sleep(random.uniform(2.0, 4.0))
    await human_mouse_move(page)
    await human_scroll(page)
    await asyncio.sleep(random.uniform(1.0, 2.0))

    dom_html = await page.content()
    has_ai, ai_urls, seo_urls = parse_html(dom_html)

    # 겹침 계산 (도메인 레벨)
    ai_domains  = {extract_domain(u) for u in ai_urls}
    seo_domains = {extract_domain(u) for u in seo_urls}
    overlap     = ai_domains & seo_domains
    overlap_cnt = len(overlap)
    overlap_rat = round(overlap_cnt / len(ai_domains), 4) if ai_domains else 0.0

    return {
        "id":               qid,
        "query":            query,
        "category":         category,
        "has_ai_overview":  has_ai,
        "ai_overview_urls": "|".join(ai_urls),
        "seo_top10_urls":   "|".join(seo_urls),
        "overlap_count":    overlap_cnt,
        "overlap_ratio":    overlap_rat,
        "crawled_at":       datetime.now().isoformat(),
    }

def _empty_row(qid, query, category) -> dict:
    return {
        "id": qid, "query": query, "category": category,
        "has_ai_overview": False, "ai_overview_urls": "",
        "seo_top10_urls": "", "overlap_count": 0,
        "overlap_ratio": 0.0, "crawled_at": datetime.now().isoformat(),
    }

# ── 메인 ──────────────────────────────────────────────────────────────────────
async def main():
    queries    = load_queries()
    done_ids   = load_progress()
    init_csv()

    # 아직 안 된 쿼리만 필터링
    todo = [q for q in queries if q["id"] not in done_ids]
    print(f"총 {len(queries)}개 중 {len(todo)}개 남음")

    async with async_playwright() as pw:
        # 매 실행마다 랜덤 UA / 뷰포트
        ua       = random.choice(USER_AGENTS)
        viewport = random.choice(VIEWPORTS)

        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                f"--window-size={viewport['width']},{viewport['height']}",
            ],
        )

        context = await browser.new_context(
            user_agent=ua,
            viewport=viewport,
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            extra_http_headers={
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )

        # 봇 감지 우회: navigator.webdriver 숨기기
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3] });
            Object.defineProperty(navigator, 'languages', { get: () => ['ko-KR','ko','en-US'] });
            window.chrome = { runtime: {} };
        """)

        page = await context.new_page()

        for i, query_row in enumerate(todo):
            result = await process_query(page, query_row)
            append_result(result)
            done_ids.add(query_row["id"])
            save_progress(done_ids)

            print(f"  → AI Overview: {result['has_ai_overview']} | "
                  f"AI URLs: {len(result['ai_overview_urls'].split('|')) if result['ai_overview_urls'] else 0} | "
                  f"SEO URLs: {len(result['seo_top10_urls'].split('|')) if result['seo_top10_urls'] else 0} | "
                  f"겹침: {result['overlap_count']}")

            # 마지막 쿼리가 아니면 랜덤 대기
            if i < len(todo) - 1:
                wait = random.uniform(*DELAY_BETWEEN_QUERIES)
                print(f"  ⏳ {wait:.1f}초 대기...")
                await asyncio.sleep(wait)

                # 10개마다 좀 더 쉬기 (인간처럼)
                if (i + 1) % 10 == 0:
                    extra = random.uniform(30, 90)
                    print(f"  😴 추가 휴식 {extra:.0f}초...")
                    await asyncio.sleep(extra)

        await browser.close()

    print(f"\n✅ 완료! results.csv 저장됨")

if __name__ == "__main__":
    asyncio.run(main())
