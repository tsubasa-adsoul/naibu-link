# auto_arigataya.py （最終調整版・本文リンク重視）

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import re
import csv
from io import StringIO

def analyze_step(state):
    
    def log(message):
        if 'log' not in state: state['log'] = []
        state['log'].append(f"[{time.strftime('%H:%M:%S')}] {message}")
        if len(state['log']) > 100: state['log'] = state['log'][-100:]

    def normalize_url(url, base_url):
        if not isinstance(url, str): return ""
        try:
            full_url = urljoin(base_url, url.strip())
            parsed = urlparse(full_url)
            netloc = parsed.netloc.lower().replace('www.', '')
            path = parsed.path.rstrip('/')
            if not path: path = '/'
            return f"https://{netloc}{path}"
        except: return ""

    def is_content(url):
        try:
            path = urlparse(url).path.lower()
            if any(re.search(p, path) for p in [r'^/category/', r'^/[a-z0-9\-]+/?$', r'^/$']): return True
            return False
        except: return False

    def is_noindex_page(soup):
        return soup.find('meta', attrs={'name': 'robots', 'content': re.compile(r'noindex', re.I)})

    # ★★★ ここが最重要修正点 ★★★
    def extract_links(soup, base_url):
        links = []
        # 本文エリアのセレクタを定義
        selectors = ['.post_content', '.entry-content', 'main .article']
        content_area = None
        for selector in selectors:
            content_area = soup.select_one(selector)
            if content_area:
                log(f"  -> 本文エリア発見: '{selector}'")
                break
        
        # もし本文エリアが見つからなければ、リンクは抽出しない
        if not content_area:
            log("  -> 警告: 本文エリアが見つからず、リンクを抽出しませんでした。")
            return []

        # 本文エリア内の不要な部分を除外
        for exclude in content_area.select('header, footer, nav, aside, .sidebar, .widget, .share, .related, .popular-posts, .breadcrumb, .author-box, .navigation'):
            exclude.decompose()
            
        for a in content_area.find_all('a', href=True):
            links.append({'url': a['href'], 'anchor_text': a.get_text(strip=True) or a.get('title', '')})
        for element in content_area.find_all(attrs={'onclick': True}):
            match = re.search(r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]", element.get('onclick', ''))
            if match:
                links.append({'url': match.group(1), 'anchor_text': element.get_text(strip=True) or '[onclick]'})
        return links

    def extract_from_sitemap_recursively(sitemap_url, session):
        urls = set()
        try:
            res = session.get(sitemap_url, timeout=20)
            if not res.ok: return urls
            soup = BeautifulSoup(res.content, 'lxml')
            
            sitemap_indexes = soup.find_all('sitemap')
            if sitemap_indexes:
                for sitemap in sitemap_indexes:
                    if loc := sitemap.find('loc'):
                        urls.update(extract_from_sitemap_recursively(loc.text.strip(), session))
            
            url_tags = soup.find_all('url')
            for url_tag in url_tags:
                if loc := url_tag.find('loc'):
                    urls.add(loc.text.strip())
        except Exception as e:
            log(f"サイトマップ解析エラー: {sitemap_url} - {e}")
        return urls

    if state['phase'] == 'initializing':
        log("フェーズ1: 記事URLの収集を開始します。")
        try:
            base_url = "https://arigataya.co.jp"
            session = requests.Session()
            session.headers.update({'User-Agent': 'Mozilla/5.0'})
            
            sitemap_urls = extract_from_sitemap_recursively(urljoin(base_url, '/sitemap.xml'), session)
            initial_urls = list(set([base_url] + list(sitemap_urls)))
            
            state.update({
                'session': session, 'base_url': base_url, 'domain': urlparse(base_url).netloc.lower().replace('www.', ''),
                'to_visit': [u for u in initial_urls if is_content(u)],
                'visited': set(), 'pages': {}, 'links': [], 'phase': 'crawling', 'crawl_limit': 800
            })
            log(f"シードURLを{len(state['to_visit'])}件発見。クロールを開始します。")
            if not state['to_visit']:
                log("警告: クロール対象のURLが見つかりませんでした。")
                state['phase'] = 'error'
        except Exception as e:
            log(f"初期化エラー: {e}")
            state['phase'] = 'error'
        return state

    if state['phase'] == 'crawling':
        session, base_url, domain = state['session'], state['base_url'], state['domain']
        crawled_count = 0
        
        while state['to_visit'] and crawled_count < 5:
            url = state['to_visit'].pop(0)
            if url in state['visited']: continue
            state['visited'].add(url)
            
            try:
                log(f"クロール中: {url}")
                res = session.get(url, timeout=20)
                if not res.ok: continue

                soup = BeautifulSoup(res.text, 'html.parser')
                if is_noindex_page(soup): continue

                title = (soup.find('h1') or soup.find('title')).get_text(strip=True)
                title = re.sub(r'\s*\|.*$', '', title).strip()
                state['pages'][url] = {'title': title}
                
                for link in extract_links(soup, base_url):
                    norm_link = normalize_url(link['url'], base_url)
                    if norm_link and norm_link.startswith(f"https://{domain}") and is_content(norm_link):
                        state['links'].append({
                            'source_url': url, 'source_title': title,
                            'target_url': norm_link, 'anchor_text': link['anchor_text']
                        })
                        if norm_link not in state['visited'] and norm_link not in state['to_visit']:
                            state['to_visit'].append(norm_link)
                
                crawled_count += 1
                time.sleep(0.5)
            except Exception as e:
                log(f"クロールエラー: {url} - {e}")
        
        total_urls = len(state['visited']) + len(state['to_visit'])
        state['progress'] = len(state['visited']) / total_urls if total_urls > 0 else 1
        state['progress_text'] = f"進捗: {len(state['visited'])} / {total_urls} ページ"

        if not state['to_visit']:
            log("クロール完了。")
            state['phase'] = 'completed'
        return state

    return state

def generate_csv(state):
    output = StringIO()
    writer = csv.writer(output, lineterminator='\n')
    writer.writerow(['番号', 'ページタイトル', 'URL', '被リンク元タイトル', '被リンク元URL', 'アンカーテキスト'])
    
    pages = state.get('pages', {})
    links = state.get('links', [])
    if not pages: return output.getvalue()

    page_inlinks = {url: [] for url in pages}
    for link in links:
        if link['target_url'] in page_inlinks:
            page_inlinks[link['target_url']].append(link)

    sorted_pages = sorted(pages.keys(), key=lambda url: len(page_inlinks.get(url, [])), reverse=True)
    page_numbers = {url: i+1 for i, url in enumerate(sorted_pages)}

    for url in sorted_pages:
        page_num = page_numbers[url]
        title = pages[url]['title']
        inlinks = page_inlinks[url]
        
        if inlinks:
            for link in inlinks:
                writer.writerow([page_num, title, url, link['source_title'], link['source_url'], link['anchor_text']])
        else:
            writer.writerow([page_num, title, url, '', '', ''])
            
    return output.getvalue()
