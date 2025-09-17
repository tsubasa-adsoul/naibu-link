# auto_xgift.py （改造後）

# 必要なライブラリのみをインポート
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import re
import csv
from io import StringIO

# ★★★ このファイルが呼び出されたときに実行される本体です ★★★
def analyze(status_callback):
    """
    xgift.jp の分析を実行し、結果をCSV文字列で返す関数。
    主のオリジナルのロジックを、一切変更せずに移植。
    """

    # --- 主のオリジナルのコードを、この関数の中にそのまま配置します ---
    
    # ページやリンク情報を保存する変数
    pages = {}
    links = []
    detailed_links = []

    # --- 主のオリジナルの関数群（クロールロジックの心臓部） ---
    # これらは一切変更いたしません。

    def normalize_url(url):
        if not url: return ""
        try:
            parsed = urlparse(url)
            return f"https://{parsed.netloc.replace('www.', '')}{parsed.path.rstrip('/')}"
        except: return url

    def is_article_page(url):
        path = urlparse(normalize_url(url)).path.lower()
        exclude_patterns = ['/site/', '/wp-admin', '/wp-content', '/wp-json', '/feed', '/rss', '.', '/page/', '/category/', '/tag/', '/author/', '/search', '/privacy', '/terms', '/contact', '/about']
        if any(p in path for p in exclude_patterns): return False
        
        if path.startswith('/blog/') and path != '/blog':
            article_path = path[6:]
            if article_path and '/' not in article_path.rstrip('/'):
                clean_path = article_path.rstrip('/')
                if clean_path and len(clean_path) > 2: return True
        
        if (path.startswith('/') and len(path) > 1 and '/' not in path[1:].rstrip('/') and not path.startswith('/blog')):
            clean_path = path[1:].rstrip('/')
            if clean_path and len(clean_path) > 3 and all(c.isalnum() or c in '-_' for c in clean_path):
                return True
        return False

    def is_crawlable(url):
        path = urlparse(normalize_url(url)).path.lower()
        if any(w in path for w in ['/site/', '/wp-admin', '/wp-content', '/wp-json', '/feed', '/rss', '.jpg', '.png', '.css', '.js', '.pdf', '.zip', '.svg', '.ico']): return False
        return (path.startswith('/blog') or is_article_page(url) or path in ['/', ''])

    def extract_links_for_crawling(soup, current_url):
        links_set = set()
        for a in soup.find_all('a', href=True):
            href = a.get('href', '').strip()
            if href and not href.startswith('#'):
                absolute = urljoin(current_url, href)
                if 'xgift.jp' in absolute and is_crawlable(absolute):
                    links_set.add(normalize_url(absolute))
        return list(links_set)

    def extract_content_links(soup, current_url):
        content_selectors = ['.entry-content', '.post-content', '.main-content', 'main', 'article', '.content', '.single-content', '[class*="content"]']
        content = None
        for selector in content_selectors:
            content = soup.select_one(selector)
            if content: break
        
        if not content:
            content = soup.find('body')
            if content:
                for remove_sel in ['nav', 'header', 'footer', '.navigation', '.menu', '.sidebar', '.widget', '.ads', '.related', '.author-info']:
                    for elem in content.select(remove_sel): elem.decompose()
        if not content: return []

        links = []
        for a in content.find_all('a', href=True):
            href = a.get('href', '').strip()
            text = a.get_text(strip=True) or ''
            if href and not href.startswith('#') and text:
                absolute = urljoin(current_url, href)
                if 'xgift.jp' in absolute and is_article_page(absolute):
                    links.append({'url': normalize_url(absolute), 'anchor_text': text[:100]})
        return links

    # --- ここからが分析の実行部分です ---
    try:
        pages, links, detailed_links = {}, [], []
        visited, to_visit = set(), [normalize_url("https://xgift.jp/blog/")]
        
        to_visit.extend(['https://xgift.jp/blog/page/2/', 'https://xgift.jp/blog/page/3/', 'https://xgift.jp/blog/category/', 'https://xgift.jp/'])

        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})

        status_callback("=== xgift.jp (AFFINGER) 分析開始 ===")
        status_callback("フェーズ1: ページ収集中...")

        max_pages = 600
        while to_visit and len(pages) < max_pages:
            url = to_visit.pop(0)
            if url in visited: continue
            
            try:
                response = session.get(url, timeout=15)
                if response.status_code != 200: continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                robots = soup.find('meta', attrs={'name': 'robots'})
                if robots and 'noindex' in robots.get('content', '').lower(): continue
                
                if (('/blog' in url and not is_article_page(url)) or '/page/' in url or '/category/' in url):
                    page_links = extract_links_for_crawling(soup, url)
                    new_links = [l for l in page_links if l not in visited and l not in to_visit]
                    to_visit.extend(new_links)
                    visited.add(url)
                    continue
                
                if is_article_page(url):
                    title = None
                    for selector in ['h1.entry-title', 'h1', '.post-title', '.entry-title']:
                        if (title_elem := soup.select_one(selector)):
                            title = title_elem.get_text(strip=True)
                            break
                    if not title: title = soup.title.get_text(strip=True) if soup.title else url
                    title = re.sub(r'\s*[|\-]\s*.*(xgift|XGIFT|エックスギフト).*$', '', title, flags=re.IGNORECASE).strip()
                    
                    pages[url] = {'title': title, 'outbound_links': []}
                    
                    page_links = extract_links_for_crawling(soup, url)
                    new_links = [l for l in page_links if l not in visited and l not in to_visit]
                    to_visit.extend(new_links)
                
                visited.add(url)
                status_callback(f"収集中: {len(pages)}記事")
                time.sleep(0.2)
                
            except Exception as e:
                status_callback(f"  - エラー: {url} - {e}")
                continue

        status_callback(f"=== フェーズ1完了: {len(pages)}記事 ===")
        status_callback("=== フェーズ2: リンク関係構築 ===")
        
        processed = set()
        for i, url in enumerate(list(pages.keys())):
            try:
                status_callback(f"リンク解析中: {i+1}/{len(pages)}")
                response = session.get(url, timeout=15)
                if response.status_code != 200: continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                content_links = extract_content_links(soup, url)
                
                for link_data in content_links:
                    target = link_data['url']
                    if target in pages and target != url:
                        if (url, target) not in processed:
                            processed.add((url, target))
                            links.append((url, target))
                            pages[url]['outbound_links'].append(target)
                            detailed_links.append({
                                'source_url': url, 'source_title': pages[url]['title'],
                                'target_url': target, 'anchor_text': link_data['anchor_text']
                            })
            except Exception as e:
                status_callback(f"  - リンク解析エラー: {url} - {e}")
                continue

        for url in pages:
            pages[url]['inbound_links'] = sum(1 for s, t in links if t == url)

        status_callback(f"=== 分析完了: {len(pages)}記事, {len(links)}リンク ===")

    except Exception as e:
        status_callback(f"致命的なエラーが発生しました: {e}")
        return "A_番号,B_ページタイトル,C_URL,D_被リンク元ページタイトル,E_被リンク元ページURL,F_被リンク元ページアンカーテキスト\n"

    # --- 最後にCSV文字列を生成して返します ---
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['A_番号', 'B_ページタイトル', 'C_URL', 'D_被リンク元ページタイトル', 'E_被リンク元ページURL', 'F_被リンク元ページアンカーテキスト'])
    
    targets = {}
    for link in detailed_links:
        target = link['target_url']
        targets.setdefault(target, []).append(link)
    
    for target, links_list in sorted(targets.items(), key=lambda x: len(x[1]), reverse=True):
        title = pages.get(target, {}).get('title', target)
        for link in links_list:
            writer.writerow(['', title, target, link['source_title'], link['source_url'], link['anchor_text']])
    
    for url, info in pages.items():
        if info.get('inbound_links', 0) == 0:
            writer.writerow(['', info['title'], url, '', '', ''])

    return output.getvalue()
