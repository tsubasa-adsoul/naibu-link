#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
内部リンク構造分析ツール（Streamlit完全版）
- オンライン自動クロール機能
- CSVアップロード機能
- ネットワーク図表示
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import re
from collections import Counter
from io import StringIO
import tempfile
import os

# PyVis
try:
    from pyvis.network import Network
    HAS_PYVIS = True
except ImportError:
    HAS_PYVIS = False

st.set_page_config(
    page_title="内部リンク構造分析ツール",
    page_icon="🔗",
    layout="wide"
)

# サイト設定（元の13サイト全て）
SITES_CONFIG = {
    "Answer現金化": {
        "base_url": "https://answer-genkinka.com",
        "module_name": "answer"
    },
    "ありがたや": {
        "base_url": "https://arigataya.co.jp",
        "module_name": "arigataya"
    },
    "ビックギフト": {
        "base_url": "https://bic-gift.co.jp", 
        "module_name": "bicgift"
    },
    "クレかえる": {
        "base_url": "https://kurekaeru.jp",
        "module_name": "crecaeru"
    },
    "ファミペイ": {
        "base_url": "https://flashpay-famipay.com",
        "module_name": "flashpay_famipay"
    },
    "メディア": {
        "base_url": "https://flashpay-media.com",
        "module_name": "flashpay_media"
    },
    "フレンドペイ": {
        "base_url": "https://friendpay.me",
        "module_name": "friendpay"
    },
    "不用品回収隊": {
        "base_url": "https://fuyouhin-kaishuu.com",
        "module_name": "fuyouhin"
    },
    "買取LIFE": {
        "base_url": "https://kaitori-life.com",
        "module_name": "kaitori_life"
    },
    "カウール": {
        "base_url": "https://kau-ru.com",
        "module_name": "kau_ru"
    },
    "MorePay": {
        "base_url": "https://morepay.jp",
        "module_name": "morepay"
    },
    "ペイフル": {
        "base_url": "https://payful.jp",
        "module_name": "payful"
    },
    "スマートペイ": {
        "base_url": "https://smartpay-gift.com",
        "module_name": "smart"
    },
    "XGIFT": {
        "base_url": "https://xgift.jp",
        "module_name": "xgift"
    }
}

def normalize_url(url, base_url):
    if not isinstance(url, str): return ""
    try:
        full_url = urljoin(base_url, url.strip())
        parsed = urlparse(full_url)
        netloc = parsed.netloc.lower().replace('www.', '')
        path = parsed.path.rstrip('/')
        if not path: path = '/'
        return f"https://{netloc}{path}"
    except: return ""

def is_content_url(url, base_domain):
    try:
        path = urlparse(url).path.lower()
        
        # 除外パターン
        exclude_patterns = [
            r'/sitemap', r'\.xml$', r'/wp-admin/', r'/wp-content/',
            r'/feed/', r'\.(jpg|jpeg|png|gif|pdf|zip)$',
            r'#', r'\?replytocom=', r'attachment_id='
        ]
        if any(re.search(p, path) for p in exclude_patterns):
            return False

        # 許可パターン
        allow_patterns = [
            r'^/$',
            r'^/[a-z0-9\-_]+/?$',
            r'^/category/',
            r'^/blog/',
            r'^/archives/',
            r'^/\d{4}/',
        ]
        return any(re.search(p, path) for p in allow_patterns)
    except:
        return False

def extract_from_sitemap(sitemap_url, session):
    urls = set()
    try:
        res = session.get(sitemap_url, timeout=20)
        if not res.ok: return urls
        soup = BeautifulSoup(res.content, 'lxml')
        
        # サイトマップインデックス
        sitemap_indexes = soup.find_all('sitemap')
        if sitemap_indexes:
            for sitemap in sitemap_indexes:
                if loc := sitemap.find('loc'):
                    urls.update(extract_from_sitemap(loc.text.strip(), session))
        
        # URL一覧
        for url_tag in soup.find_all('url'):
            if loc := url_tag.find('loc'):
                urls.add(loc.text.strip())
    except Exception:
        pass
    return urls

def extract_links_from_page(soup, base_url):
    links = []
    
    # コンテンツエリアを特定
    content_area = soup.select_one('.entry-content, .post-content, .content, main, article') or soup.body
    
    # 不要部分を除去
    for exclude in content_area.select('header, footer, nav, aside, .sidebar, .widget, .share, .breadcrumb'):
        exclude.decompose()
    
    # リンクを抽出
    for a in content_area.find_all('a', href=True):
        href = a.get('href')
        if href and not href.startswith('#'):
            anchor_text = a.get_text(strip=True) or a.get('title', '') or '[リンク]'
            links.append({
                'url': href,
                'anchor_text': anchor_text
            })
    
    return links

def crawl_site(site_name, base_url, max_pages=100):
    """サイトをクロールして内部リンクデータを収集"""
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    log_container = st.empty()
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    domain = urlparse(base_url).netloc.lower().replace('www.', '')
    
    # サイトマップからURL収集
    status_text.text("サイトマップを解析中...")
    sitemap_urls = extract_from_sitemap(urljoin(base_url, '/sitemap.xml'), session)
    initial_urls = list(set([base_url] + list(sitemap_urls)))
    
    # コンテンツURLのみを抽出
    to_visit = [u for u in initial_urls if is_content_url(u, domain)][:max_pages]
    
    if not to_visit:
        st.warning("クロール対象のURLが見つかりませんでした")
        return pd.DataFrame()
    
    visited = set()
    pages = {}
    all_links = []
    
    logs = []
    
    for i, url in enumerate(to_visit):
        if url in visited:
            continue
            
        try:
            progress = (i + 1) / len(to_visit)
            progress_bar.progress(progress)
            status_text.text(f"クロール中: {i+1}/{len(to_visit)} - {url[:60]}...")
            
            response = session.get(url, timeout=15)
            if response.status_code != 200:
                continue
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # noindexチェック
            if soup.find('meta', attrs={'name': 'robots', 'content': re.compile(r'noindex', re.I)}):
                continue
            
            # タイトル取得
            title_tag = soup.find('h1') or soup.find('title')
            title = title_tag.get_text(strip=True) if title_tag else url
            title = re.sub(r'\s*[|\-].*$', '', title).strip()
            
            pages[url] = {'title': title}
            
            # リンク抽出
            extracted_links = extract_links_from_page(soup, base_url)
            
            link_count = 0
            for link_data in extracted_links:
                normalized_link = normalize_url(link_data['url'], base_url)
                
                # 内部リンクかチェック
                link_domain = urlparse(normalized_link).netloc.lower().replace('www.', '')
                if link_domain == domain and is_content_url(normalized_link, domain):
                    all_links.append({
                        'source_url': url,
                        'source_title': title,
                        'target_url': normalized_link,
                        'anchor_text': link_data['anchor_text']
                    })
                    link_count += 1
                    
                    # 新しいURLを発見した場合、クロール対象に追加
                    if normalized_link not in visited and normalized_link not in to_visit and len(to_visit) < max_pages:
                        to_visit.append(normalized_link)
            
            visited.add(url)
            
            log_msg = f"[{time.strftime('%H:%M:%S')}] {title[:40]} -> {link_count}個のリンク"
            logs.append(log_msg)
            
            # ログ表示（最新10件）
            log_container.code('\n'.join(logs[-10:]), language="log")
            
            time.sleep(0.5)  # サーバー負荷軽減
            
        except Exception as e:
            log_msg = f"[{time.strftime('%H:%M:%S')}] エラー: {url} - {e}"
            logs.append(log_msg)
    
    status_text.text("分析データを生成中...")
    
    # CSVデータ生成
    csv_data = []
    
    # URLとタイトルのマッピング
    url_to_title = {url: info['title'] for url, info in pages.items()}
    
    # 被リンク数計算
    target_counts = Counter(link['target_url'] for link in all_links)
    
    # 被リンク数順にソート
    sorted_targets = sorted(target_counts.items(), key=lambda x: x[1], reverse=True)
    
    row_number = 1
    for target_url, _ in sorted_targets:
        target_title = url_to_title.get(target_url, target_url)
        
        # このターゲットへのリンクを取得
        target_links = [link for link in all_links if link['target_url'] == target_url]
        
        for link in target_links:
            csv_data.append({
                'A_番号': row_number,
                'B_ページタイトル': target_title,
                'C_URL': target_url,
                'D_被リンク元ページタイトル': link['source_title'],
                'E_被リンク元ページURL': link['source_url'],
                'F_被リンク元ページアンカーテキスト': link['anchor_text']
            })
        
        row_number += 1
    
    # 孤立ページも追加
    for url, info in pages.items():
        if url not in target_counts:
            csv_data.append({
                'A_番号': row_number,
                'B_ページタイトル': info['title'],
                'C_URL': url,
                'D_被リンク元ページタイトル': '',
                'E_被リンク元ページURL': '',
                'F_被リンク元ページアンカーテキスト': ''
            })
            row_number += 1
    
    progress_bar.progress(1.0)
    status_text.text(f"分析完了: {len(pages)}ページ、{len(all_links)}リンクを検出")
    
    return pd.DataFrame(csv_data)

def create_network_visualization(df, site_name, top_n=40):
    """ネットワーク図を作成"""
    if not HAS_PYVIS:
        return None
    
    try:
        edges_df = df[
            (df['E_被リンク元ページURL'].astype(str) != "") &
            (df['C_URL'].astype(str) != "")
        ].copy()

        if edges_df.empty:
            return None

        # 被リンク数計算
        in_counts = edges_df.groupby('C_URL').size().sort_values(ascending=False)
        top_targets = set(in_counts.head(top_n).index)
        
        # 上位ページ間のリンクのみ
        sub_edges = edges_df[
            edges_df['C_URL'].isin(top_targets) & 
            edges_df['E_被リンク元ページURL'].isin(top_targets)
        ]
        
        if sub_edges.empty:
            return None
        
        # エッジ集約
        agg = sub_edges.groupby(['E_被リンク元ページURL', 'C_URL']).size().reset_index(name='weight')
        
        # URL→タイトルマッピング
        url2title = {}
        for _, r in df[['B_ページタイトル','C_URL']].drop_duplicates().iterrows():
            if r['C_URL']:
                url2title[r['C_URL']] = r['B_ページタイトル']
        for _, r in df[['D_被リンク元ページタイトル','E_被リンク元ページURL']].drop_duplicates().iterrows():
            if r['E_被リンク元ページURL']:
                url2title.setdefault(r['E_被リンク元ページURL'], r['D_被リンク元ページタイトル'])

        # PyVisネットワーク作成
        net = Network(height="800px", width="100%", directed=True, bgcolor="#ffffff")
        
        net.barnes_hut(
            gravity=-8000,
            central_gravity=0.3,
            spring_length=200,
            spring_strength=0.05,
            damping=0.15
        )

        # ノード追加
        nodes = set(agg['E_被リンク元ページURL']).union(set(agg['C_URL']))
        for u in nodes:
            size = max(15, min(50, int(15 + (in_counts.get(u, 0) * 2))))
            label = str(url2title.get(u, u))[:20]
            if len(label) < len(str(url2title.get(u, u))):
                label += "..."
            
            net.add_node(
                u,
                label=label,
                title=f"{url2title.get(u, u)}<br>{u}",
                size=size
            )

        # エッジ追加
        for _, r in agg.iterrows():
            net.add_edge(
                r['E_被リンク元ページURL'], 
                r['C_URL'], 
                width=min(int(r['weight']), 10)
            )

        # HTML生成
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as tmp:
            net.save_graph(tmp.name)
            with open(tmp.name, 'r', encoding='utf-8') as f:
                html_content = f.read()
            os.unlink(tmp.name)
            
        return html_content
        
    except Exception:
        return None

def main():
    st.title("🔗 内部リンク構造分析ツール")
    
    # セッションステート初期化
    if 'analysis_data' not in st.session_state:
        st.session_state.analysis_data = None
    if 'site_name' not in st.session_state:
        st.session_state.site_name = None

    # サイドバー
    with st.sidebar:
        st.header("📁 データソース")
        
        # データソース選択
        data_source = st.radio(
            "分析方法を選択",
            ["オンライン自動分析", "CSVファイルアップロード"]
        )
        
        if data_source == "オンライン自動分析":
            st.subheader("サイト選択")
            selected_site = st.selectbox("分析対象サイト", list(SITES_CONFIG.keys()))
            
            max_pages = st.slider("最大ページ数", 50, 500, 200, 50)
            
            if st.button("🚀 分析開始"):
                config = SITES_CONFIG[selected_site]
                with st.spinner(f"{selected_site}を分析中..."):
                    df = crawl_site(selected_site, config["base_url"], max_pages)
                    if not df.empty:
                        st.session_state.analysis_data = df
                        st.session_state.site_name = selected_site
                        st.success("分析完了！")
                        st.rerun()
        
        else:
            uploaded_file = st.file_uploader("CSVファイルをアップロード", type=['csv'])
            if uploaded_file:
                try:
                    df = pd.read_csv(uploaded_file, encoding="utf-8-sig").fillna("")
                    st.session_state.analysis_data = df
                    st.session_state.site_name = uploaded_file.name
                    st.success("CSVファイル読み込み完了！")
                except Exception as e:
                    st.error(f"読み込みエラー: {e}")
        
        # 設定
        st.header("🛠️ 表示設定")
        network_top_n = st.slider("ネットワーク図：上位N件", 10, 100, 40, 5)

    # メイン画面
    if st.session_state.analysis_data is None:
        st.info("👈 サイドバーから分析を実行してください")
        return

    df = st.session_state.analysis_data
    site_name = st.session_state.site_name

    # CSVダウンロード
    csv_string = df.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        label="📥 分析結果をCSVダウンロード",
        data=csv_string,
        file_name=f"{site_name}_analysis.csv",
        mime="text/csv"
    )

    # タブ表示
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 データ一覧",
        "🏛️ ピラーページ", 
        "🧩 クラスター分析",
        "🧭 孤立記事",
        "📈 ネットワーク図"
    ])

    # データ処理
    pages_df = df[['B_ページタイトル', 'C_URL']].drop_duplicates().copy()
    has_src = (df['D_被リンク元ページタイトル'].astype(str) != "") & (df['E_被リンク元ページURL'].astype(str) != "")
    inbound_counts = df[has_src].groupby('C_URL').size()
    pages_df['被リンク数'] = pages_df['C_URL'].map(inbound_counts).fillna(0).astype(int)
    pages_df = pages_df.sort_values('被リンク数', ascending=False).reset_index(drop=True)

    with tab1:
        st.header("📊 全データ")
        st.dataframe(df, use_container_width=True)

    with tab2:
        st.header("🏛️ ピラーページ分析")
        st.dataframe(pages_df, use_container_width=True)
        
        if len(pages_df) > 0:
            top20 = pages_df.head(20)
            fig = px.bar(
                top20.sort_values('被リンク数'), 
                x='被リンク数', 
                y='B_ページタイトル',
                orientation='h',
                title="被リンク数 TOP20",
                height=600
            )
            fig.update_layout(yaxis={'categoryorder': 'total ascending'})
            st.plotly_chart(fig, use_container_width=True)

    with tab3:
        st.header("🧩 クラスター分析（アンカーテキスト）")
        
        anchors = df[df['F_被リンク元ページアンカーテキスト'].astype(str) != '']
        if not anchors.empty:
            anchor_counts = Counter(anchors['F_被リンク元ページアンカーテキスト'])
            anchor_df = pd.DataFrame(anchor_counts.most_common(), columns=['アンカーテキスト', '頻度'])
            
            total = sum(anchor_counts.values())
            hhi = sum((c/total)**2 for c in anchor_counts.values()) if total else 0.0
            diversity = 1 - hhi
            
            st.metric("アンカーテキスト多様性", f"{diversity:.3f}")
            st.dataframe(anchor_df, use_container_width=True)
        else:
            st.warning("アンカーテキストデータがありません")

    with tab4:
        st.header("🧭 孤立記事")
        
        isolated = pages_df[pages_df['被リンク数'] == 0].copy()
        if not isolated.empty:
            st.warning(f"孤立記事が {len(isolated)} 件見つかりました")
            st.dataframe(isolated[['B_ページタイトル', 'C_URL']], use_container_width=True)
        else:
            st.success("孤立記事はありません")

    with tab5:
        st.header("📈 ネットワーク図")
        
        if HAS_PYVIS:
            with st.spinner("ネットワーク図を生成中..."):
                html_content = create_network_visualization(df, site_name, network_top_n)
                
                if html_content:
                    st.components.v1.html(html_content, height=820)
                    st.success(f"ネットワーク図を表示しました（上位{network_top_n}件）")
                else:
                    st.error("ネットワーク図の生成に失敗しました")
        else:
            st.error("PyVisライブラリがインストールされていません")

if __name__ == "__main__":
    main()
