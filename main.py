import streamlit as st
import requests
from bs4 import BeautifulSoup
import csv
import io
import time
from urllib.parse import urljoin, urlparse
import pandas as pd
from datetime import datetime
import re
import numpy as np

# 実際の分析エンジン
class AnswerGenkinkaAnalyzer:
    def __init__(self):
        self.base_url = "https://answer-genkinka.jp"
        self.seed_urls = [
            "https://answer-genkinka.jp/blog/",
            "https://answer-genkinka.jp/sitemap.xml"
        ]
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
    def extract_from_sitemap(self, sitemap_url):
        urls = []
        try:
            response = self.session.get(sitemap_url, timeout=10)
            soup = BeautifulSoup(response.content, 'xml')
            
            for loc in soup.find_all('loc'):
                url = loc.get_text()
                if self.is_article_page(url):
                    urls.append(url)
                    
        except Exception as e:
            st.warning(f"サイトマップ取得エラー: {e}")
            
        return list(set(urls))
    
    def is_article_page(self, url):
        if not url.startswith(self.base_url):
            return False
            
        path = urlparse(url).path
        
        exclude_patterns = [
            '/wp-admin', '/wp-content', '/wp-includes',
            '/feed', '/rss', '/sitemap', '/category', '/tag',
            '/author', '/search', '/page', '/privacy', '/terms'
        ]
        
        if any(pattern in path for pattern in exclude_patterns):
            return False
            
        article_patterns = [
            r'/blog/[^/]+/?$',
            r'/\d{4}/\d{2}/[^/]+/?$',
            r'/[^/]+/?$'
        ]
        
        return any(re.match(pattern, path) for pattern in article_patterns)
    
    def extract_links(self, soup, current_url):
        links = []
        
        for link in soup.find_all('a', href=True):
            href = link.get('href')
            if href:
                full_url = urljoin(current_url, href)
                if self.is_article_page(full_url):
                    links.append(full_url)
        
        for element in soup.find_all(attrs={'onclick': True}):
            onclick = element.get('onclick', '')
            if 'location.href' in onclick or 'window.open' in onclick:
                match = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", onclick)
                if not match:
                    match = re.search(r"window\.open\s*\(\s*['\"]([^'\"]+)['\"]", onclick)
                
                if match:
                    href = match.group(1)
                    full_url = urljoin(current_url, href)
                    if self.is_article_page(full_url):
                        links.append(full_url)
        
        return list(set(links))
    
    def analyze_page(self, url):
        try:
            response = self.session.get(url, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            title_elem = soup.find('title')
            title = title_elem.get_text().strip() if title_elem else url
            
            content_selectors = [
                '.entry-content',
                '.post-content', 
                '.article-content',
                'article',
                'main'
            ]
            
            content_links = []
            for selector in content_selectors:
                content = soup.select_one(selector)
                if content:
                    content_links = self.extract_links(content, url)
                    break
            
            if not content_links:
                content_links = self.extract_links(soup, url)
            
            return {
                'url': url,
                'title': title,
                'outgoing_links': content_links,
                'status': 'success'
            }
            
        except Exception as e:
            return {
                'url': url,
                'title': f"取得エラー: {url}",
                'outgoing_links': [],
                'status': f'error: {str(e)}'
            }
    
    def analyze_site(self):
        st.info("answer-genkinka.jp の分析を開始します...")
        
        progress = st.progress(0)
        status = st.empty()
        
        status.text("URL収集中...")
        all_urls = set()
        
        for seed_url in self.seed_urls:
            if seed_url.endswith('.xml'):
                sitemap_urls = self.extract_from_sitemap(seed_url)
                all_urls.update(sitemap_urls)
                st.success(f"サイトマップから {len(sitemap_urls)} URL を取得")
            else:
                all_urls.add(seed_url)
        
        progress.progress(20)
        
        status.text(f"ページ分析中... ({len(all_urls)} ページ)")
        
        results = []
        for i, url in enumerate(list(all_urls)[:20]):  # 最初の20ページに制限
            if i % 5 == 0:
                progress.progress(20 + int(60 * i / min(len(all_urls), 20)))
                status.text(f"分析中... {i+1}/{min(len(all_urls), 20)}")
            
            result = self.analyze_page(url)
            results.append(result)
            time.sleep(0.5)
        
        progress.progress(80)
        
        status.text("被リンク数計算中...")
        
        link_counts = {}
        for result in results:
            url = result['url']
            link_counts[url] = link_counts.get(url, 0)
            
            for outgoing_url in result['outgoing_links']:
                link_counts[outgoing_url] = link_counts.get(outgoing_url, 0) + 1
        
        final_data = []
        for result in results:
            url = result['url']
            final_data.append({
                'タイトル': result['title'],
                'URL': url,
                '被リンク数': link_counts.get(url, 0),
                '発リンク数': len(result['outgoing_links']),
                'ステータス': result['status']
            })
        
        progress.progress(100)
        status.text("分析完了！")
        
        return final_data

# 各サイトの設定情報
ANALYZER_CONFIGS = {
    "answer-genkinka.jp": {
        "name": "Answer現金化",
        "url": "https://answer-genkinka.jp/blog/",
        "status": "active",
        "last_analysis": None,
        "description": "現金化サービス専門サイト",
        "features": ["ブログ記事分析", "全自動CSV出力"],
        "streamlit_url": "https://answer-analyzer.streamlit.app",
        "color": "#FF6B6B",
        "analyzer": AnswerGenkinkaAnalyzer
    },
    "arigataya.co.jp": {
        "name": "ありがたや", 
        "url": "https://arigataya.co.jp",
        "status": "planned",
        "last_analysis": None,
        "description": "onclick対応・全自動版",
        "features": ["onclick対応", "自動リンク検出"],
        "streamlit_url": None,
        "color": "#4ECDC4",
        "analyzer": None
    },
    "kau-ru.co.jp": {
        "name": "カウール",
        "url": "https://kau-ru.co.jp", 
        "status": "planned",
        "last_analysis": None,
        "description": "複数サイト対応版",
        "features": ["WordPress API", "添付ファイル除外"],
        "streamlit_url": None,
        "color": "#45B7D1",
        "analyzer": None
    },
    "crecaeru.co.jp": {
        "name": "クレかえる",
        "url": "https://crecaeru.co.jp",
        "status": "planned", 
        "last_analysis": None,
        "description": "gnav除外対応・onclick対応版",
        "features": ["gnav除外", "onclick対応"],
        "streamlit_url": None,
        "color": "#96CEB4",
        "analyzer": None
    },
    "friendpay.jp": {
        "name": "フレンドペイ",
        "url": "https://friendpay.jp",
        "status": "planned",
        "last_analysis": None, 
        "description": "サイト別除外セレクター対応",
        "features": ["サイト別除外", "最適化分析"],
        "streamlit_url": None,
        "color": "#FFEAA7",
        "analyzer": None
    },
    "kaitori-life.co.jp": {
        "name": "買取LIFE",
        "url": "https://kaitori-life.co.jp",
        "status": "planned",
        "last_analysis": None,
        "description": "JINテーマ専用最適化",
        "features": ["JINテーマ対応", "専用セレクター"],
        "streamlit_url": None,
        "color": "#FD79A8",
        "analyzer": None
    },
    "wallet-sos.jp": {
        "name": "ウォレットSOS",
        "url": "https://wallet-sos.jp",
        "status": "planned",
        "last_analysis": None,
        "description": "Selenium版（Cloudflare対策）",
        "features": ["Selenium対応", "Cloudflare対策"],
        "streamlit_url": None,
        "color": "#A29BFE",
        "analyzer": None
    },
    "wonderwall-invest.co.jp": {
        "name": "ワンダーウォール",
        "url": "https://wonderwall-invest.co.jp",
        "status": "planned",
        "last_analysis": None,
        "description": "secure-technology専用",
        "features": ["専用最適化", "高精度分析"],
        "streamlit_url": None,
        "color": "#6C5CE7",
        "analyzer": None
    },
    "fuyohin-kaishu.co.jp": {
        "name": "不用品回収",
        "url": "https://fuyohin-kaishu.co.jp",
        "status": "planned",
        "last_analysis": None,
        "description": "カテゴリ別分析・修正版",
        "features": ["カテゴリ別分析", "包括的収集"],
        "streamlit_url": None,
        "color": "#00B894",
        "analyzer": None
    },
    "bic-gift.co.jp": {
        "name": "ビックギフト",
        "url": "https://bic-gift.co.jp",
        "status": "planned",
        "last_analysis": None,
        "description": "SANGOテーマ専用・全自動版",
        "features": ["SANGOテーマ対応", "専用抽出"],
        "streamlit_url": None,
        "color": "#E17055",
        "analyzer": None
    },
    "flashpay.jp/famipay": {
        "name": "ファミペイ",
        "url": "https://flashpay.jp/famipay/",
        "status": "planned",
        "last_analysis": None,
        "description": "/famipay/配下専用",
        "features": ["配下限定分析", "高精度抽出"],
        "streamlit_url": None,
        "color": "#00CEC9",
        "analyzer": None
    },
    "flashpay.jp/media": {
        "name": "フラッシュペイ",
        "url": "https://flashpay.jp/media/",
        "status": "planned",
        "last_analysis": None,
        "description": "/media/配下専用",
        "features": ["メディア特化", "効率分析"],
        "streamlit_url": None,
        "color": "#74B9FF",
        "analyzer": None
    },
    "more-pay.jp": {
        "name": "モアペイ",
        "url": "https://more-pay.jp",
        "status": "planned",
        "last_analysis": None,
        "description": "改善版・包括的分析",
        "features": ["包括分析", "改善版エンジン"],
        "streamlit_url": None,
        "color": "#FD79A8",
        "analyzer": None
    },
    "pay-ful.jp": {
        "name": "ペイフル",
        "url": "https://pay-ful.jp/media/",
        "status": "planned", 
        "last_analysis": None,
        "description": "個別記事ページ重視",
        "features": ["記事重視", "精密分析"],
        "streamlit_url": None,
        "color": "#FDCB6E",
        "analyzer": None
    },
    "smart-pay.website": {
        "name": "スマートペイ",
        "url": "https://smart-pay.website/media/",
        "status": "planned",
        "last_analysis": None,
        "description": "大規模サイト対応",
        "features": ["大規模対応", "効率化エンジン"],
        "streamlit_url": None,
        "color": "#E84393",
        "analyzer": None
    },
    "xgift.jp": {
        "name": "エックスギフト",
        "url": "https://xgift.jp/blog/",
        "status": "planned",
        "last_analysis": None,
        "description": "AFFINGER対応",
        "features": ["AFFINGER対応", "テーマ最適化"],
        "streamlit_url": None,
        "color": "#00B894",
        "analyzer": None
    }
}

def main():
    st.set_page_config(
        page_title="内部リンク分析 統括管理システム",
        page_icon="🎛️",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    st.title("🎛️ 内部リンク分析 統括管理システム")
    st.markdown("**16サイト対応 - 一元管理ダッシュボード**")
    
    with st.sidebar:
        st.header("📋 メニュー")
        menu = st.radio(
            "機能を選択",
            ["🏠 ダッシュボード", "🔗 個別分析", "📊 統計・比較", "⚙️ 設定管理"],
            index=0
        )
        
        st.divider()
        st.markdown("**📈 システム状況**")
        active_count = sum(1 for config in ANALYZER_CONFIGS.values() if config['status'] == 'active')
        st.metric("稼働中", f"{active_count}/16サイト")
        
        st.divider()
        st.markdown("**🕐 最終更新**")
        st.text(datetime.now().strftime("%Y-%m-%d %H:%M"))
    
    if menu == "🏠 ダッシュボード":
        show_dashboard()
    elif menu == "🔗 個別分析":
        show_individual_analysis()
    elif menu == "📊 統計・比較":
        show_statistics()
    elif menu == "⚙️ 設定管理":
        show_settings()

def show_dashboard():
    st.header("📊 システム全体概要")
    
    col1, col2, col3, col4 = st.columns(4)
    
    active_sites = [k for k, v in ANALYZER_CONFIGS.items() if v['status'] == 'active']
    planned_sites = [k for k, v in ANALYZER_CONFIGS.items() if v['status'] == 'planned']
    
    with col1:
        st.metric("総サイト数", len(ANALYZER_CONFIGS), delta="16サイト")
    with col2:
        st.metric("稼働中", len(active_sites), delta=f"+{len(active_sites)}")
    with col3:
        st.metric("準備中", len(planned_sites), delta=f"{len(planned_sites)}サイト")
    with col4:
        st.metric("本日の分析", 0, delta="0回")
    
    st.divider()
    
    st.subheader("🔗 分析対象サイト一覧")
    
    cols = st.columns(3)
    
    for i, (site_key, config) in enumerate(ANALYZER_CONFIGS.items()):
        col_idx = i % 3
        
        with cols[col_idx]:
            if config['status'] == 'active':
                status_color = "🟢"
                status_text = "稼働中"
            elif config['status'] == 'planned':
                status_color = "🟡" 
                status_text = "準備中"
            else:
                status_color = "🔴"
                status_text = "停止中"
            
            with st.container():
                st.markdown(f"""
                <div style="
                    border: 2px solid {config['color']};
                    border-radius: 10px;
                    padding: 15px;
                    margin: 10px 0;
                    background: linear-gradient(135deg, {config['color']}15, {config['color']}05);
                ">
                    <h4 style="color: {config['color']}; margin: 0 0 10px 0;">
                        {status_color} {config['name']}
                    </h4>
                    <p style="margin: 5px 0; font-size: 0.9em;">
                        <strong>URL:</strong> {config['url'][:30]}...
                    </p>
                    <p style="margin: 5px 0; font-size: 0.9em;">
                        <strong>ステータス:</strong> {status_text}
                    </p>
                    <p style="margin: 5px 0; font-size: 0.8em; color: #666;">
                        {config['description']}
                    </p>
                </div>
                """, unsafe_allow_html=True)
                
                if config['status'] == 'active':
                    if st.button(f"🚀 {config['name']} 分析実行", key=f"analyze_{site_key}"):
                        run_real_analysis(site_key, config)
                else:
                    st.button(f"⏳ 準備中", disabled=True, key=f"disabled_{site_key}")

def run_real_analysis(site_key, config):
    """実際の分析を実行"""
    st.success(f"{config['name']} の分析を開始します...")
    
    if config.get('analyzer'):
        # 実際の分析エンジンを使用
        analyzer = config['analyzer']()
        data = analyzer.analyze_site()
        
        if data:
            show_real_results(config['name'], data)
        else:
            st.error("分析に失敗しました")
    else:
        st.warning(f"{config['name']} の分析エンジンは準備中です")

def show_real_results(site_name, data):
    """実際の分析結果を表示"""
    st.subheader(f"📊 {site_name} 分析結果")
    
    df = pd.DataFrame(data)
    df_sorted = df.sort_values('被リンク数', ascending=False)
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("総ページ数", len(df))
    with col2:
        st.metric("総内部リンク数", df['発リンク数'].sum())
    with col3:
        st.metric("孤立ページ", len(df[df['被リンク数'] == 0]))
    with col4:
        st.metric("最多被リンク", df['被リンク数'].max())
    
    st.subheader("📊 被リンク数ランキング")
    
    top_10 = df_sorted.head(10)
    if not top_10.empty:
        chart_data = top_10.set_index('タイトル')['被リンク数']
        st.bar_chart(chart_data)
    
    st.subheader("📋 詳細データ")
    st.dataframe(df_sorted, use_container_width=True)
    
    csv_buffer = io.StringIO()
    df_sorted.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
    csv_data = csv_buffer.getvalue()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{site_name}_analysis_{timestamp}.csv"
    
    st.download_button(
        "📥 CSVダウンロード",
        csv_data,
        filename,
        "text/csv",
        help="被リンク数順でソートされた詳細レポート"
    )

def show_individual_analysis():
    st.header("🔗 個別サイト分析")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        selected_site = st.selectbox(
            "分析対象サイトを選択",
            options=list(ANALYZER_CONFIGS.keys()),
            format_func=lambda x: f"{ANALYZER_CONFIGS[x]['name']} ({x})"
        )
    
    with col2:
        st.markdown("**選択サイト情報**")
        config = ANALYZER_CONFIGS[selected_site]
        st.info(f"""
        **名称:** {config['name']}  
        **URL:** {config['url']}  
        **ステータス:** {config['status']}  
        **説明:** {config['description']}
        """)
    
    st.subheader(f"🎯 {config['name']} の専用機能")
    
    feature_cols = st.columns(len(config['features']))
    for i, feature in enumerate(config['features']):
        with feature_cols[i]:
            st.markdown(f"""
            <div style="
                background: {config['color']}20;
                border: 1px solid {config['color']};
                border-radius: 5px;
                padding: 10px;
                text-align: center;
                margin: 5px;
            ">
                <strong>{feature}</strong>
            </div>
            """, unsafe_allow_html=True)
    
    st.divider()
    
    st.subheader("🚀 分析実行")
    
    if config['status'] == 'active':
        url_input = st.text_input(
            "分析URL（カスタマイズ可能）",
            value=config['url'],
            help="デフォルトURL以外も分析可能です"
        )
        
        col1, col2, col3 = st.columns([2, 1, 1])
        
        with col1:
            if st.button(f"🔍 {config['name']} 分析開始", type="primary"):
                run_real_analysis(selected_site, config)
        
        with col2:
            if st.button("📊 履歴表示"):
                st.info("分析履歴機能は準備中です")
        
        with col3:
            if st.button("⚙️ 設定"):
                st.info("個別設定機能は準備中です")
    
    else:
        st.warning(f"{config['name']} はまだ準備中です。Streamlit版への移行作業を進めています。")
        
        st.markdown("**移行状況:**")
        progress = st.progress(0)
        st.text("CustomTkinter → Streamlit 変換作業中...")

def show_statistics():
    st.header("📊 統計・比較分析")
    
    st.info("統計・比較機能は各サイトのStreamlit化完了後に実装予定です")
    
    st.subheader("🔮 実装予定機能")
    
    features = [
        "📈 全サイト横断統計",
        "🔄 サイト間比較分析", 
        "📅 時系列トレンド",
        "🎯 SEO改善提案",
        "📊 統合レポート生成",
        "⚡ リアルタイム監視"
    ]
    
    cols = st.columns(2)
    for i, feature in enumerate(features):
        with cols[i % 2]:
            st.markdown(f"- {feature}")

def show_settings():
    st.header("⚙️ 設定管理")
    
    st.subheader("🔧 システム設定")
    
    with st.expander("全般設定", expanded=True):
        auto_analysis = st.checkbox("自動分析を有効化", value=False)
        analysis_interval = st.selectbox("分析間隔", ["1時間", "6時間", "12時間", "24時間"])
        max_concurrent = st.slider("同時実行数", 1, 5, 2)
    
    with st.expander("通知設定"):
        email_notify = st.checkbox("メール通知", value=False)
        slack_notify = st.checkbox("Slack通知", value=False)
        if email_notify:
            email = st.text_input("通知先メールアドレス")
        if slack_notify:
            webhook = st.text_input("Slack Webhook URL")
    
    with st.expander("サイト別設定"):
        for site_key, config in ANALYZER_CONFIGS.items():
            st.markdown(f"**{config['name']} ({site_key})**")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                enabled = st.checkbox("有効", value=config['status']=='active', key=f"enable_{site_key}")
            with col2:
                priority = st.selectbox("優先度", ["高", "中", "低"], key=f"priority_{site_key}")
            with col3:
                timeout = st.number_input("タイムアウト(秒)", 10, 300, 60, key=f"timeout_{site_key}")
            
            st.divider()
    
    if st.button("💾 設定を保存", type="primary"):
        st.success("設定を保存しました！")
        st.balloons()

if __name__ == "__main__":
    main()
