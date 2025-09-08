import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import time
import re
import csv
import pandas as pd
from datetime import datetime
from io import StringIO
import threading
import queue

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
        """個別記事ページかどうか判定（シンプル版）"""
        path = urlparse(self.normalize_url(url)).path.lower()
        
        # 除外：明らかに記事ではないもの
        exclude_words = ['/site/', '/blog/', '/page/', '/feed', '/wp-', '.']
        if any(word in path for word in exclude_words):
            return False
        
        # 許可：ルート直下のスラッグ（/記事名）
        if path.startswith('/') and len(path) > 1:
            # パスからスラッシュを除去
            clean_path = path[1:].rstrip('/')
            # スラッシュが含まれていなくて、文字がある
            if clean_path and '/' not in clean_path:
                return True
        
        return False

    def is_crawlable(self, url):
        """クロール対象かどうか判定"""
        path = urlparse(self.normalize_url(url)).path.lower()
        
        # 除外：明らかに不要なもの
        exclude_words = ['/site/', '/wp-admin', '/feed', '.jpg', '.png', '.css', '.js']
        if any(word in path for word in exclude_words):
            return False
        
        # 許可：ブログ関連 + 記事ページ
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
        """サイト分析メイン処理"""
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
            while to_visit and len(self.pages) < max_pages:
                url_to_process = to_visit.pop(0)
                if url_to_process in visited: 
                    continue
                
                try:
                    if status_callback:
                        status_callback(f"処理中: {url_to_process}")
                    
                    response = session.get(url_to_process, timeout=10)
                    if response.status_code != 200: 
                        continue
                    
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    # NOINDEXチェック
                    robots = soup.find('meta', attrs={'name': 'robots'})
                    if robots and 'noindex' in robots.get('content', '').lower():
                        continue
                    
                    # 記事一覧ページは収集のみ
                    if '/blog' in url_to_process:
                        page_links = self.extract_links(soup, url_to_process)
                        new_links = [l for l in page_links if l not in visited and l not in to_visit]
                        to_visit.extend(new_links)
                        visited.add(url_to_process)
                        continue
                    
                    # 個別記事ページを保存
                    if self.is_article_page(url_to_process):
                        title = soup.find('h1')
                        title = title.get_text(strip=True) if title else url_to_process
                        
                        # answer-genkinka | アンサー などのサイト名を除去
                        title = re.sub(r'\s*[|\-]\s*.*(answer-genkinka|アンサー).*$', '', title, flags=re.IGNORECASE)
                        
                        self.pages[url_to_process] = {'title': title, 'outbound_links': []}
                        
                        # 新しいリンクを発見
                        page_links = self.extract_links(soup, url_to_process)
                        new_links = [l for l in page_links if l not in visited and l not in to_visit]
                        to_visit.extend(new_links)
                    
                    visited.add(url_to_process)
                    
                    if progress_callback:
                        progress_callback(len(self.pages) / max_pages)
                    
                    time.sleep(0.1)
                    
                except Exception as e:
                    continue

            if status_callback:
                status_callback(f"=== フェーズ1完了: {len(self.pages)}記事 ===")

            # フェーズ2: リンク関係構築
            if status_callback:
                status_callback("=== フェーズ2: リンク関係構築 ===")
            
            processed = set()
            for i, url_to_process in enumerate(list(self.pages.keys())):
                try:
                    if progress_callback and i % 10 == 0:
                        progress_callback(0.5 + (i / len(self.pages)) * 0.5)
                    
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
        if not self.detailed_links:
            return None
        
        # 被リンクありページのデータ
        data = []
        for link in self.detailed_links:
            data.append({
                'ページタイトル': link['target_url'] if link['target_url'] in self.pages else link['target_url'],
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
                    '被リンク元タイトル': '',
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
    st.markdown("**全自動版 - Streamlit対応**")
    
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
    if st.button("🚀 分析開始", type="primary"):
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
        
        # 分析実行
        with st.spinner('分析中...'):
            success = analyzer.analyze_site(url, update_progress, update_status)
        
        if success:
            # 結果表示
            summary = analyzer.get_results_summary()
            
            if summary:
                st.success("✅ 分析完了！")
                
                # 統計情報
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("総記事数", summary['total_pages'])
                with col2:
                    st.metric("内部リンク数", summary['total_links'])
                with col3:
                    st.metric("孤立記事", summary['isolated_pages'])
                with col4:
                    st.metric("人気記事", summary['popular_pages'])
                
                # 詳細結果
                df = analyzer.get_detailed_results()
                if df is not None and not df.empty:
                    st.subheader("📊 詳細分析結果")
                    
                    # データ表示
                    st.dataframe(df, use_container_width=True, height=400)
                    
                    # CSVダウンロード
                    csv_data = df.to_csv(index=False).encode('utf-8-sig')
                    filename = f"answer-genkinka-{datetime.now().strftime('%Y%m%d')}.csv"
                    
                    st.download_button(
                        label="📥 CSVダウンロード",
                        data=csv_data,
                        file_name=filename,
                        mime="text/csv",
                        type="primary"
                    )
                    
                    # 上位結果表示
                    st.subheader("🏆 被リンク数ランキング（上位10件）")
                    
                    # 被リンク数でグループ化
                    inbound_counts = {}
                    for _, row in df.iterrows():
                        if row['被リンク元URL']:  # 被リンクがある場合のみ
                            url_key = row['URL']
                            if url_key not in inbound_counts:
                                inbound_counts[url_key] = {
                                    'title': row['ページタイトル'],
                                    'url': url_key,
                                    'count': 0
                                }
                            inbound_counts[url_key]['count'] += 1
                    
                    # 上位10件表示
                    sorted_pages = sorted(inbound_counts.values(), key=lambda x: x['count'], reverse=True)[:10]
                    
                    for i, page_info in enumerate(sorted_pages, 1):
                        count = page_info['count']
                        if count >= 10:
                            eval_text = "🏆 超人気"
                        elif count >= 5:
                            eval_text = "✅ 人気"
                        elif count >= 2:
                            eval_text = "⚠️ 普通"
                        else:
                            eval_text = "🔹 少数"
                        
                        st.write(f"**{i}位** | 被リンク数: **{count}** | {eval_text}")
                        st.write(f"📄 {page_info['title'][:80]}...")
                        st.write(f"🔗 {page_info['url']}")
                        st.divider()
                
                else:
                    st.warning("詳細データが取得できませんでした")
            else:
                st.warning("分析結果が取得できませんでした")
        else:
            st.error("分析中にエラーが発生しました")
        
        # プログレスバーとステータスをクリア
        progress_bar.empty()
        status_placeholder.empty()

if __name__ == "__main__":
    main()
