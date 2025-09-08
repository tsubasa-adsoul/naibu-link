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
        """サイトマップからURL抽出（元コードの移植）"""
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
        """記事ページ判定（元コードの移植）"""
        if not url.startswith(self.base_url):
            return False
            
        path = urlparse(url).path
        
        # 除外パターン
        exclude_patterns = [
            '/wp-admin', '/wp-content', '/wp-includes',
            '/feed', '/rss', '/sitemap', '/category', '/tag',
            '/author', '/search', '/page', '/privacy', '/terms'
        ]
        
        if any(pattern in path for pattern in exclude_patterns):
            return False
            
        # 記事パターン
        article_patterns = [
            r'/blog/[^/]+/?$',  # /blog/記事スラッグ
            r'/\d{4}/\d{2}/[^/]+/?$',  # /YYYY/MM/記事スラッグ
            r'/[^/]+/?$'  # ルート直下
        ]
        
        return any(re.match(pattern, path) for pattern in article_patterns)
    
    def extract_links(self, soup, current_url):
        """リンク抽出（onclick属性対応・元コードの移植）"""
        links = []
        
        # 通常のaタグ
        for link in soup.find_all('a', href=True):
            href = link.get('href')
            if href:
                full_url = urljoin(current_url, href)
                if self.is_article_page(full_url):
                    links.append(full_url)
        
        # onclick属性対応
        for element in soup.find_all(attrs={'onclick': True}):
            onclick = element.get('onclick', '')
            if 'location.href' in onclick or 'window.open' in onclick:
                # onclick="location.href='URL'" パターン
                match = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", onclick)
                if not match:
                    # onclick="window.open('URL')" パターン
                    match = re.search(r"window\.open\s*\(\s*['\"]([^'\"]+)['\"]", onclick)
                
                if match:
                    href = match.group(1)
                    full_url = urljoin(current_url, href)
                    if self.is_article_page(full_url):
                        links.append(full_url)
        
        return list(set(links))
    
    def analyze_page(self, url):
        """個別ページ分析（元コードの移植）"""
        try:
            response = self.session.get(url, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # タイトル取得
            title_elem = soup.find('title')
            title = title_elem.get_text().strip() if title_elem else url
            
            # 記事コンテンツ内のリンク抽出
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
            
            # コンテンツ内で見つからない場合は全体から抽出
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
    
    def discover_pagination(self, url):
        """ページネーション自動探索（元コードの移植）"""
        discovered_urls = []
        try:
            response = self.session.get(url, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # rel="next" リンク
            next_link = soup.find('link', rel='next')
            if next_link and next_link.get('href'):
                next_url = urljoin(url, next_link.get('href'))
                discovered_urls.append(next_url)
            
            # ページネーション要素
            pagination_selectors = [
                '.pagination a',
                '.page-numbers a',
                '.wp-pagenavi a',
                '.nav-links a'
            ]
            
            for selector in pagination_selectors:
                for link in soup.select(selector):
                    href = link.get('href')
                    if href:
                        full_url = urljoin(url, href)
                        if full_url.startswith(self.base_url):
                            discovered_urls.append(full_url)
            
        except Exception as e:
            st.warning(f"ページネーション探索エラー: {e}")
        
        return list(set(discovered_urls))
    
    def analyze_site(self):
        """サイト全体分析（元コードの移植・メイン処理）"""
        st.info("🚀 answer-genkinka.jp の分析を開始します...")
        
        # ステップ1: URL収集
        progress = st.progress(0)
        status = st.empty()
        
        status.text("URL収集中...")
        all_urls = set()
        
        # シードURLから開始
        for seed_url in self.seed_urls:
            if seed_url.endswith('.xml'):
                sitemap_urls = self.extract_from_sitemap(seed_url)
                all_urls.update(sitemap_urls)
                st.success(f"サイトマップから {len(sitemap_urls)} URL を取得")
            else:
                # ページネーション探索
                pagination_urls = self.discover_pagination(seed_url)
                all_urls.update(pagination_urls)
                all_urls.add(seed_url)
        
        progress.progress(20)
        
        # ステップ2: 各ページを分析
        status.text(f"ページ分析中... ({len(all_urls)} ページ)")
        
        results = []
        for i, url in enumerate(all_urls):
            if i % 10 == 0:
                progress.progress(20 + int(60 * i / len(all_urls)))
                status.text(f"分析中... {i+1}/{len(all_urls)}")
            
            result = self.analyze_page(url)
            results.append(result)
            time.sleep(0.1)  # レート制限
        
        progress.progress(80)
        
        # ステップ3: 被リンク数計算
        status.text("被リンク数計算中...")
        
        link_counts = {}
        for result in results:
            url = result['url']
            link_counts[url] = link_counts.get(url, 0)
            
            for outgoing_url in result['outgoing_links']:
                link_counts[outgoing_url] = link_counts.get(outgoing_url, 0) + 1
        
        # ステップ4: 最終データ構築
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

def main():
    st.set_page_config(
        page_title="Answer現金化 内部リンク分析",
        page_icon="🔗",
        layout="wide"
    )
    
    st.title("🔗 Answer現金化 内部リンク分析")
    st.markdown("**answer-genkinka.jp専用分析ツール（CustomTkinter完全移植版）**")
    
    analyzer = AnswerGenkinkaAnalyzer()
    
    # 分析実行
    if st.button("🚀 分析開始", type="primary"):
        
        # 実際の分析実行
        with st.spinner("分析中..."):
            data = analyzer.analyze_site()
        
        if data:
            # 被リンク数でソート
            df = pd.DataFrame(data)
            df_sorted = df.sort_values('被リンク数', ascending=False)
            
            # 統計表示
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("総ページ数", len(df))
            with col2:
                st.metric("総内部リンク数", df['発リンク数'].sum())
            with col3:
                st.metric("孤立ページ", len(df[df['被リンク数'] == 0]))
            with col4:
                st.metric("最多被リンク", df['被リンク数'].max())
            
            # 被リンク数ランキング
            st.subheader("📊 被リンク数ランキング")
            
            # グラフ表示
            top_10 = df_sorted.head(10)
            if not top_10.empty:
                chart_data = top_10.set_index('タイトル')['被リンク数']
                st.bar_chart(chart_data)
            
            # 詳細テーブル
            st.subheader("📋 詳細データ")
            st.dataframe(df_sorted, use_container_width=True)
            
            # CSV出力
            csv_buffer = io.StringIO()
            df_sorted.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
            csv_data = csv_buffer.getvalue()
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"answer-genkinka_analysis_{timestamp}.csv"
            
            st.download_button(
                "📥 CSVダウンロード",
                csv_data,
                filename,
                "text/csv",
                help="被リンク数順でソートされた詳細レポート"
            )
            
            st.success("✅ 分析完了！")
        
        else:
            st.error("❌ 分析に失敗しました")
    
    # 設定表示
    with st.expander("⚙️ 分析設定"):
        st.markdown("""
        **対象サイト:** answer-genkinka.jp  
        **分析範囲:** /blog/ 配下 + サイトマップ  
        **特殊機能:** onclick属性対応、ページネーション自動探索  
        **出力形式:** CSV（被リンク数順ソート）
        """)

if __name__ == "__main__":
    main()
