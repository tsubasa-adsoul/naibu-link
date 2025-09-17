import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import re
from collections import Counter
import tempfile
import os

# PyVis
try:
    from pyvis.network import Network
    HAS_PYVIS = True
except ImportError:
    HAS_PYVIS = False

st.set_page_config(page_title="内部リンク構造分析ツール", page_icon="🔗", layout="wide")

# 14サイト設定
SITES = {
    "Answer現金化": "https://answer-genkinka.com",
    "ありがたや": "https://arigataya.co.jp", 
    "ビックギフト": "https://bic-gift.co.jp",
    "クレかえる": "https://crecaeru.co.jp",
    "ファミペイ": "https://flashpay-famipay.com",
    "メディア": "https://flashpay-media.com",
    "フレンドペイ": "https://friendpay.me",
    "不用品回収隊": "https://fuyouhin-kaishuu.com",
    "買取LIFE": "https://kaitori-life.com",
    "カウール": "https://kau-ru.com",
    "MorePay": "https://morepay.jp",
    "ペイフル": "https://payful.jp", 
    "スマートペイ": "https://smartpay-gift.com",
    "XGIFT": "https://xgift.jp"
}

def crawl_site(site_name, base_url):
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0'})
    domain = urlparse(base_url).netloc.lower().replace('www.', '')
    
    # サイトマップ取得
    st.info("サイトマップを解析中...")
    urls = set([base_url])
    try:
        res = session.get(urljoin(base_url, '/sitemap.xml'), timeout=20)
        if res.ok:
            soup = BeautifulSoup(res.content, 'lxml')
            for loc in soup.find_all('loc'):
                url_text = loc.text.strip()
                if not any(x in url_text.lower() for x in ['.xml', '/wp-admin/', 'attachment_id']):
                    urls.add(url_text)
    except:
        st.warning("サイトマップ取得に失敗、手動でクロール開始")
    
    # クロール対象を制限
    to_visit = list(urls)[:100]  # 最大100ページに制限
    
    if not to_visit:
        st.error("クロール対象URLが見つかりませんでした")
        return pd.DataFrame()
    
    st.success(f"クロール開始: {len(to_visit)}個のURL")
    
    progress_bar = st.progress(0)
    pages = {}
    all_links = []
    
    for i, url in enumerate(to_visit):
        try:
            progress_bar.progress((i + 1) / len(to_visit))
            st.text(f"クロール中: {i+1}/{len(to_visit)} - {url[:50]}...")
            
            res = session.get(url, timeout=10)
            if not res.ok:
                continue
                
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # タイトル取得
            title = (soup.find('h1') or soup.find('title')).get_text(strip=True) if (soup.find('h1') or soup.find('title')) else url
            title = re.sub(r'\s*[|\-].*$', '', title).strip()
            pages[url] = title
            
            # リンク抽出
            content = soup.select_one('.entry-content, .post-content, main, article') or soup.body
            
            for a in content.find_all('a', href=True):
                href = a['href']
                if href and not href.startswith('#'):
                    full_url = urljoin(base_url, href)
                    link_domain = urlparse(full_url).netloc.lower().replace('www.', '')
                    
                    if link_domain == domain:
                        all_links.append({
                            'source_url': url,
                            'source_title': title,
                            'target_url': full_url,
                            'anchor_text': a.get_text(strip=True) or '[リンク]'
                        })
            
            time.sleep(0.3)
            
        except Exception as e:
            st.text(f"エラー: {url} - {e}")
    
    # CSVデータ生成
    if not all_links:
        return pd.DataFrame()
    
    csv_data = []
    target_counts = Counter(link['target_url'] for link in all_links)
    
    row_num = 1
    for target_url, count in target_counts.most_common():
        target_title = pages.get(target_url, target_url)
        target_links = [link for link in all_links if link['target_url'] == target_url]
        
        for link in target_links:
            csv_data.append({
                'A_番号': row_num,
                'B_ページタイトル': target_title,
                'C_URL': target_url,
                'D_被リンク元ページタイトル': link['source_title'],
                'E_被リンク元ページURL': link['source_url'],
                'F_被リンク元ページアンカーテキスト': link['anchor_text']
            })
        row_num += 1
    
    return pd.DataFrame(csv_data)

def create_network(df, top_n=30):
    if not HAS_PYVIS or df.empty:
        return None
    
    edges = df[(df['E_被リンク元ページURL'] != '') & (df['C_URL'] != '')].copy()
    if edges.empty:
        return None
    
    # 上位ページのみ
    in_counts = edges.groupby('C_URL').size().sort_values(ascending=False)
    top_pages = set(in_counts.head(top_n).index)
    sub_edges = edges[edges['C_URL'].isin(top_pages)]
    
    if sub_edges.empty:
        return None
    
    # ネットワーク作成
    net = Network(height="700px", width="100%", directed=True)
    
    # ノード追加
    for url in top_pages:
        title = df[df['C_URL'] == url]['B_ページタイトル'].iloc[0]
        size = max(15, min(40, int(in_counts.get(url, 0) * 3)))
        net.add_node(url, label=title[:15], title=title, size=size)
    
    # エッジ追加
    for _, row in sub_edges.iterrows():
        if row['E_被リンク元ページURL'] in top_pages:
            net.add_edge(row['E_被リンク元ページURL'], row['C_URL'])
    
    # HTML生成
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as tmp:
            net.save_graph(tmp.name)
            with open(tmp.name, 'r', encoding='utf-8') as f:
                html_content = f.read()
            os.unlink(tmp.name)
        return html_content
    except:
        return None

def main():
    st.title("🔗 内部リンク構造分析ツール")
    
    if 'analysis_data' not in st.session_state:
        st.session_state.analysis_data = None
    
    with st.sidebar:
        st.header("📁 データソース")
        
        # オンライン分析
        st.subheader("オンライン分析")
        selected_site = st.selectbox("サイト選択", list(SITES.keys()))
        
        if st.button("🚀 分析開始"):
            base_url = SITES[selected_site]
            with st.spinner(f"{selected_site}を分析中..."):
                df = crawl_site(selected_site, base_url)
                if not df.empty:
                    st.session_state.analysis_data = df
                    st.session_state.site_name = selected_site
                    st.success("分析完了！")
                    st.rerun()
                else:
                    st.error("分析に失敗しました")
        
        st.divider()
        
        # CSVアップロード
        st.subheader("CSVアップロード")
        uploaded_file = st.file_uploader("CSVファイル", type=['csv'])
        if uploaded_file:
            try:
                df = pd.read_csv(uploaded_file, encoding="utf-8-sig").fillna("")
                st.session_state.analysis_data = df
                st.session_state.site_name = uploaded_file.name
                st.success("読み込み完了！")
            except Exception as e:
                st.error(f"読み込みエラー: {e}")
    
    # メイン表示
    if st.session_state.analysis_data is None:
        st.info("👈 サイドバーから分析を実行してください")
        return
    
    df = st.session_state.analysis_data
    site_name = getattr(st.session_state, 'site_name', 'Unknown')
    
    # CSVダウンロード
    csv_data = df.to_csv(index=False, encoding="utf-8-sig")
    st.download_button("📥 結果をCSVダウンロード", csv_data, f"{site_name}_analysis.csv", "text/csv")
    
    # タブ表示
    tab1, tab2, tab3 = st.tabs(["📊 データ一覧", "🏛️ ピラーページ", "📈 ネットワーク図"])
    
    with tab1:
        st.dataframe(df, use_container_width=True)
    
    with tab2:
        pages = df[['B_ページタイトル', 'C_URL']].drop_duplicates()
        has_links = df[(df['D_被リンク元ページタイトル'] != '') & (df['E_被リンク元ページURL'] != '')]
        link_counts = has_links.groupby('C_URL').size()
        pages['被リンク数'] = pages['C_URL'].map(link_counts).fillna(0).astype(int)
        pages = pages.sort_values('被リンク数', ascending=False)
        
        st.dataframe(pages, use_container_width=True)
    
    with tab3:
        if HAS_PYVIS:
            with st.spinner("ネットワーク図生成中..."):
                html_content = create_network(df)
                if html_content:
                    st.components.v1.html(html_content, height=720)
                else:
                    st.error("ネットワーク図の生成に失敗しました")
        else:
            st.error("PyVisライブラリが必要です")

if __name__ == "__main__":
    main()
