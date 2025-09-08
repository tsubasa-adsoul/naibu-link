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
        if not url: 
            return ""
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

    def analyze(self, start_url):
        self.pages, self.links, self.detailed_links = {}, [], []
        visited, to_visit = set(), [self.normalize_url(start_url)]
        
        to_visit.append('https://answer-genkinka.jp/blog/page/2/')

        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})

        progress_bar = st.progress(0)
        status_text = st.empty()

        status_text.text("フェーズ1: ページ収集中...")
        
        while to_visit and len(self.pages) < 100:
            url = to_visit.pop(0)
            if url in visited: 
                continue
            
            try:
                status_text.text(f"処理中: {url}")
                response = session.get(url, timeout=10)
                if response.status_code != 200: 
                    continue
                
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
                progress_bar.progress(len(self.pages) / 100)
                time.sleep(0.1)
                
            except Exception as e:
                continue

        status_text.text("フェーズ2: リンク関係構築中...")
        
        processed = set()
        for i, url in enumerate(list(self.pages.keys())):
            try:
                response = session.get(url, timeout=10)
                if response.status_code != 200: 
                    continue
                
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
                                'source_url': url, 
                                'source_title': self.pages[url]['title'],
                                'target_url': target, 
                                'anchor_text': link_data['anchor_text']
                            })
                            
                progress_bar.progress(0.5 + 0.5 * i / len(self.pages))
                            
            except Exception as e:
                continue

        for url in self.pages:
            self.pages[url]['inbound_links'] = sum(1 for s, t in self.links if t == url)

        progress_bar.progress(1.0)
        status_text.text("分析完了!")
        
        return self.pages, self.links, self.detailed_links

    def export_detailed_csv(self):
        if not self.detailed_links:
            return None
            
        csv_data = []
        csv_data.append(['番号', 'ページタイトル', 'URL', '被リンク元タイトル', '被リンク元URL', 'アンカーテキスト'])
        
        targets = {}
        for link in self.detailed_links:
            target = link['target_url']
            targets.setdefault(target, []).append(link)
        
        sorted_targets = sorted(targets.items(), key=lambda x: len(x[1]), reverse=True)
        
        page_number = 1
        for target, links_list in sorted_targets:
            title = self.pages.get(target, {}).get('title', target)
            for link in links_list:
                csv_data.append([page_number, title, target, link['source_title'], link['source_url'], link['anchor_text']])
            page_number += 1
        
        for url, info in self.pages.items():
            if info['inbound_links'] == 0:
                csv_data.append([page_number, info['title'], url, '', '', ''])
                page_number += 1
        
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
    
    start_url = st.text_input(
        "分析開始URL",
        value="https://answer-genkinka.jp/blog/",
        help="answer-genkinka.jpの分析開始URL"
    )
    
    if st.button("🚀 分析開始", type="primary"):
        if not start_url:
            st.error("URLを入力してください")
            return
            
        analyzer = AnswerAnalyzer()
        
        with st.spinner("分析中..."):
            pages, links, detailed_links = analyzer.analyze(start_url)
        
        if pages:
            st.session_state['analyzer_data'] = {
                'pages': pages,
                'links': links,
                'detailed_links': detailed_links,
                'analyzer': analyzer
            }
    
    if 'analyzer_data' in st.session_state:
        data = st.session_state['analyzer_data']
        pages = data['pages']
        links = data['links']
        analyzer = data['analyzer']
        
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
        
        st.subheader("📊 分析結果（被リンク数順）")
        
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
        
        if len(df_sorted) > 0:
            st.subheader("被リンク数ランキング（上位10件）")
            top_10 = df_sorted.head(10)
            chart_data = top_10.set_index('タイトル')['被リンク数']
            st.bar_chart(chart_data)
        
        st.subheader("詳細データ")
        st.dataframe(df_sorted, use_container_width=True)
        
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

if __name__ == "__main__":
    main()
