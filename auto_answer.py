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

    def analyze(self, start_url):
        """メイン分析処理"""
        self.pages, self.links, self.detailed_links = {}, [], []
        visited, to_visit = set(), [self.normalize_url(start_url)]
        
        # ページネーションを追加
        to_visit.append('https://answer-genkinka.jp/blog/page/2/')

        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})

        # プログレス表示
        progress_bar = st.progress(0)
        status_text = st.empty()

        # フェーズ1: ページ収集
        status_text.text("フェーズ1: ページ収集中...")
        
        while to_visit and len(self.pages) < 100:  # Streamlit用に制限
            url = to_visit.pop(0)
            if url in visited: continue
            
            try:
                status_text.text(f"処理中: {url}")
                response = session.get(url, timeout=10)
                if response.status_code != 200: 
                    continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # NOINDEXチェック
                robots = soup.find('meta', attrs={'name': 'robots'})
                if robots and 'noindex' in robots.get('content', '').lower():
                    continue
                
                # 記事一覧ページは収集のみ
                if '/blog' in url:
                    page_links = self.extract_links(soup, url)
                    new_links = [l for l in page_links if l not in visited and l not in to_visit]
                    to_visit.extend(new_links)
                    visited.add(url)
                    continue
                
                # 個別記事ページを保存
                if self.is_article_page(url):
                    title = soup.find('h1')
                    title = title.get_text(strip=True) if title else url
                    
                    # answer-genkinka | アンサー などのサイト名を除去
                    title = re.sub(r'\s*[|\-]\s*.*(answer-genkinka|アンサー).*$', '', title, flags=re.IGNORECASE)
                    
                    self.pages[url] = {'title': title, 'outbound_links': []}
                    
                    # 新しいリンクを発見
                    page_links = self.extract_links(soup, url)
                    new_links = [l for l in page_links if l not in visited and l not in to_visit]
                    to_visit.extend(new_links)
                
                visited.add(url)
                
                progress_bar.progress(len(self.pages) / 100)
                time.sleep(0.1)
                
            except Exception as e:
                st.error(f"エラー: {url} - {e}")
                continue

        # フェーズ2: リンク関係構築
        status_text.text("フェーズ2: リンク関係構築中...")
        
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
                            
                progress_bar.progress(0.5 + 0.5 * i / len(self.pages))
                            
            except Exception as e:
                continue

        # 被リンク数計算
        for url in self.pages:
            self.pages[url]['inbound_links'] = sum(1 for s, t in self.links if t == url)

        progress_bar.progress(1.0)
        status_text.text("分析完了!")
        
        return self.pages, self.links, self.detailed_links

    def export_detailed_csv(self):
        """詳細CSVエクスポート"""
        if not self.detailed_links:
            return None
            
        # CSVデータ作成
        csv_data = []
        csv_data.append(['番号', 'ページタイトル', 'URL', '被リンク元タイトル', '被リンク元URL', 'アンカーテキスト'])
        
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
                csv_data.append([row, title, target, link['source_title'], link['source_url'], link['anchor_text']])
                row += 1
        
        # 孤立ページも追加
        for url, info in self.pages.items():
            if info['inbound_links'] == 0:
                csv_data.append([row, info['title'], url, '', '', ''])
                row += 1
        
        # CSV文字列に変換
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerows(csv_data)
        return output.getvalue()

def main():
    st.set_page_config(
        page_title="Answer現金化 内部リンク分析",
        page_icon="🔗",
        layout="wide"
    )
    
    st.title("🔗 answer-genkinka.jp専用内部リンク分析ツール")
    st.markdown("**CustomTkinter完全移植版**")
    
    # URL入力
    start_url = st.text_input(
        "分析開始URL",
        value="https://answer-genkinka.jp/blog/",
        help="answer-genkinka.jpの分析開始URL"
    )
    
    # 分析実行
    if st.button("🚀 分析開始", type="primary"):
        if not start_url:
            st.error("URLを入力してください")
            return
            
        analyzer = AnswerAnalyzer()
        
        with st.spinner("分析中..."):
            pages, links, detailed_links = analyzer.analyze(start_url)
        
        if pages:
            # 統計表示
            total = len(pages)
            isolated = sum(1 for p in pages.values() if p['inbound_links'] == 0)
            popular = sum(1 for p in pages.values() if p['inbound_links'] >= 5)
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("総記事数", total)
            with col2:
                st.metric("総リンク数", len(links))
            with col3:
                st.metric("孤立ページ", isolated)
            with col4:
                st.metric("人気ページ", popular)
            
            # 結果表示
            st.subheader("📊 分析結果（被リンク数順）")
            
            # DataFrameに変換
            results_data = []
            for url, info in pages.items():
                results_data.append({
                    'タイトル': info['title'],
                    'URL': url,
                    '被リンク数': info['inbound_links'],
                    '発リンク数': len(info['outbound_links'])
                })
            
            df = pd.DataFrame(results_data)
            df_sorted = df.sort_values('被リンク数', ascending=False)
            
            # グラフ表示
            if len(df_sorted) > 0:
                st.subheader("被リンク数ランキング（上位10件）")
                top_10 = df_sorted.head(10)
                chart_data = top_10.set_index('タイトル')['被リンク数']
                st.bar_chart(chart_data)
            
            # 詳細テーブル
            st.subheader("詳細データ")
            st.dataframe(df_sorted, use_container_width=True)
            
            # CSVダウンロード
            csv_content = analyzer.export_detailed_csv()
            if csv_content:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"answer-genkinka-{timestamp}.csv"
                
                st.download_button(
                    "📥 詳細CSVダウンロード",
                    csv_content,
                    filename,
                    "text/csv",
                    help="被リンク数順でソートされた詳細レポート"
                )
            
            st.success("✅ 分析完了!")
        
        else:
            st.error("❌ データを取得できませんでした")

if __name__ == "__main__":
    main()
