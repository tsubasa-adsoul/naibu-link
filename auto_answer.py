# streamlit_app.py
# ------------------------------------------------------------
# 🔗 answer-genkinka.jp専用 内部リンク分析（Streamlit・実クロール完全版）
# - 既存CTk版の移植 + 不具合修正
# - 個別記事判定を強化（/blog/<slug>、/YYYY/MM/<slug>、/直下スラッグ）
# - ページネーション自動探索（rel=next, .pagination）
# - sitemap.xml もシードに追加（/blog/配下優先）
# - ダミー/サンプル一切なし
# ------------------------------------------------------------

import streamlit as st
import requests
from bs4 import BeautifulSoup, SoupStrainer
from urllib.parse import urlparse, urljoin, urlunparse
from datetime import datetime
import re
import csv
import io
import os
import sys
import time
from collections import deque

st.set_page_config(page_title="answer-genkinka.jp 内部リンク分析", layout="wide")

DOMAIN = "answer-genkinka.jp"
BASE = f"https://{DOMAIN}"

# ===== ユーティリティ =====
def normalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        p = urlparse(url)
        # www除去・クエリ/フラグメント除去・末尾スラッシュ除去
        clean = urlunparse(("https", p.netloc.replace("www.", ""), p.path.rstrip("/"), "", "", ""))
        return clean
    except Exception:
        return url

def same_site(url: str) -> bool:
    try:
        return urlparse(url).netloc.replace("www.", "") == DOMAIN
    except Exception:
        return False

# 個別記事パターン:
ARTICLE_PATTERNS = [
    re.compile(r"^/blog/[^/]+/?$", re.IGNORECASE),            # /blog/slug
    re.compile(r"^/\d{4}/\d{1,2}/[^/]+/?$", re.IGNORECASE),   # /2025/09/slug
    re.compile(r"^/[^/]+/?$", re.IGNORECASE),                 # /slug（ルート直下）
]

def is_article_page(url: str) -> bool:
    path = urlparse(normalize_url(url)).path
    # 除外拡張子/ディレクトリ
    if any(path.endswith(ext) for ext in (".jpg",".jpeg",".png",".gif",".webp",".svg",".pdf",".css",".js",".zip",".rar",".7z",".mp4",".mp3",".webm",".ico")):
        return False
    if any(seg in path.lower() for seg in ["/wp-admin","/wp-json","/feed","/page/","/tag/","/category/","/author/","/site/","/search"]):
        return False
    # 個別記事パターンのいずれかに一致
    return any(pat.match(path) for pat in ARTICLE_PATTERNS)

def is_crawlable(url: str) -> bool:
    path = urlparse(normalize_url(url)).path.lower()
    if any(path.endswith(ext) for ext in (".jpg",".jpeg",".png",".gif",".webp",".svg",".pdf",".css",".js",".zip",".rar",".7z",".mp4",".mp3",".webm",".ico")):
        return False
    if any(bad in path for bad in ["/wp-admin","/wp-login","/feed","/tag/","/author/","/site/","/search"]):
        return False
    # /blog 一覧や記事、年/月アーカイブなどは許容
    return True

def get_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36"
    })
    return s

def fetch(session, url, timeout=12, retries=2, sleep=0.6):
    last_exc = None
    for i in range(retries+1):
        try:
            r = session.get(url, timeout=timeout)
            # 2xxのみ採用
            if 200 <= r.status_code < 300:
                return r
            # 429/5xx →待って再試行
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(sleep * (i+1))
            else:
                return r  # 404等はそのまま返す
        except Exception as e:
            last_exc = e
            time.sleep(sleep * (i+1))
    if last_exc:
        raise last_exc
    return None

CONTENT_SELECTORS = [
    ".entry-content",
    ".post-content",
    "article .entry-content",
    "article .content",
    ".single-post",
    ".p-entry__body",
    ".c-entry__content",
    ".article-body",
    "main article",
    "main .content",
    "#content article",
    "article",
    "main",
]

def extract_content_links(soup: BeautifulSoup, current_url: str):
    # 本文に近い領域を優先
    content = None
    for sel in CONTENT_SELECTORS:
        content = soup.select_one(sel)
        if content:
            break
    if not content:
        return []

    out = []
    for a in content.find_all("a", href=True):
        href = a.get("href","").strip()
        text = (a.get_text(strip=True) or "").strip()
        if not href or href.startswith("#") or not text:
            continue
        absu = urljoin(current_url, href)
        if same_site(absu) and is_article_page(absu):
            out.append({"url": normalize_url(absu), "anchor_text": text[:120]})
    # 重複排除（URL+anchor）
    seen = set()
    uniq = []
    for d in out:
        key = (d["url"], d["anchor_text"])
        if key not in seen:
            seen.add(key)
            uniq.append(d)
    return uniq

def sanitize_title(title: str, url: str) -> str:
    if not title:
        return url
    return re.sub(r"\s*[|\-]\s*.*(answer-genkinka|アンサー).*?$","", title, flags=re.IGNORECASE)

def collect_links_on_page(soup: BeautifulSoup, current_url: str):
    links = []
    for a in soup.find_all("a", href=True):
        href = a.get("href","").strip()
        if not href or href.startswith("#"):
            continue
        absu = urljoin(current_url, href)
        if same_site(absu) and is_crawlable(absu):
            links.append(normalize_url(absu))
    return list(dict.fromkeys(links))  # 順序保持で重複除去

def find_pagination_urls(soup: BeautifulSoup, current_url: str):
    """rel=next, .pagination, .nav-links から次ページを探索"""
    urls = set()
    for ln in soup.find_all("link", rel=lambda x: x and "next" in x):
        absu = urljoin(current_url, ln.get("href",""))
        if same_site(absu):
            urls.add(normalize_url(absu))
    for a in soup.select("a[rel='next'], .pagination a, .nav-links a"):
        absu = urljoin(current_url, a.get("href",""))
        if same_site(absu):
            urls.add(normalize_url(absu))
    return list(urls)

def seed_from_sitemap(session):
    """sitemap.xml から /blog/配下や記事っぽいURLをシードに追加"""
    seeds = set()
    for path in ["/sitemap.xml", "/sitemap_index.xml", "/sitemap1.xml"]:
        url = BASE + path
        try:
            r = fetch(session, url, timeout=10, retries=1)
            if not r or r.status_code != 200 or "xml" not in r.headers.get("Content-Type",""):
                continue
            # 軽量パース
            only_loc = SoupStrainer("loc")
            xsoup = BeautifulSoup(r.text, "xml", parse_only=only_loc)
            for loc in xsoup.find_all("loc"):
                locu = (loc.text or "").strip()
                if not locu:
                    continue
                if same_site(locu):
                    nloc = normalize_url(locu)
                    # /blog/配下 or 記事判定に合致
                    if "/blog/" in urlparse(nloc).path or is_article_page(nloc):
                        seeds.add(nloc)
        except Exception:
            continue
    return list(seeds)

# ===== 分析本体 =====
def analyze_site(start_url: str, max_pages: int, status_cb=None, progress_cb=None):
    pages = {}           # url -> {title, outbound_links[], inbound_links}
    links = []           # (source, target)
    detailed_links = []  # dict

    start_url = normalize_url(start_url)
    session = get_session()

    visited = set()
    q = deque()

    # 初期キュー：入力URL + ページネーション（後で自動検出） + sitemap
    q.append(start_url)
    # sitemapから種まき
    for u in seed_from_sitemap(session)[:1000]:
        q.append(u)

    processed_count = 0

    # フェーズ1：収集（一覧/記事問わず拾い、記事はpagesに登録）
    while q and len(pages) < max_pages:
        url = q.popleft()
        if url in visited or not same_site(url):
            continue
        visited.add(url)

        try:
            r = fetch(session, url, timeout=12, retries=2)
            if not r or r.status_code != 200:
                continue

            soup = BeautifulSoup(r.text, "html.parser")

            # robots noindex 回避
            robots = soup.find("meta", attrs={"name":"robots"})
            if robots and "noindex" in (robots.get("content","").lower()):
                continue

            # 記事なら登録
            if is_article_page(url):
                h1 = soup.find("h1")
                title = sanitize_title(h1.get_text(strip=True) if h1 else url, url)
                if url not in pages:
                    pages[url] = {"title": title, "outbound_links": [], "inbound_links": 0}

            # そのページから見つかるリンクを収集（一覧・記事を問わずクロール拡大）
            new_links = collect_links_on_page(soup, url)
            # ページネーションも収集
            new_links += find_pagination_urls(soup, url)
            # キューに追加（未訪問のみ）
            for nl in new_links:
                if nl not in visited and same_site(nl):
                    q.append(nl)

            processed_count += 1
            if status_cb:
                status_cb(f"収集中: 記事 {len(pages)} / キュー {len(q)} / 処理 {processed_count}")
            if progress_cb:
                # 記事の進捗ベース（最大値max_pagesに対する比率）
                progress_cb(min(len(pages)/max_pages, 0.98))
            time.sleep(0.03)

        except Exception:
            continue

    # フェーズ2：本文内リンク構築（記事のみを対象に本文を再解析）
    for url in list(pages.keys()):
        try:
            r = fetch(session, url, timeout=12, retries=2)
            if not r or r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            content_links = extract_content_links(soup, url)
            for ld in content_links:
                tgt = ld["url"]
                if tgt in pages and tgt != url:
                    links.append((url, tgt))
                    pages[url]["outbound_links"].append(tgt)
                    detailed_links.append({
                        "source_url": url,
                        "source_title": pages[url]["title"],
                        "target_url": tgt,
                        "anchor_text": ld["anchor_text"],
                    })
            if status_cb:
                status_cb(f"リンク解析中: {pages[url]['title'][:28]}…")
            time.sleep(0.02)
        except Exception:
            continue

    # 被リンク数
    for u in pages:
        pages[u]["inbound_links"] = sum(1 for s,t in links if t == u)

    if progress_cb:
        progress_cb(1.0)

    return pages, links, detailed_links

# ===== CSV =====
def build_csv_bytes(pages: dict, detailed_links: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["番号","ページタイトル","URL","被リンク元タイトル","被リンク元URL","アンカーテキスト"])

    targets = {}
    for d in detailed_links:
        targets.setdefault(d["target_url"], []).append(d)

    for i, (tgt, lst) in enumerate(sorted(targets.items(), key=lambda x: len(x[1]), reverse=True), start=1):
        ttitle = pages.get(tgt,{}).get("title", tgt)
        for d in lst:
            w.writerow([i, ttitle, tgt, d["source_title"], d["source_url"], d["anchor_text"]])

    # 孤立ページ
    row = len(detailed_links) + 1
    for u, info in pages.items():
        if info.get("inbound_links",0) == 0:
            w.writerow([row, info.get("title",u), u, "", "", ""])
            row += 1

    data = buf.getvalue().encode("utf-8-sig")
    buf.close()
    return data

def auto_save_csv(pages: dict, detailed_links: list[dict]) -> str | None:
    try:
        if hasattr(sys, "_MEIPASS"):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        d = datetime.now().strftime("%Y-%m-%d")
        folder = os.path.join(base_dir, d)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"answer-genkinka-{d}.csv")
        with open(path, "wb") as f:
            f.write(build_csv_bytes(pages, detailed_links))
        return path
    except Exception:
        return None

# ===== UI =====
st.title("🔗 answer-genkinka.jp 内部リンク分析（Streamlit・実クロール）")

col1, col2 = st.columns([0.7, 0.3])
with col1:
    start_url = st.text_input("開始URL", value=f"{BASE}/blog/", help="例: https://answer-genkinka.jp/blog/")
with col2:
    max_pages = st.number_input("記事収集上限", 50, 5000, 800, 50)
    do_autosave = st.checkbox("完了後に自動保存（CSV）", value=True)

status = st.empty()
prog = st.progress(0.0)

def status_cb(msg): status.info(msg)
def progress_cb(v): prog.progress(min(max(v,0.0),1.0))

run = st.button("分析開始", type="primary")

# 初回自動実行
if "auto_done" not in st.session_state:
    st.session_state.auto_done = False
if not st.session_state.auto_done and start_url.strip():
    run = True
    st.session_state.auto_done = True

if run:
    try:
        status_cb("開始します…")
        pages, links, detailed = analyze_site(start_url=start_url, max_pages=int(max_pages),
                                              status_cb=status_cb, progress_cb=progress_cb)
        total = len(pages)
        isolated = sum(1 for p in pages.values() if p.get("inbound_links",0) == 0)
        popular5 = sum(1 for p in pages.values() if p.get("inbound_links",0) >= 5)
        st.success(f"分析完了: 記事 {total} / リンク {len(links)} / 孤立 {isolated} / 人気(5+) {popular5}")

        left, right = st.columns([0.35, 0.65])
        with left:
            st.subheader("サマリ")
            st.metric("記事数", total)
            st.metric("リンク数", len(links))
            st.metric("孤立", isolated)
            st.metric("人気(被10+)", sum(1 for p in pages.values() if p.get("inbound_links",0) >= 10))

            csv_bytes = build_csv_bytes(pages, detailed)
            st.download_button(
                "詳細CSVをダウンロード",
                data=csv_bytes,
                file_name=f"answer-genkinka-{datetime.now().strftime('%Y-%m-%d')}.csv",
                mime="text/csv",
            )
            if do_autosave:
                pth = auto_save_csv(pages, detailed)
                if pth:
                    st.caption(f"自動保存: {pth}")

        with right:
            st.subheader("記事ランキング（被リンク降順）")
            for i, (u, info) in enumerate(sorted(pages.items(), key=lambda x: x[1].get("inbound_links",0), reverse=True), start=1):
                inbound = info.get("inbound_links",0)
                outbound = len(info.get("outbound_links",[]))
                if inbound == 0: tag = "🚨要改善"
                elif inbound >= 10: tag = "🏆超人気"
                elif inbound >= 5: tag = "✅人気"
                else: tag = "⚠️普通"
                st.markdown(
                    f"**{i}. {info.get('title','')[:60]}**  \n"
                    f"被リンク: **{inbound}** / 発リンク: {outbound} / {tag}  \n"
                    f"[{u}]({u})"
                )

        with st.expander("本文内リンク（ターゲット別 詳細）", expanded=False):
            targets = {}
            for d in detailed:
                targets.setdefault(d["target_url"], []).append(d)
            for tgt, lst in sorted(targets.items(), key=lambda x: len(x[1]), reverse=True)[:300]:
                st.markdown(f"**{pages.get(tgt,{}).get('title',tgt)}**  \n[{tgt}]({tgt})  \n被リンク: **{len(lst)}**")
                for dd in lst[:80]:
                    st.markdown(f"- from: [{dd['source_title']}]({dd['source_url']})  \n  アンカー: `{dd['anchor_text']}`")
                st.divider()

        status_cb("完了")
        progress_cb(1.0)

    except Exception as e:
        st.error(f"分析エラー: {e}")
else:
    st.info("「分析開始」を押すか、ページ表示直後の自動実行でクロールを開始します。")
