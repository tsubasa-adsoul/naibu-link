import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import time
import re
import pandas as pd
from datetime import datetime
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

    def analyze(self, url, status_callback=None):
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
            while to_visit and len(self.pages) < 500:
                current_url = to_visit.pop(0)
                if current_url in visited: continue
                
                try:
                    if status_callback:
                        status_callback(f"処理中: {current_url}")
                    
                    response = session.get(current_url, timeout=10)
                    if response.status_code != 200: 
                        if status_callback:
                            status_callback(f"HTTPエラー: {response.status_code}")
                        continue
                    
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    # NOINDEXチェック
                    robots = soup.find('meta', attrs={'name': 'robots'})
                    if robots and 'noindex' in robots.get('content', '').lower():
                        if status_callback:
                            status_callback("NOINDEXをスキップ")
                        continue
                    
                    # 記事一覧ページは収集のみ
                    if '/blog' in current_url:
                        page_links = self.extract_links(soup, current_url)
                        new_links = [l for l in page_links if l not in visited and l not in to_visit]
                        to_visit.extend(new_links)
                        visited.add(current_url)
                        if status_callback:
                            status_callback(f"一覧ページ: {len(new_links)}件の新規リンク")
                        continue
                    
                    # 個別記事ページを保存
                    if self.is_article_page(current_url):
                        title = soup.find('h1')
                        title = title.get_text(strip=True) if title else current_url
                        
                        # answer-genkinka | アンサー などのサイト名を除去
                        title = re.sub(r'\s*[|\-]\s*.*(answer-genkinka|アンサー).*$', '', title, flags=re.IGNORECASE)
                        
                        self.pages[current_url] = {'title': title, 'outbound_links': []}
                        
                        # 新しいリンクを発見
                        page_links = self.extract_links(soup, current_url)
                        new_links = [l for l in page_links if l not in visited and l not in to_visit]
                        to_visit.extend(new_links)
                        
                        if status_callback:
                            status_callback(f"記事: {title}")
                            status_callback(f"新規: {len(new_links)}件")
                    
                    visited.add(current_url)
                    time.sleep(0.1)
                    
                except Exception as e:
                    if status_callback:
                        status_callback(f"エラー: {e}")
                    continue

            if status_callback:
                status_callback(f"=== フェーズ1完了: {len(self.pages)}記事 ===")

            # フェーズ2: リンク関係構築
            if status_callback:
                status_callback("=== フェーズ2: リンク関係構築 ===")
            
            processed = set()
            for current_url in list(self.pages.keys()):
                try:
                    response = session.get(current_url, timeout=10)
                    if response.status_code != 200: continue
                    
                    soup = BeautifulSoup(response.text, 'html.parser')
                    content_links = self.extract_content_links(soup, current_url)
                    
                    for link_data in content_links:
                        target = link_data['url']
                        if target in self.pages and target != current_url:
                            link_key = (current_url, target)
                            if link_key not in processed:
                                processed.add(link_key)
                                self.links.append((current_url, target))
                                self.pages[current_url]['outbound_links'].append(target)
                                self.detailed_links.append({
                                    'source_url': current_url, 'source_title': self.pages[current_url]['title'],
                                    'target_url': target, 'anchor_text': link_data['anchor_text']
                                })
                except Exception as e:
                    if status_callback:
                        status_callback(f"リンク解析エラー: {e}")
                    continue

            # 被リンク数計算
            for url in self.pages:
                self.pages[url]['inbound_links'] = sum(1 for s, t in self.links if t == url)

            if status_callback:
                status_callback(f"=== 分析完了: {len(self.pages)}記事, {len(self.links)}リンク ===")
            
            return True
            
        except Exception as e:
            if status_callback:
                status_callback(f"分析エラー: {e}")
            return False

    def get_detailed_csv_data(self):
        """詳細CSVデータを取得"""
        data = []
        
        # ターゲット別にグループ化
        targets = {}
        for link in self.detailed_links:
            target = link['target_url']
            targets.setdefault(target, []).append(link)
        
        # 被リンク数でソート
        sorted_targets = sorted(targets.items(), key=lambda x: len(x[1]), reverse=True)
        
        row = 1
        for target, links_list in sorted_targets:
            title = self.pages.get(target, {}).get('title', target)
            for link in links_list:
                data.append([row, title, target, link['source_title'], link['source_url'], link['anchor_text']])
                row += 1
        
        # 孤立ページも追加
        for url, info in self.pages.items():
            if info['inbound_links'] == 0:
                data.append([row, info['title'], url, '', '', ''])
                row += 1
        
        return data

def main():
    st.set_page_config(
        page_title="Answer-Genkinka 内部リンク分析",
        page_icon="🔗",
        layout="wide"
    )
    
    st.title("🔗 answer-genkinka.jp専用内部リンク分析ツール")
    st.markdown("**全自動版 - Streamlit対応**")
    
    # URL入力
    url = st.text_input(
        "分析URL", 
        value="https://answer-genkinka.jp/blog/",
        placeholder="https://answer-genkinka.jp/blog/"
    )
    
    # 分析実行
    if st.button("🚀 分析開始", type="primary"):
        if not url:
            st.error("URLを入力してください")
            return
        
        analyzer = AnswerAnalyzer()
        
        # ステータス表示用
        status_placeholder = st.empty()
        
        def update_status(message):
            status_placeholder.text(message)
        
        # 分析実行
        with st.spinner('answer-genkinka.jp を分析中...'):
            success = analyzer.analyze(url, update_status)
        
        if success and analyzer.pages:
            st.success("✅ 分析完了！")
            
            # 統計情報
            total = len(analyzer.pages)
            isolated = sum(1 for p in analyzer.pages.values() if p['inbound_links'] == 0)
            popular = sum(1 for p in analyzer.pages.values() if p['inbound_links'] >= 5)
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("記事数", total)
            with col2:
                st.metric("リンク数", len(analyzer.links))
            with col3:
                st.metric("孤立記事", isolated)
            with col4:
                st.metric("人気記事", popular)
            
            # 結果表示
            st.subheader("📊 分析結果")
            
            sorted_pages = sorted(analyzer.pages.items(), key=lambda x: x[1]['inbound_links'], reverse=True)
            
            for i, (page_url, info) in enumerate(sorted_pages[:20]):  # 上位20件
                inbound = info['inbound_links']
                outbound = len(info['outbound_links'])
                
                if inbound == 0:
                    eval_text = "🚨要改善"
                elif inbound >= 10:
                    eval_text = "🏆超人気"
                elif inbound >= 5:
                    eval_text = "✅人気"
                else:
                    eval_text = "⚠️普通"
                
                st.write(f"**{i+1}.** {info['title'][:50]}...")
                st.write(f"被リンク:{inbound} | 発リンク:{outbound} | {eval_text}")
                st.write(f"🔗 {page_url}")
                st.divider()
            
            # CSVダウンロード
            if analyzer.detailed_links:
                csv_data = analyzer.get_detailed_csv_data()
                
                if csv_data:
                    df = pd.DataFrame(csv_data, columns=['番号', 'ページタイトル', 'URL', '被リンク元タイトル', '被リンク元URL', 'アンカーテキスト'])
                    
                    st.subheader("📥 CSV出力")
                    st.dataframe(df, use_container_width=True, height=300)
                    
                    csv_string = df.to_csv(index=False).encode('utf-8-sig')
                    filename = f"answer-genkinka-{datetime.now().strftime('%Y-%m-%d')}.csv"
                    
                    st.download_button(
                        label="詳細CSVダウンロード",
                        data=csv_string,
                        file_name=filename,
                        mime="text/csv",
                        type="primary"
                    )
        else:
            st.error("分析に失敗しました")
        
        status_placeholder.empty()

if __name__ == "__main__":
    main()
