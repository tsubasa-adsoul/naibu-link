import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import time
import re
import csv
import io
from datetime import datetime
import pandas as pd

# Answer現金化分析クラス
class AnswerAnalyzer:
    def __init__(self):
        self.pages = {}
        self.links = []
        self.detailed_links = []

    def normalize_url(self, url):
        if not url: return ""
        try:
            parsed = urlparse(url)
            return f"https://{parsed.netloc.replace('www.', '')}{parsed.path.rstrip('/')}"
        except:
            return url

    def is_article_page(self, url):
        path = urlparse(self.normalize_url(url)).path.lower()
        exclude_words = ['/site/', '/blog/', '/page/', '/feed', '/wp-', '.']
        if any(word in path for word in exclude_words):
            return False
        
        if path.startswith('/') and len(path) > 1:
            clean_path = path[1:].rstrip('/')
            if clean_path and '/' not in clean_path:
                return True
        return False

    def is_crawlable(self, url):
        path = urlparse(self.normalize_url(url)).path.lower()
        exclude_words = ['/site/', '/wp-admin', '/feed', '.jpg', '.png', '.css', '.js']
        if any(word in path for word in exclude_words):
            return False
        return (path.startswith('/blog') or self.is_article_page(url))

    def extract_links(self, soup, current_url):
        links = []
        for a in soup.find_all('a', href=True):
            href = a.get('href', '').strip()
            if href and not href.startswith('#'):
                absolute = urljoin(current_url, href)
                if 'answer-genkinka.jp' in absolute and self.is_crawlable(absolute):
                    links.append(self.normalize_url(absolute))
        return list(set(links))

    def extract_content_links(self, soup, current_url):
        content = soup.select_one('.entry-content, .post-content, main, article')
        if not content:
            return []
        
        links = []
        for a in content.find_all('a', href=True):
            href = a.get('href', '').strip()
            text = a.get_text(strip=True) or ''
            if href and not href.startswith('#') and text:
                absolute = urljoin(current_url, href)
                if 'answer-genkinka.jp' in absolute and self.is_article_page(absolute):
                    links.append({'url': self.normalize_url(absolute), 'anchor_text': text[:100]})
        return links

    def analyze(self, start_url, progress_callback=None):
        self.pages, self.links, self.detailed_links = {}, [], []
        visited, to_visit = set(), [self.normalize_url(start_url)]
        to_visit.append('https://answer-genkinka.jp/blog/page/2/')

        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})

        # フェーズ1: ページ収集
        while to_visit and len(self.pages) < 50:
            url = to_visit.pop(0)
            if url in visited: continue
            
            try:
                if progress_callback:
                    progress_callback(f"収集中: {url}")
                    
                response = session.get(url, timeout=10)
                if response.status_code != 200: continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                robots = soup.find('meta', attrs={'name': 'robots'})
                if robots and 'noindex' in robots.get('content', '').lower():
                    continue
                
                if '/blog' in url:
                    page_links = self.extract_links(soup, url)
                    new_links = [l for l in page_links if l not in visited and l not in to_visit]
                    to_visit.extend(new_links)
                    visited.add(url)
                    continue
                
                if self.is_article_page(url):
                    title = soup.find('h1')
                    title = title.get_text(strip=True) if title else url
                    title = re.sub(r'\s*[|\-]\s*.*(answer-genkinka|アンサー).*$', '', title, flags=re.IGNORECASE)
                    
                    self.pages[url] = {'title': title, 'outbound_links': []}
                    page_links = self.extract_links(soup, url)
                    new_links = [l for l in page_links if l not in visited and l not in to_visit]
                    to_visit.extend(new_links)
                
                visited.add(url)
                time.sleep(0.1)
                
            except Exception:
                continue

        # フェーズ2: リンク関係構築
        if progress_callback:
            progress_callback("リンク関係構築中...")
            
        processed = set()
        for url in list(self.pages.keys()):
            try:
                response = session.get(url, timeout=10)
                if response.status_code != 200: continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                content_links = self.extract_content_links(soup, url)
                
                for link_data in content_links:
                    target = link_data['url']
                    if target in self.pages and target != url:
                        link_key = (url, target)
                        if link_key not in processed:
                            processed.add(link_key)
                            self.links.append((url, target))
                            self.pages[url]['outbound_links'].append(target)
                            self.detailed_links.append({
                                'source_url': url, 'source_title': self.pages[url]['title'],
                                'target_url': target, 'anchor_text': link_data['anchor_text']
                            })
            except Exception:
                continue

        # 被リンク数計算
        for url in self.pages:
            self.pages[url]['inbound_links'] = sum(1 for s, t in self.links if t == url)

        return self.pages, self.links, self.detailed_links

# その他サイト用のダミー分析クラス（後で実装）
class GenericAnalyzer:
    def __init__(self, site_name, base_url):
        self.site_name = site_name
        self.base_url = base_url

    def analyze(self, start_url, progress_callback=None):
        if progress_callback:
            progress_callback(f"{self.site_name} の分析は準備中です...")
        return {}, [], []

# サイト設定
ANALYZER_CONFIGS = {
    "answer-genkinka.jp": {
        "name": "Answer現金化",
        "url": "https://answer-genkinka.jp/blog/",
        "status": "active",
        "description": "現金化サービス専門サイト",
        "features": ["ブログ記事分析", "全自動CSV出力"],
        "color": "#FF6B6B",
        "analyzer_class": AnswerAnalyzer
    },
    "arigataya.co.jp": {
        "name": "ありがたや", 
        "url": "https://arigataya.co.jp",
        "status": "planned",
        "description": "onclick対応・全自動版",
        "features": ["onclick対応", "自動リンク検出"],
        "color": "#4ECDC4",
        "analyzer_class": GenericAnalyzer
    },
    "kau-ru.co.jp": {
        "name": "カウール",
        "url": "https://kau-ru.co.jp", 
        "status": "planned",
        "description": "複数サイト対応版",
        "features": ["WordPress API", "添付ファイル除外"],
        "color": "#45B7D1",
        "analyzer_class": GenericAnalyzer
    },
    "crecaeru.co.jp": {
        "name": "クレかえる",
        "url": "https://crecaeru.co.jp",
        "status": "planned",
        "description": "gnav除外対応・onclick対応版",
        "features": ["gnav除外", "onclick対応"],
        "color": "#96CEB4",
        "analyzer_class": GenericAnalyzer
    },
    "friendpay.jp": {
        "name": "フレンドペイ",
        "url": "https://friendpay.jp",
        "status": "planned",
        "description": "サイト別除外セレクター対応",
        "features": ["サイト別除外", "最適化分析"],
        "color": "#FFEAA7",
        "analyzer_class": GenericAnalyzer
    },
    "kaitori-life.co.jp": {
        "name": "買取LIFE",
        "url": "https://kaitori-life.co.jp",
        "status": "planned",
        "description": "JINテーマ専用最適化",
        "features": ["JINテーマ対応", "専用セレクター"],
        "color": "#FD79A8",
        "analyzer_class": GenericAnalyzer
    },
    "wallet-sos.jp": {
        "name": "ウォレットSOS",
        "url": "https://wallet-sos.jp",
        "status": "planned",
        "description": "Selenium版（Cloudflare対策）",
        "features": ["Selenium対応", "Cloudflare対策"],
        "color": "#A29BFE",
        "analyzer_class": GenericAnalyzer
    },
    "wonderwall-invest.co.jp": {
        "name": "ワンダーウォール",
        "url": "https://wonderwall-invest.co.jp",
        "status": "planned",
        "description": "secure-technology専用",
        "features": ["専用最適化", "高精度分析"],
        "color": "#6C5CE7",
        "analyzer_class": GenericAnalyzer
    },
    "fuyohin-kaishu.co.jp": {
        "name": "不用品回収",
        "url": "https://fuyohin-kaishu.co.jp",
        "status": "planned",
        "description": "カテゴリ別分析・修正版",
        "features": ["カテゴリ別分析", "包括的収集"],
        "color": "#00B894",
        "analyzer_class": GenericAnalyzer
    },
    "bic-gift.co.jp": {
        "name": "ビックギフト",
        "url": "https://bic-gift.co.jp",
        "status": "planned",
        "description": "SANGOテーマ専用・全自動版",
        "features": ["SANGOテーマ対応", "専用抽出"],
        "color": "#E17055",
        "analyzer_class": GenericAnalyzer
    },
    "flashpay.jp/famipay": {
        "name": "ファミペイ",
        "url": "https://flashpay.jp/famipay/",
        "status": "planned",
        "description": "/famipay/配下専用",
        "features": ["配下限定分析", "高精度抽出"],
        "color": "#00CEC9",
        "analyzer_class": GenericAnalyzer
    },
    "flashpay.jp/media": {
        "name": "フラッシュペイ",
        "url": "https://flashpay.jp/media/",
        "status": "planned",
        "description": "/media/配下専用",
        "features": ["メディア特化", "効率分析"],
        "color": "#74B9FF",
        "analyzer_class": GenericAnalyzer
    },
    "more-pay.jp": {
        "name": "モアペイ",
        "url": "https://more-pay.jp",
        "status": "planned",
        "description": "改善版・包括的分析",
        "features": ["包括分析", "改善版エンジン"],
        "color": "#FD79A8",
        "analyzer_class": GenericAnalyzer
    },
    "pay-ful.jp": {
        "name": "ペイフル",
        "url": "https://pay-ful.jp/media/",
        "status": "planned",
        "description": "個別記事ページ重視",
        "features": ["記事重視", "精密分析"],
        "color": "#FDCB6E",
        "analyzer_class": GenericAnalyzer
    },
    "smart-pay.website": {
        "name": "スマートペイ",
        "url": "https://smart-pay.website/media/",
        "status": "planned",
        "description": "大規模サイト対応",
        "features": ["大規模対応", "効率化エンジン"],
        "color": "#E84393",
        "analyzer_class": GenericAnalyzer
    },
    "xgift.jp": {
        "name": "エックスギフト",
        "url": "https://xgift.jp/blog/",
        "status": "planned",
        "description": "AFFINGER対応",
        "features": ["AFFINGER対応", "テーマ最適化"],
        "color": "#00B894",
        "analyzer_class": GenericAnalyzer
    }
}

def create_detailed_csv(pages, detailed_links):
    """詳細CSVデータ作成"""
    csv_data = []
    csv_data.append(['番号', 'ページタイトル', 'URL', '被リンク元タイトル', '被リンク元URL', 'アンカーテキスト'])
    
    targets = {}
    for link in detailed_links:
        target = link['target_url']
        targets.setdefault(target, []).append(link)
    
    sorted_targets = sorted(targets.items(), key=lambda x: len(x[1]), reverse=True)
    
    row = 1
    for target, links_list in sorted_targets:
        title = pages.get(target, {}).get('title', target)
        for link in links_list:
            csv_data.append([row, title, target, link['source_title'], link['source_url'], link['anchor_text']])
            row += 1
    
    for url, info in pages.items():
        if info.get('inbound_links', 0) == 0:
            csv_data.append([row, info['title'], url, '', '', ''])
            row += 1
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(csv_data)
    return output.getvalue()

def run_analysis(site_key, config):
    """分析実行"""
    st.info(f"{config['name']} の分析を開始します...")
    
    status_placeholder = st.empty()
    progress_bar = st.progress(0)
    
    def progress_callback(message):
        status_placeholder.text(message)
    
    # 分析実行
    if config['analyzer_class'] == AnswerAnalyzer:
        analyzer = AnswerAnalyzer()
    else:
        analyzer = GenericAnalyzer(config['name'], config['url'])
    
    pages, links, detailed_links = analyzer.analyze(config['url'], progress_callback)
    
    progress_bar.progress(1.0)
    status_placeholder.text("分析完了!")
    
    if pages:
        # 統計表示
        total = len(pages)
        isolated = sum(1 for p in pages.values() if p.get('inbound_links', 0) == 0)
        popular = sum(1 for p in pages.values() if p.get('inbound_links', 0) >= 5)
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("総ページ数", total)
        with col2:
            st.metric("総リンク数", len(links))
        with col3:
            st.metric("孤立ページ", isolated)
        with col4:
            st.metric("人気ページ", popular)
        
        # 結果表示
        st.subheader(f"📊 {config['name']} 分析結果")
        
        # DataFrameに変換
        results_data = []
        for url, info in pages.items():
            results_data.append({
                'タイトル': info['title'],
                'URL': url,
                '被リンク数': info.get('inbound_links', 0),
                '発リンク数': len(info.get('outbound_links', []))
            })
        
        df = pd.DataFrame(results_data)
        df_sorted = df.sort_values('被リンク数', ascending=False)
        
        # グラフ表示
        if len(df_sorted) > 0:
            st.subheader("被リンク数ランキング（上位10件）")
            top_10 = df_sorted.head(10)
            if not top_10.empty:
                chart_data = top_10.set_index('タイトル')['被リンク数']
                st.bar_chart(chart_data)
        
        # 詳細テーブル（常に表示）
        st.subheader("詳細データ")
        st.dataframe(df_sorted, use_container_width=True)
        
        # CSVダウンロード（詳細データは消えない）
        if detailed_links:
            csv_content = create_detailed_csv(pages, detailed_links)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{config['name']}-{timestamp}.csv"
            
            st.download_button(
                "📥 詳細CSVダウンロード",
                csv_content,
                filename,
                "text/csv",
                help="被リンク数順でソートされた詳細レポート"
            )
        
        st.success("✅ 分析完了!")
    
    else:
        if config['status'] == 'planned':
            st.warning(f"{config['name']} の分析エンジンは準備中です")
        else:
            st.error("❌ データを取得できませんでした")

def main():
    st.set_page_config(
        page_title="内部リンク分析 統括管理システム",
        page_icon="🎛️",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    st.title("🎛️ 内部リンク分析 統括管理システム")
    st.markdown("**16サイト対応 - 一元管理ダッシュボード**")
    
    # サイドバー
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
    
    # メイン画面
    if menu == "🏠 ダッシュボード":
        show_dashboard()
    elif menu == "🔗 個別分析":
        show_individual_analysis()
    elif menu == "📊 統計・比較":
        show_statistics()
    elif menu == "⚙️ 設定管理":
        show_settings()

def show_dashboard():
    """ダッシュボード表示"""
    st.header("📊 システム全体概要")
    
    # 統計情報
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
    
    # サイト一覧カード表示
    st.subheader("🔗 分析対象サイト一覧")
    
    # 3列レイアウトでカード表示
    cols = st.columns(3)
    
    for i, (site_key, config) in enumerate(ANALYZER_CONFIGS.items()):
        col_idx = i % 3
        
        with cols[col_idx]:
            # ステータスに応じた色分け
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
                
                # アクションボタン
                if st.button(f"🚀 {config['name']} 分析実行", key=f"analyze_{site_key}"):
                    run_analysis(site_key, config)
                
                # 保存された結果があれば表示ボタンを追加
                if f'pages_{site_key}' in st.session_state:
                    if st.button(f"📊 {config['name']} 結果表示", key=f"show_{site_key}"):
                        show_analysis_results(site_key)

def show_individual_analysis():
    """個別分析画面"""
    st.header("🔗 個別サイト分析")
    
    # サイト選択
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
    
    # 機能説明
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
    
    # 分析実行セクション
    st.subheader("🚀 分析実行")
    
    url_input = st.text_input(
        "分析URL（カスタマイズ可能）",
        value=config['url'],
        help="デフォルトURL以外も分析可能です"
    )
    
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        if st.button(f"🔍 {config['name']} 分析開始", type="primary"):
            run_analysis(selected_site, config)
    
    with col2:
        # 保存された結果があれば表示ボタンを追加
        if f'pages_{selected_site}' in st.session_state:
            if st.button("📊 結果表示"):
                show_analysis_results(selected_site)
        else:
            if st.button("📊 履歴表示"):
                st.info("分析履歴機能は準備中です")
    
    with col3:
        if st.button("⚙️ 設定"):
            st.info("個別設定機能は準備中です")
    
    # 保存されたデータがあれば自動表示
    if f'pages_{selected_site}' in st.session_state:
        st.divider()
        show_analysis_results(selected_site)

def show_statistics():
    """統計・比較画面"""
    st.header("📊 統計・比較分析")
    
    st.info("統計・比較機能は各サイトのStreamlit化完了後に実装予定です")
    
    # 将来の機能プレビュー
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
    """設定管理画面"""
    st.header("⚙️ 設定管理")
    
    st.subheader("🔧 システム設定")
    
    # 全般設定
    with st.expander("全般設定", expanded=True):
        auto_analysis = st.checkbox("自動分析を有効化", value=False)
        analysis_interval = st.selectbox("分析間隔", ["1時間", "6時間", "12時間", "24時間"])
        max_concurrent = st.slider("同時実行数", 1, 5, 2)
    
    # 通知設定
    with st.expander("通知設定"):
        email_notify = st.checkbox("メール通知", value=False)
        slack_notify = st.checkbox("Slack通知", value=False)
        if email_notify:
            email = st.text_input("通知先メールアドレス")
        if slack_notify:
            webhook = st.text_input("Slack Webhook URL")
    
    # サイト別設定
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
    
    # 保存ボタン
    if st.button("💾 設定を保存", type="primary"):
        st.success("設定を保存しました！")
        st.balloons()

if __name__ == "__main__":
    main()
