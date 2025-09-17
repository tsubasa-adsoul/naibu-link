# auto_crecaeru.py （真の最終・完成版・ロジック完全復元）

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

    # ★★★ ここが全ての元凶であり、完全に修正した心臓部です ★★★
    def is_content(url, base_url):
        """主のオリジナルの、寛容な判定ロジックを完全に復元"""
        try:
            normalized_url = normalize_url(url, base_url)
            if not normalized_url: return False
            path = urlparse(normalized_url).path.lower().split('?')[0].rstrip('/')
            
            # まず重要なページを明示的に許可
            if any(re.search(p, path) for p in [r'^/category/[a-z0-9\-]+/?$', r'^/category/[a-z0-9\-]+/page/\d+/?$', r'^/[a-z0-9\-]+/?$', r'^/$', r'^$']):
                return True
            
            # 除外パターンをチェック
            exclude_patterns = [r'/sitemap', r'\.xml', r'/page/\d+', r'-mg', r'/site/', r'/wp-', r'/tag/', r'/wp-content', r'/wp-admin', r'/wp-json', r'#', r'\?utm_', r'/feed/', r'mailto:', r'tel:', r'/privacy', r'/terms', r'/contact', r'/go-', r'/redirect', r'/exit', r'/out', r'\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|rar|doc|docx|xls|xlsx)']
            if any(re.search(e, path) for e in exclude_patterns):
                return False
            
            # 上記のいずれでもなければ、許可する（主のオリジナルの思想）
            return True
        except:
            return False

    def is_noindex_page(soup):
        return soup.find('meta', attrs={'name': 'robots', 'content': re.compile(r'noindex', re.I)})

    # nonlocal変数を正しく扱うため、analyze_step直下で定義
    excluded_links_count = state.get('excluded_links_count', 0)
    def extract_links(soup, base_url):
        nonlocal excluded_links_count
        links = []
        selectors = ['.post_content', '.entry-content', 'main']
        content_area = None
        for selector in selectors:
            content_area = soup.select_one(selector)
            if content_area: break
        if not content_area: content_area = soup.body
        
        # gnavを除外
        if gnav := content_area.select_one('#gnav.l-header__gnav.c-gnavWrap'):
            excluded_links_count += len(gnav.find_all('a', href=True))
            gnav.decompose()
        
        for exclude in content_area.select('header, footer, nav, aside, .sidebar, .widget, .share, .related'):
            exclude.decompose()
            
        for a in content_area.find_all('a', href=True):
            links.append({'url': a['href'], 'anchor_text': a.get_text(strip=True) or a.get('title', '')})
        for element in content_area.find_all(attrs={'onclick': True}):
            match = re.search(r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]", element.get('onclick', ''))
            if match: links.append({'url': match.group(1), 'anchor_text': element.get_text(strip=True) or '[onclick]'})
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
                    if loc := sitemap.find('loc'): urls.update(extract_from_sitemap_recursively(loc.text.strip(), session))
            else:
                for url_tag in soup.find_all('url'):
                    if loc := url_tag.find('loc'): urls.add(loc.text.strip())
        except Exception as e:
            log(f"サイトマップ解析エラー: {sitemap_url} - {e}")
        return urls

    if state['phase'] == 'initializing':
        log("フェーズ1: 記事URLの収集を開始します。")
        try:
            # ★★★ ドメインを完全に修正 ★★★
            base_url = "https://crecaeru.co.jp"
            session = requests.Session()
            session.headers.update({'User-Agent': 'Mozilla/5.0'})
            
            sitemap_urls = extract_from_sitemap_recursively(urljoin(base_url, '/sitemap.xml'), session)
            initial_urls = list(set([base_url] + list(sitemap_urls)))
            
            state.update({
                'session': session, 'base_url': base_url, 'domain': urlparse(base_url).netloc.lower().replace('www.', ''),
                'to_visit': [u for u in initial_urls if is_content(u, base_url)],
                'visited': set(), 'pages': {}, 'links': [], 'phase': 'crawling', 'crawl_limit': 800, 'excluded_links_count': 0
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
        
        while state['to_visit'] and crawled_count < 10:
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
                title = re.sub(r'\s*\|.*(crecaeru|クレかえる).*$', '', title, flags=re.IGNORECASE).strip()
                state['pages'][url] = {'title': title}
                
                for link in extract_links(soup, base_url):
                    norm_link = normalize_url(link['url'], base_url)
                    if norm_link and norm_link.startswith(f"https://{domain}") and is_content(norm_link, base_url):
                        state['links'].append({
                            'source_url': url, 'source_title': title,
                            'target_url': norm_link, 'anchor_text': link['anchor_text']
                        })
                        if norm_link not in state['visited'] and norm_link not in state['to_visit']:
                            state['to_visit'].append(norm_link)
                
                crawled_count += 1
                time.sleep(0.3)
            except Exception as e:
                log(f"クロールエラー: {url} - {e}")
        
        state['excluded_links_count'] = excluded_links_count
        total_urls = len(state['visited']) + len(state['to_visit'])
        state['progress'] = len(state['visited']) / total_urls if total_urls > 0 else 1
        state['progress_text'] = f"進捗: {len(state['visited'])} / {total_urls} ページ"

        if not state['to_visit']:
            log("クロール完了。")
            state['phase'] = 'completed'
        return state

    return state

def generate_csv(state):
    # (この関数は変更なし)
    pass
