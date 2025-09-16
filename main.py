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
        
        max_pages = 50 # 収集ページ数の上限（テスト用）

        # フェーズ1: ページ収集
        while to_visit and len(self.pages) < max_pages:
            url = to_visit.pop(0)
            if url in visited: continue
            
            try:
                if progress_callback:
                    progress_callback(f"収集中 ({len(self.pages)}/{max_pages}): {url}", len(self.pages) / max_pages)
                    
                response = session.get(url, timeout=10)
                visited.add(url)
                if response.status_code != 200: continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                robots = soup.find('meta', attrs={'name': 'robots'})
                if robots and 'noindex' in robots.get('content', '').lower():
                    continue
                
                if '/blog' in url:
                    page_links = self.extract_links(soup, url)
                    new_links = [l for l in page_links if l not in visited and l not in to_visit]
                    to_visit.extend(new_links)
                    continue
                
                if self.is_article_page(url):
                    title = soup.find('h1')
                    title = title.get_text(strip=True) if title else url
                    title = re.sub(r'\s*[|\-]\s*.*(answer-genkinka|アンサー).*$', '', title, flags=re.IGNORECASE)
                    
                    self.pages[url] = {'title': title, 'outbound_links': []}
                    page_links = self.extract_links(soup, url)
                    new_links = [l for l in page_links if l not in visited and l not in to_visit]
                    to_visit.extend(new_links)
                
                time.sleep(0.1)
                
            except Exception:
                continue

        # フェーズ2: リンク関係構築
        if progress_callback:
            progress_callback("リンク関係構築中...", 0.9)
            
        processed = set()
        for i, url in enumerate(list(self.pages.keys())):
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

### ▼▼▼ 変更点1: ArigatayaAnalyzerクラスの追加 ▼▼▼
class ArigatayaAnalyzer:
    def __init__(self):
        self.pages = {}
        self.links = []
        self.detailed_links = []
        self.base_url = None
        self.domain = None

    def normalize_url(self, url):
        try:
            parsed = urlparse(url)
            path = parsed.path.split('?')[0].split('#')[0]
            netloc = parsed.netloc.replace('www.', '')
            path = path.rstrip('/')
            if not path:
                return f"https://{netloc}"
            return f"https://{netloc}{path}"
        except Exception:
            return url

    def is_internal(self, url):
        return urlparse(url).netloc.replace('www.', '') == self.domain

    def extract_from_sitemap(self, url, visited_sitemaps):
        if url in visited_sitemaps:
            return set()
        visited_sitemaps.add(url)
        urls = set()
        try:
            res = requests.get(url, timeout=10)
            res.raise_for_status()
            soup = BeautifulSoup(res.content, 'xml')
            if soup.find('sitemapindex'):
                for loc in soup.find_all('loc'):
                    urls.update(self.extract_from_sitemap(loc.text.strip(), visited_sitemaps))
            else:
                for loc in soup.find_all('loc'):
                    urls.add(self.normalize_url(loc.text.strip()))
        except Exception as e:
            print(f"サイトマップエラー ({url}): {e}")
        return urls

    def generate_seed_urls(self):
        sitemap_root = urljoin(self.base_url, '/sitemap.xml')
        sitemap_urls = self.extract_from_sitemap(sitemap_root, set())
        print(f"サイトマップから {len(sitemap_urls)} 個のURLを取得しました。")
        seed_urls = set([self.normalize_url(self.base_url)]) | sitemap_urls
        return list(seed_urls)

    def is_content(self, url):
        try:
            path = urlparse(url).path.lower()
            exclude_patterns = [
                r'\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip)$', r'/wp-admin', r'/wp-json', r'/wp-includes',
                r'/wp-content/plugins', r'/feed', r'/comments/feed', r'/trackback', r'sitemap\.xml',
                r'\/go\/', r'\/g\/', r'\/tag\/', r'\/author\/', r'\/privacy',
            ]
            if any(re.search(pattern, path) for pattern in exclude_patterns):
                return False
            clean_path = path.strip('/')
            if ('/' not in clean_path and clean_path) or path == '/' or not path or path.startswith('/category/'):
                return True
            return False
        except Exception:
            return False

    def is_noindex_page(self, soup):
        meta_robots = soup.find('meta', attrs={'name': 'robots'})
        if meta_robots and 'noindex' in meta_robots.get('content', '').lower():
            return True
        return False

    def extract_links(self, soup, base_url):
        links = []
        content_area = soup.select_one('.post_content, .entry-content, main, article') or soup
        for a in content_area.find_all('a', href=True):
            href = a.get('href')
            if href and not href.startswith(('#', 'javascript:', 'mailto:')):
                full_url = urljoin(base_url, href)
                if self.is_internal(full_url):
                    links.append({'url': self.normalize_url(full_url), 'anchor_text': a.get_text(strip=True)[:100]})
        for tag in content_area.find_all(onclick=True):
            onclick_val = tag.get('onclick')
            match = re.search(r"location\.href='([^']+)'", onclick_val)
            if match:
                href = match.group(1)
                full_url = urljoin(base_url, href)
                if self.is_internal(full_url):
                    links.append({'url': self.normalize_url(full_url), 'anchor_text': tag.get_text(strip=True)[:100]})
        return links

    def analyze(self, start_url, progress_callback=None):
        self.base_url = start_url
        self.domain = urlparse(start_url).netloc.replace('www.', '')
        self.pages, self.links, self.detailed_links = {}, [], []
        
        if progress_callback:
            progress_callback("サイトマップからURLを収集中...", 0.0)
        
        to_visit = self.generate_seed_urls()
        visited, processed_links = set(), set()
        
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
        
        max_pages = 500
        queue = list(dict.fromkeys(to_visit))
        
        while queue and len(self.pages) < max_pages:
            url = queue.pop(0)
            if url in visited or not self.is_content(url):
                visited.add(url)
                continue

            try:
                if progress_callback:
                    progress = len(self.pages) / max_pages
                    progress_callback(f"分析中 ({len(self.pages)}/{max_pages}): {url}", progress)
                
                response = session.get(url, timeout=10)
                visited.add(url)
                if response.status_code != 200: continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                if self.is_noindex_page(soup): continue

                title = (soup.title.string.strip() if soup.title and soup.title.string else url)
                title = re.sub(r'\s*[|\-]\s*.*(arigataya|ありがたや).*$', '', title, flags=re.IGNORECASE).strip()
                
                if url not in self.pages:
                    self.pages[url] = {'title': title, 'outbound_links': [], 'inbound_links': 0}

                extracted_links = self.extract_links(soup, url)
                for link_data in extracted_links:
                    target_url = link_data['url']
                    if self.is_content(target_url):
                        link_key = (url, target_url)
                        if link_key not in processed_links:
                            self.pages[url]['outbound_links'].append(target_url)
                            self.detailed_links.append({'source_url': url, 'source_title': title, 'target_url': target_url, 'anchor_text': link_data['anchor_text']})
                            self.links.append(link_key)
                            processed_links.add(link_key)
                        if target_url not in visited and target_url not in queue:
                            queue.append(target_url)
                time.sleep(0.1)

            except Exception as e:
                print(f"エラー ({url}): {e}")
                continue

        if progress_callback: progress_callback("被リンク数を計算中...", 0.95)
        for page_url in self.pages: self.pages[page_url]['inbound_links'] = 0
        for _, target in self.links:
            if target in self.pages: self.pages[target]['inbound_links'] += 1
        
        return self.pages, self.links, self.detailed_links

# その他サイト用のダミー分析クラス
class GenericAnalyzer:
    def __init__(self):
        pass

    def analyze(self, start_url, progress_callback=None):
        if progress_callback:
            progress_callback(f"このサイトの分析エンジンは準備中です...", 0)
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
    ### ▼▼▼ 変更点2: ANALYZER_CONFIGSの更新 ▼▼▼
    "arigataya.co.jp": {
        "name": "ありがたや", 
        "url": "https://arigataya.co.jp",
        "status": "active", # "planned" から "active" に変更
        "description": "onclick対応・全自動版",
        "features": ["onclick対応", "自動リンク検出"],
        "color": "#4ECDC4",
        "analyzer_class": ArigatayaAnalyzer # GenericAnalyzer から ArigatayaAnalyzer に変更
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
    
    def progress_callback(message, progress):
        status_placeholder.text(message)
        progress_bar.progress(progress)
    
    # 分析実行
    analyzer_class = config.get("analyzer_class", GenericAnalyzer)
    analyzer = analyzer_class()
    
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
        
        # 詳細テーブル
        st.subheader("詳細データ")
        st.dataframe(df_sorted, use_container_width=True)
        
        # CSVダウンロード
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
    
    # セッションステートの初期化
    if 'active_analysis' not in st.session_state:
        st.session_state.active_analysis = None
    if 'analysis_results' not in st.session_state:
        st.session_state.analysis_results = {}
    
    # サイドバー
    with st.sidebar:
        st.header("📋 メニュー")
        menu_options = ["🏠 ダッシュボード", "🔗 個別分析", "📊 統計・比較", "⚙️ 設定管理"]
        menu = st.radio("機能を選択", menu_options, index=0)
        
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
    st.header("📊 システム全体概要")
    
    active_sites = [k for k, v in ANALYZER_CONFIGS.items() if v['status'] == 'active']
    planned_sites = [k for k, v in ANALYZER_CONFIGS.items() if v['status'] == 'planned']
    
    col1, col2, col3, col4 = st.columns(4)
    with col1: st.metric("総サイト数", len(ANALYZER_CONFIGS))
    with col2: st.metric("稼働中", len(active_sites))
    with col3: st.metric("準備中", len(planned_sites))
    with col4: st.metric("本日の分析", 0)
    
    st.divider()
    st.subheader("🔗 分析対象サイト一覧")
    
    cols = st.columns(3)
    sorted_sites = sorted(ANALYZER_CONFIGS.items(), key=lambda x: (x[1]['status'] != 'active', x[0]))

    for i, (site_key, config) in enumerate(sorted_sites):
        with cols[i % 3]:
            status_color = "🟢" if config['status'] == 'active' else "🟡"
            status_text = "稼働中" if config['status'] == 'active' else "準備中"
            
            with st.container(border=True):
                st.markdown(f"""
                <h4 style="color: {config['color']}; margin: 0 0 10px 0;">
                    {status_color} {config['name']}
                </h4>
                <p style="margin: 5px 0; font-size: 0.9em;">
                    <strong>URL:</strong> <a href="{config['url']}" target="_blank">{config['url'][:30]}...</a>
                </p>
                <p style="margin: 5px 0; font-size: 0.9em;">
                    <strong>ステータス:</strong> {status_text}
                </p>
                <p style="margin: 5px 0; font-size: 0.8em; color: #666;">
                    {config['description']}
                </p>
                """, unsafe_allow_html=True)
                
                if st.button(f"🚀 分析実行", key=f"dash_analyze_{site_key}", use_container_width=True):
                    st.session_state.active_analysis = site_key
                    st.rerun()

    # 分析がトリガーされたら実行
    if st.session_state.active_analysis:
        site_key = st.session_state.active_analysis
        config = ANALYZER_CONFIGS[site_key]
        st.session_state.active_analysis = None # トリガーをリセット
        
        with st.spinner(f"{config['name']}の分析を実行中..."):
            run_analysis(site_key, config)

def show_individual_analysis():
    st.header("🔗 個別サイト分析")
    
    selected_site = st.selectbox(
        "分析対象サイトを選択",
        options=list(ANALYZER_CONFIGS.keys()),
        format_func=lambda x: f"{ANALYZER_CONFIGS[x]['name']} ({x})"
    )
    
    config = ANALYZER_CONFIGS[selected_site]
    
    with st.container(border=True):
        st.subheader(f"🎯 {config['name']} の設定")
        st.write(f"**URL:** {config['url']}")
        st.write(f"**ステータス:** {config['status']}")
        st.write(f"**説明:** {config['description']}")
        
        st.write("**専用機能:**")
        feature_cols = st.columns(len(config['features']))
        for i, feature in enumerate(config['features']):
            with feature_cols[i]:
                st.info(feature)

    st.divider()
    
    if st.button(f"🔍 {config['name']} 分析開始", type="primary", use_container_width=True):
        with st.spinner(f"{config['name']}の分析を実行中..."):
            run_analysis(selected_site, config)

def show_statistics():
    st.header("📊 統計・比較分析")
    st.info("この機能は現在準備中です。")

def show_settings():
    st.header("⚙️ 設定管理")
    st.info("この機能は現在準備中です。")

if __name__ == "__main__":
    main()
