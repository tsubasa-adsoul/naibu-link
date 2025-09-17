# answer-genkinka.py （改造後）

import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import time
import re
import csv
from io import StringIO

# ★★★ ここからが、このファイルが呼び出されたときに実行される本体です ★★★
def analyze(status_callback):
    """
    answer-genkinka.jp の分析を実行し、結果をCSV文字列で返す関数。
    主のオリジナルのロジックを完全に移植。
    """
    
    # --- 主のオリジナルのクラスや関数を、この中で定義・使用します ---
    
    class AnswerAnalyzer:
        def __init__(self, callback):
            self.pages = {}
            self.links = []
            self.detailed_links = []
            self.status_callback = callback # 進捗報告用の関数を受け取る

        def _update_status(self, message):
            if self.status_callback:
                self.status_callback(message)

        # --- 主のオリジナルの関数群（変更なし） ---
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
            if any(word in path for word in exclude_words): return False
            if path.startswith('/') and len(path) > 1:
                clean_path = path[1:].rstrip('/')
                if clean_path and '/' not in clean_path: return True
            return False

        def is_crawlable(self, url):
            path = urlparse(self.normalize_url(url)).path.lower()
            exclude_words = ['/site/', '/wp-admin', '/feed', '.jpg', '.png', '.css', '.js']
            if any(word in path for word in exclude_words): return False
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
            if not content: return []
            links = []
            for a in content.find_all('a', href=True):
                href = a.get('href', '').strip()
                text = a.get_text(strip=True) or ''
                if href and not href.startswith('#') and text:
                    absolute = urljoin(current_url, href)
                    if 'answer-genkinka.jp' in absolute and self.is_article_page(absolute):
                        links.append({'url': self.normalize_url(absolute), 'anchor_text': text[:100]})
            return links

        # --- 主のオリジナルの分析ロジック（StreamlitのUI部品をコールバックに置き換え） ---
        def run_analysis(self, start_url):
            self.pages, self.links, self.detailed_links = {}, [], []
            visited, to_visit = set(), [self.normalize_url(start_url)]
            to_visit.append('https://answer-genkinka.jp/blog/page/2/')

            session = requests.Session()
            session.headers.update({'User-Agent': 'Mozilla/5.0'})

            self._update_status("フェーズ1: ページ収集中...")
            
            crawl_count = 0
            while to_visit and len(self.pages) < 100: # Streamlit Cloudでの上限
                url = to_visit.pop(0)
                if url in visited: continue
                
                try:
                    self._update_status(f"処理中 ({crawl_count+1}/100): {url}")
                    response = session.get(url, timeout=15) # タイムアウトを少し延長
                    if response.status_code != 200: continue
                    
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    robots = soup.find('meta', attrs={'name': 'robots'})
                    if robots and 'noindex' in robots.get('content', '').lower(): continue
                    
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
                    crawl_count += 1
                    time.sleep(0.1)
                    
                except Exception as e:
                    self._update_status(f"  - エラー発生: {url} - {e}")
                    continue

            self._update_status("フェーズ2: リンク関係構築中...")
            
            processed = set()
            total_pages = len(self.pages.keys())
            for i, url in enumerate(list(self.pages.keys())):
                try:
                    self._update_status(f"リンク解析中 ({i+1}/{total_pages}): {url}")
                    response = session.get(url, timeout=15)
                    if response.status_code != 200: continue
                    
                    soup = BeautifulSoup(response.text, 'html.parser')
                    content_links = self.extract_content_links(soup, url)
                    
                    for link_data in content_links:
                        target = link_data['url']
                        if target in self.pages and target != url:
                            if (url, target) not in processed:
                                processed.add((url, target))
                                self.links.append((url, target))
                                self.pages[url]['outbound_links'].append(target)
                                self.detailed_links.append({
                                    'source_url': url, 'source_title': self.pages[url]['title'],
                                    'target_url': target, 'anchor_text': link_data['anchor_text']
                                })
                                
                except Exception as e:
                    self._update_status(f"  - リンク解析エラー: {url} - {e}")
                    continue

            for url in self.pages:
                self.pages[url]['inbound_links'] = sum(1 for s, t in self.links if t == url)

            self._update_status("分析完了!")

        # --- 主のオリジナルのCSVエクスポートロジックを、文字列を返すように変更 ---
        def get_csv_string(self):
            if not self.pages:
                return "A_番号,B_ページタイトル,C_URL,D_被リンク元ページタイトル,E_被リンク元ページURL,F_被リンク元ページアンカーテキスト\n"

            output = StringIO()
            writer = csv.writer(output)
            writer.writerow(['A_番号', 'B_ページタイトル', 'C_URL', 'D_被リンク元ページタイトル', 'E_被リンク元ページURL', 'F_被リンク元ページアンカーテキスト'])
            
            # 被リンクありページ
            for link in self.detailed_links:
                target_url = link['target_url']
                target_title = self.pages.get(target_url, {}).get('title', target_url)
                # 番号は main.py 側で振るため、ここではダミー値（空）
                writer.writerow(['', target_title, target_url, link['source_title'], link['source_url'], link['anchor_text']])
            
            # 孤立ページ
            for url, info in self.pages.items():
                if info.get('inbound_links', 0) == 0:
                    writer.writerow(['', info['title'], url, '', '', ''])

            return output.getvalue()
            
    # --- ここからが analyze 関数の実行部分 ---
    
    # 主のクラスのインスタンスを作成し、進捗報告用の関数を渡す
    analyzer = AnswerAnalyzer(callback=status_callback)
    
    # 分析を実行
    start_url = "https://answer-genkinka.jp/blog/"
    analyzer.run_analysis(start_url)
    
    # CSV文字列を生成して返す
    csv_string = analyzer.get_csv_string()
    
    return csv_string
