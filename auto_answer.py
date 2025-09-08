# Streamlit版（完成版）

```python
# streamlit_app.py
# ------------------------------------------------------------
# 🔗 answer-genkinka.jp専用内部リンク分析ツール（Streamlit・実クロール版）
# - 既存Tk/CTk版のロジックをStreamlitに移植
# - ダミーなし。実際にrequests+BeautifulSoupでクロールします
# - 収集上限: 500記事 / 自動で /blog/page/2/ も巡回
# - 分析完了後：画面表示 + 詳細CSVのダウンロード + 自動保存（任意）
# ------------------------------------------------------------

import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from datetime import datetime
import re
import csv
import io
import os
import sys
import time

st.set_page_config(page_title="answer-genkinka.jp 内部リンク分析（Streamlit）", layout="wide")

# =========================
# ユーティリティ
# =========================
def normalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        return f"https://{parsed.netloc.replace('www.', '')}{parsed.path.rstrip('/')}"
    except Exception:
        return url

def is_article_page(url: str) -> bool:
    """個別記事ページかどうか判定（シンプル版/Tk版準拠）"""
    path = urlparse(normalize_url(url)).path.lower()

    # 除外：明らかに記事ではないもの
    exclude_words = ['/site/', '/blog/', '/page/', '/feed', '/wp-', '.']
    if any(word in path for word in exclude_words):
        return False

    # 許可：ルート直下のスラッグ（/記事名）
    if path.startswith('/') and len(path) > 1:
        clean_path = path[1:].rstrip('/')
        if clean_path and '/' not in clean_path:
            return True

    return False

def is_crawlable(url: str) -> bool:
    """クロール対象かどうか判定"""
    path = urlparse(normalize_url(url)).path.lower()

    # 除外：明らかに不要なもの
    exclude_words = ['/site/', '/wp-admin', '/feed', '.jpg', '.png', '.css', '.js']
    if any(word in path for word in exclude_words):
        return False

    # 許可：ブログ関連 + 記事ページ
    return (path.startswith('/blog') or is_article_page(url))

def extract_links(soup: BeautifulSoup, current_url: str) -> list[str]:
    """リンク抽出（サイト内 & クロール対象のみ）"""
    links = []
    for a in soup.find_all('a', href=True):
        href = a.get('href', '').strip()
        if href and not href.startswith('#'):
            absolute = urljoin(current_url, href)
            if 'answer-genkinka.jp' in absolute and is_crawlable(absolute):
                links.append(normalize_url(absolute))
    return list(set(links))

def extract_content_links(soup: BeautifulSoup, current_url: str) -> list[dict]:
    """コンテンツエリアからリンク抽出（本文内リンクのみ）"""
    content = soup.select_one('.entry-content, .post-content, main, article')
    if not content:
        return []

    links = []
    for a in content.find_all('a', href=True):
        href = a.get('href', '').strip()
        text = a.get_text(strip=True) or ''
        if href and not href.startswith('#') and text:
            absolute = urljoin(current_url, href)
            if 'answer-genkinka.jp' in absolute and is_article_page(absolute):
                links.append({'url': normalize_url(absolute), 'anchor_text': text[:100]})
    return links

def sanitize_title(title: str, url: str) -> str:
    """サイト名などを除去"""
    if not title:
        return url
    # 「answer-genkinka | アンサー」等のサイト名除去
    return re.sub(r'\s*[|\-]\s*.*(answer-genkinka|アンサー).*$', '', title, flags=re.IGNORECASE)

# =========================
# 分析本体
# =========================
def analyze_site(start_url: str, max_pages: int = 500, status_cb=None, progress_cb=None):
    """
    - start_url から巡回し、/blog/page/2/ もキューに追加
    - 記事ページの被/発リンクを抽出
    - return: pages(dict), links(list[tuple]), detailed_links(list[dict])
    """
    pages = {}
    links = []
    detailed_links = []

    visited = set()
    to_visit = [normalize_url(start_url)]
    # ページネーションも巡回
    to_visit.append('https://answer-genkinka.jp/blog/page/2/')

    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0'})

    if status_cb:
        status_cb("収集中: 0記事")

    # ===== フェーズ1: ページ収集 =====
    while to_visit and len(pages) < max_pages:
        url = to_visit.pop(0)
        if url in visited:
            continue

        try:
            resp = session.get(url, timeout=10)
            if resp.status_code != 200:
                visited.add(url)
                continue

            soup = BeautifulSoup(resp.text, 'html.parser')

            # NOINDEXチェック
            robots = soup.find('meta', attrs={'name': 'robots'})
            if robots and 'noindex' in robots.get('content', '').lower():
                visited.add(url)
                continue

            # 記事一覧ページは収集のみ
            if '/blog' in url:
                page_links = extract_links(soup, url)
                new_links = [l for l in page_links if l not in visited and l not in to_visit]
                to_visit.extend(new_links)
                visited.add(url)
                if status_cb:
                    status_cb(f"収集中: {len(pages)}記事（一覧: 新規{len(new_links)}件）")
                if progress_cb:
                    progress_cb(len(pages) / max_pages)
                time.sleep(0.05)
                continue

            # 個別記事
            if is_article_page(url):
                title_el = soup.find('h1')
                title = sanitize_title(title_el.get_text(strip=True) if title_el else url, url)

                pages[url] = {'title': title, 'outbound_links': []}

                # 新規リンク発見
                page_links = extract_links(soup, url)
                new_links = [l for l in page_links if l not in visited and l not in to_visit]
                to_visit.extend(new_links)

            visited.add(url)

            if status_cb:
                status_cb(f"収集中: {len(pages)}記事")
            if progress_cb:
                progress_cb(len(pages) / max_pages)
            time.sleep(0.05)

        except Exception:
            # 失敗はスキップ
            visited.add(url)
            continue

    # ===== フェーズ2: リンク関係構築 =====
    processed = set()
    for url in list(pages.keys()):
        try:
            resp = session.get(url, timeout=10)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, 'html.parser')
            content_links = extract_content_links(soup, url)

            for link_data in content_links:
                target = link_data['url']
                if target in pages and target != url:
                    link_key = (url, target)
                    if link_key not in processed:
                        processed.add(link_key)
                        links.append((url, target))
                        pages[url]['outbound_links'].append(target)
                        detailed_links.append({
                            'source_url': url,
                            'source_title': pages[url]['title'],
                            'target_url': target,
                            'anchor_text': link_data['anchor_text']
                        })
        except Exception:
            continue

    # 被リンク数計算
    for u in pages:
        pages[u]['inbound_links'] = sum(1 for s, t in links if t == u)

    return pages, links, detailed_links

# =========================
# CSV出力
# =========================
def build_csv_bytes(pages: dict, detailed_links: list[dict]) -> bytes:
    """
    画面ダウンロード用（UTF-8 BOM）
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['番号', 'ページタイトル', 'URL', '被リンク元タイトル', '被リンク元URL', 'アンカーテキスト'])

    # ターゲット別にグループ化
    targets = {}
    for link in detailed_links:
        target = link['target_url']
        targets.setdefault(target, []).append(link)

    # 被リンク数でソート
    sorted_targets = sorted(targets.items(), key=lambda x: len(x[1]), reverse=True)

    row = 1
    for target, links_list in sorted_targets:
        title = pages.get(target, {}).get('title', target)
        for link in links_list:
            writer.writerow([row, title, target, link['source_title'], link['source_url'], link['anchor_text']])
            row += 1

    # 孤立ページも追加
    for url, info in pages.items():
        if info.get('inbound_links', 0) == 0:
            writer.writerow([row, info.get('title', url), url, '', '', ''])
            row += 1

    data = buf.getvalue().encode('utf-8-sig')
    buf.close()
    return data

def auto_save_csv_to_disk(pages: dict, detailed_links: list[dict]) -> str | None:
    """
    ローカル/サーバーに日付フォルダで自動保存（任意）
    """
    try:
        # 実行ファイル基準（PyInstaller対応）
        if hasattr(sys, '_MEIPASS'):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))

        today = datetime.now().strftime("%Y-%m-%d")
        folder_path = os.path.join(base_dir, today)
        os.makedirs(folder_path, exist_ok=True)

        filename = f"answer-genkinka-{today}.csv"
        filepath = os.path.join(folder_path, filename)

        with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['番号', 'ページタイトル', 'URL', '被リンク元タイトル', '被リンク元URL', 'アンカーテキスト'])

            targets = {}
            for link in detailed_links:
                target = link['target_url']
                targets.setdefault(target, []).append(link)

            sorted_targets = sorted(targets.items(), key=lambda x: len(x[1]), reverse=True)
            row = 1
            for target, links_list in sorted_targets:
                title = pages.get(target, {}).get('title', target)
                for link in links_list:
                    writer.writerow([row, title, target, link['source_title'], link['source_url'], link['anchor_text']])
                    row += 1

            for url, info in pages.items():
                if info.get('inbound_links', 0) == 0:
                    writer.writerow([row, info.get('title', url), url, '', '', ''])
                    row += 1

        return filepath
    except Exception:
        return None

# =========================
# UI / 実行
# =========================
DEFAULT_URL = "https://answer-genkinka.jp/blog/"

st.title("🔗 answer-genkinka.jp専用内部リンク分析ツール（Streamlit・全自動版）")

col_url, col_opts = st.columns([0.7, 0.3])
with col_url:
    start_url = st.text_input("開始URL", value=DEFAULT_URL, help="例: https://answer-genkinka.jp/blog/")

with col_opts:
    max_pages = st.number_input("収集上限（記事）", min_value=50, max_value=2000, value=500, step=50)
    do_autosave = st.checkbox("分析完了後に自動保存（実行環境にCSV出力）", value=True)

# 自動実行（初回のみ）
if "auto_run_done" not in st.session_state:
    st.session_state.auto_run_done = False

run_now = False
c1, c2 = st.columns([0.3, 0.7])
with c1:
    if st.button("分析開始", type="primary"):
        run_now = True
with c2:
    st.write(" ")

if not st.session_state.auto_run_done and start_url.strip():
    run_now = True
    st.session_state.auto_run_done = True

status = st.empty()
progress = st.progress(0)

def status_cb(msg: str):
    status.info(msg)

def progress_cb(val: float):
    progress.progress(min(max(val, 0.0), 1.0))

if run_now:
    try:
        status_cb("準備中…")
        pages, links, detailed_links = analyze_site(start_url, int(max_pages), status_cb=status_cb, progress_cb=progress_cb)

        total = len(pages)
        isolated = sum(1 for p in pages.values() if p.get('inbound_links', 0) == 0)
        popular5 = sum(1 for p in pages.values() if p.get('inbound_links', 0) >= 5)
        st.success(f"分析完了: {total}記事 / {len(links)}リンク / 孤立{isolated}件 / 人気(5+) {popular5}件")

        # 結果テーブル
        sorted_pages = sorted(pages.items(), key=lambda x: x[1].get('inbound_links', 0), reverse=True)

        # 左: サマリ / 右: リスト
        left, right = st.columns([0.35, 0.65])
        with left:
            st.subheader("サマリ")
            st.metric("記事数", total)
            st.metric("リンク数", len(links))
            st.metric("孤立ページ", isolated)
            st.metric("人気(被10+)", sum(1 for p in pages.values() if p.get('inbound_links', 0) >= 10))

            # CSVダウンロード
            csv_bytes = build_csv_bytes(pages, detailed_links)
            st.download_button(
                label="詳細CSVをダウンロード",
                data=csv_bytes,
                file_name=f"answer-genkinka-{datetime.now().strftime('%Y-%m-%d')}.csv",
                mime="text/csv"
            )

            # 自動保存
            saved_path = None
            if do_autosave:
                saved_path = auto_save_csv_to_disk(pages, detailed_links)
            if saved_path:
                st.caption(f"自動保存: {saved_path}")

        with right:
            st.subheader("記事ランキング（被リンク降順）")
            for i, (u, info) in enumerate(sorted_pages, start=1):
                inbound = info.get('inbound_links', 0)
                outbound = len(info.get('outbound_links', []))

                if inbound == 0:
                    eval_text = "🚨要改善"
                elif inbound >= 10:
                    eval_text = "🏆超人気"
                elif inbound >= 5:
                    eval_text = "✅人気"
                else:
                    eval_text = "⚠️普通"

                st.markdown(
                    f"**{i}. {info.get('title','')[:50]}...**  \n"
                    f"被リンク: **{inbound}** / 発リンク: {outbound} / {eval_text}  \n"
                    f"[{u}]({u})"
                )

        status_cb("完了")
        progress_cb(1.0)

        # 詳細リンクのプレビュー
        with st.expander("本文内リンク（詳細・ターゲット別）"):
            # ターゲット別にグループ化
            targets = {}
            for link in detailed_links:
                targets.setdefault(link['target_url'], []).append(link)
            sorted_targets = sorted(targets.items(), key=lambda x: len(x[1]), reverse=True)

            for tgt, lst in sorted_targets[:200]:  # 表示過多防止で最大200ターゲット
                st.markdown(f"**{pages.get(tgt,{}).get('title',tgt)}**  \n[{tgt}]({tgt})  \n被リンク: **{len(lst)}**")
                for lk in lst[:50]:  # ターゲットごと最大50件表示
                    st.markdown(
                        f"- from: [{lk['source_title']}]({lk['source_url']})  \n"
                        f"  アンカー: `{lk['anchor_text']}`"
                    )
                st.divider()

    except Exception as e:
        st.error(f"分析エラー: {e}")
else:
    st.info("「分析開始」を押すか、ページ表示直後の自動実行をお待ちください。")
```
