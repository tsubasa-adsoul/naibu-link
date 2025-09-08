import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import re
import pandas as pd
from datetime import datetime
import numpy as np

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
        """個別記事ページかどうか判定"""
        path = urlparse(self.normalize_url(url)).path.lower()
        
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

    def is_crawlable(self, url):
        """クロール対象かどうか判定"""
        path = urlparse(self.normalize_url(url)).path.lower()
        
        exclude_words = ['/site/', '/wp-admin', '/feed', '.jpg', '.png', '.css', '.js']
        if any(word in path for word in exclude_words):
            return False
        
        return (path.startswith('/blog') or self.is_article_page(url))

    def extract_links(self, soup, current_url):
        """リンク抽出"""
        links = []
        for a in soup.find_all('a', href=True):
            href = a.get('href', '').strip()
            if href and not href.startswith('#'):
                absolute = urljoin(current_url, href)
                if 'answer-genkinka.jp' in absolute and self.is_crawlable(absolute):
                    links.append(self.normalize_url(absolute))
        return list(set(links))

    def extract_content_links(self, soup, current_url):
        """コンテンツエリアからリンク抽出"""
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

    def analyze_site(self, url, progress_callback=None, status_callback=None):
        """実際のサイト分析処理"""
        try:
            self.pages, self.links, self.detailed_links = {}, [], []
            visited, to_visit = set(), [self.normalize_url(url)]
            
            # ページネーションを追加
            to_visit.append('https://answer-genkinka.jp/blog/page/2/')

            session = requests.Session()
            session.headers.update({'User-Agent': 'Mozilla/5.0'})

            if status_callback:
                status_callback("=== answer-genkinka.jp 分析開始 ===")

            # フェーズ1: ページ収集
            max_pages = 500
            processed_count = 0
            
            while to_visit and len(self.pages) < max_pages:
                url_to_process = to_visit.pop(0)
                if url_to_process in visited: 
                    continue
                
                try:
                    processed_count += 1
                    if status_callback:
                        status_callback(f"処理中 ({processed_count}): {url_to_process}")
                    
                    response = session.get(url_to_process, timeout=10)
                    if response.status_code != 200: 
                        if status_callback:
                            status_callback(f"HTTPエラー {response.status_code}: {url_to_process}")
                        continue
                    
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    # NOINDEXチェック
                    robots = soup.find('meta', attrs={'name': 'robots'})
                    if robots and 'noindex' in robots.get('content', '').lower():
                        if status_callback:
                            status_callback(f"NOINDEXをスキップ: {url_to_process}")
                        continue
                    
                    # 記事一覧ページは収集のみ
                    if '/blog' in url_to_process:
                        page_links = self.extract_links(soup, url_to_process)
                        new_links = [l for l in page_links if l not in visited and l not in to_visit]
                        to_visit.extend(new_links)
                        visited.add(url_to_process)
                        if status_callback:
                            status_callback(f"一覧ページ: {len(new_links)}件の新規リンク発見")
                        continue
                    
                    # 個別記事ページを保存
                    if self.is_article_page(url_to_process):
                        title = soup.find('h1')
                        title = title.get_text(strip=True) if title else soup.title.get_text(strip=True) if soup.title else url_to_process
                        
                        # answer-genkinka | アンサー などのサイト名を除去
                        title = re.sub(r'\s*[|\-]\s*.*(answer-genkinka|アンサー).*$', '', title, flags=re.IGNORECASE)
                        title = title.strip()
                        
                        self.pages[url_to_process] = {'title': title, 'outbound_links': []}
                        
                        # 新しいリンクを発見
                        page_links = self.extract_links(soup, url_to_process)
                        new_links = [l for l in page_links if l not in visited and l not in to_visit]
                        to_visit.extend(new_links)
                        
                        if status_callback:
                            status_callback(f"記事発見: {title[:30]}... (新規リンク{len(new_links)}件)")
                    
                    visited.add(url_to_process)
                    
                    if progress_callback:
                        progress_callback(min(len(self.pages) / max_pages, 0.5))
                    
                    time.sleep(0.2)  # レート制限
                    
                except Exception as e:
                    if status_callback:
                        status_callback(f"エラー: {url_to_process} - {str(e)}")
                    continue

            if status_callback:
                status_callback(f"=== フェーズ1完了: {len(self.pages)}記事収集 ===")

            # フェーズ2: リンク関係構築
            if status_callback:
                status_callback("=== フェーズ2: リンク関係構築 ===")
            
            processed = set()
            for i, url_to_process in enumerate(list(self.pages.keys())):
                try:
                    if status_callback and i % 5 == 0:
                        status_callback(f"リンク解析中: {i+1}/{len(self.pages)}")
                    
                    response = session.get(url_to_process, timeout=10)
                    if response.status_code != 200: 
                        continue
                    
                    soup = BeautifulSoup(response.text, 'html.parser')
                    content_links = self.extract_content_links(soup, url_to_process)
                    
                    for link_data in content_links:
                        target = link_data['url']
                        if target in self.pages and target != url_to_process:
                            link_key = (url_to_process, target)
                            if link_key not in processed:
                                processed.add(link_key)
                                self.links.append((url_to_process, target))
                                self.pages[url_to_process]['outbound_links'].append(target)
                                self.detailed_links.append({
                                    'source_url': url_to_process, 
                                    'source_title': self.pages[url_to_process]['title'],
                                    'target_url': target, 
                                    'anchor_text': link_data['anchor_text']
                                })
                    
                    if progress_callback:
                        progress_callback(0.5 + (i / len(self.pages)) * 0.5)
                        
                except Exception:
                    continue

            # 被リンク数計算
            for url_key in self.pages:
                self.pages[url_key]['inbound_links'] = sum(1 for s, t in self.links if t == url_key)

            if status_callback:
                status_callback(f"=== 分析完了: {len(self.pages)}記事, {len(self.links)}リンク ===")
            
            return True
            
        except Exception as e:
            if status_callback:
                status_callback(f"分析エラー: {e}")
            return False

    def get_results_summary(self):
        """分析結果のサマリーを取得"""
        if not self.pages:
            return None
        
        total_pages = len(self.pages)
        total_links = len(self.links)
        isolated_pages = sum(1 for p in self.pages.values() if p['inbound_links'] == 0)
        popular_pages = sum(1 for p in self.pages.values() if p['inbound_links'] >= 5)
        
        return {
            'total_pages': total_pages,
            'total_links': total_links,
            'isolated_pages': isolated_pages,
            'popular_pages': popular_pages
        }

    def get_detailed_results(self):
        """詳細結果をDataFrame形式で取得"""
        if not self.detailed_links and not self.pages:
            return None
        
        data = []
        
        # 被リンクありページのデータ
        for link in self.detailed_links:
            data.append({
                'ページタイトル': self.pages.get(link['target_url'], {}).get('title', link['target_url']),
                'URL': link['target_url'],
                '被リンク元タイトル': link['source_title'],
                '被リンク元URL': link['source_url'],
                'アンカーテキスト': link['anchor_text']
            })
        
        # 孤立ページも追加
        for url, info in self.pages.items():
            if info['inbound_links'] == 0:
                data.append({
                    'ページタイトル': info['title'],
                    'URL': url,
                    '被リンク元タイトル': '（被リンクなし）',
                    '被リンク元URL': '',
                    'アンカーテキスト': ''
                })
        
        return pd.DataFrame(data)

def main():
    st.set_page_config(
        page_title="Answer-Genkinka 内部リンク分析",
        page_icon="🔗",
        layout="wide"
    )
    
    st.title("🔗 answer-genkinka.jp専用内部リンク分析ツール")
    st.markdown("**実際のクロール版 - Streamlit対応**")
    
    # URL入力
    col1, col2 = st.columns([3, 1])
    with col1:
        url = st.text_input(
            "分析URL", 
            value="https://answer-genkinka.jp/blog/",
            placeholder="https://answer-genkinka.jp/blog/"
        )
    
    with col2:
        st.markdown("**対象サイト:**")
        st.info("answer-genkinka.jp")
    
    # 分析実行
    if st.button("🚀 実際のクロール開始", type="primary"):
        if not url:
            st.error("URLを入力してください")
            return
        
        analyzer = AnswerAnalyzer()
        
        # プログレスバーとステータス表示用
        progress_bar = st.progress(0)
        status_placeholder = st.empty()
        
        def update_progress(value):
            progress_bar.progress(value)
        
        def update_status(message):
            status_placeholder.text(message)
        
        # 実際の分析実行
        with st.spinner('answer-genkinka.jp を実際にクロール中...'):
            success = analyzer.analyze_site(url, update_progress, update_status)
        
        if success:
            # 実際の結果表示
            summary = analyzer.get_results_summary()
            
            if summary and summary['total_pages'] > 0:
                st.success("✅ 実際のクロール完了！")
                
                # 実際の統計情報
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("実際の記事数", summary['total_pages'])
                with col2:
                    st.metric("実際のリンク数", summary['total_links'])
                with col3:
                    st.metric("孤立記事", summary['isolated_pages'])
                with col4:
                    st.metric("人気記事", summary['popular_pages'])
                
                # 実際の詳細結果
                df = analyzer.get_detailed_results()
                if df is not None and not df.empty:
                    st.subheader("📊 実際の分析結果")
                    st.dataframe(df, use_container_width=True, height=400)
                    
                    # 実際のCSVダウンロード
                    csv_data = df.to_csv(index=False).encode('utf-8-sig')
                    filename = f"answer-genkinka-実際の結果-{datetime.now().strftime('%Y%m%d')}.csv"
                    
                    st.download_button(
                        label="📥 実際の結果をCSVダウンロード",
                        data=csv_data,
                        file_name=filename,
                        mime="text/csv",
                        type="primary"
                    )
                else:
                    st.warning("記事は見つかりましたが、内部リンクデータが取得できませんでした")
            else:
                st.warning("記事が見つかりませんでした。URLやサイト構造を確認してください。")
        else:
            st.error("クロール中にエラーが発生しました")
        
        # プログレスバーとステータスをクリア
        progress_bar.empty()
        status_placeholder.empty()

if __name__ == "__main__":
    main()
