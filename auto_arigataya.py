# auto_arigataya.py （真の最終完成版・ロジック完全再現）

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import re
import csv
from io import StringIO

def analyze_step(state):
    
    def log(message):
        state['log'].append(f"[{time.strftime('%H:%M:%S')}] {message}")
        if len(state['log']) > 100:
            state['log'] = state['log'][-100:]

    def normalize_url(url, base_url_for_relative):
        if not url or not isinstance(url, str): return ""
        try:
            if not urlparse(url).scheme:
                url = urljoin(base_url_for_relative, url)
            
            parsed = urlparse(url)
            scheme = 'https'
            netloc = parsed.netloc.lower().replace('www.', '')
            path = parsed.path.rstrip('/')
            if '/wp/' in path: path = path.replace('/wp/', '/')
            path = re.sub(r'/+', '/', path)
            if not path: path = '/'
            return f"{scheme}://{netloc}{path}"
        except Exception:
            return ""

    def is_content(url, base_url_for_relative):
        try:
            normalized_url = normalize_url(url, base_url_for_relative)
            if not normalized_url: return False
            path = urlparse(normalized_url).path.lower().split('?')[0].rstrip('/')
            if any(re.search(p, path) for p in [r'^/category/[a-z0-9\-]+/?$', r'^/category/[a-z0-9\-]+/page/\d+/?$', r'^/[a-z0-9\-]+/?$', r'^/$', r'^$']):
                return True
            exclude_patterns = [r'/sitemap', r'\.xml', r'/page/\d+', r'-mg', r'/site/', r'/wp-', r'/tag/', r'/wp-content', r'/wp-admin', r'/wp-json', r'#', r'\?utm_', r'/feed/', r'mailto:', r'tel:', r'/privacy', r'/terms', r'/contact', r'/go-', r'/redirect', r'/exit', r'/out', r'\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|rar|doc|docx|xls|xlsx)']
            if any(re.search(e, path) for e in exclude_patterns): return False
            return True
        except:
            return False

    def is_noindex_page(soup):
        try:
            meta_robots = soup.find('meta', attrs={'name': 'robots'})
            if meta_robots and 'noindex' in meta_robots.get('content', '').lower(): return True
            return False
        except: return False

    def extract_links(soup, current_url):
        links = []
        selectors = ['.post_content', '.entry-content', '.article-content', 'main']
        content_area = None
        for selector in selectors:
            content_area = soup.select_one(selector)
            if content_area: break
        if not content_area: content_area = soup.body
        
        for exclude in content_area.select('header, footer, nav, aside, .sidebar, .widget, .share, .related, .popular-posts, .breadcrumb, .author-box, .navigation'):
            exclude.decompose()
        for link in content_area.find_all('a', href=True):
            links.append({'url': link['href'], 'anchor_text': link.get_text(strip=True) or link.get('title', '') or '[リンク]'})
        for element in content_area.find_all(attrs={'onclick': True}):
            match = re.search(r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]", element.get('onclick', ''))
            if match:
                links.append({'url': match.group(1), 'anchor_text': element.get_text(strip=True) or element.get('title', '') or '[onclick リンク]'})
        return links

    def is_internal(url, domain):
        try: return urlparse(url).netloc.replace('www.', '') == domain.replace('www.', '')
        except: return False

    # --- フェーズ管理 ---
    
    if state['phase'] == 'initializing':
        log("フェーズ1: シードURLの生成を開始します。")
        try:
            base_url = "https://arigataya.co.jp"
            session = requests.Session()
            session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
            
            sitemap_urls = set()
            sitemap_root = urljoin(base_url, '/sitemap.xml')
            try:
                res = session.get(sitemap_root, timeout=20)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.content, 'xml')
                    for loc in soup.find_all('loc'):
                        sitemap_urls.add(loc.text.strip())
            except Exception as e:
                 log(f"サイトマップ取得失敗: {e}")

            initial_urls = list(set([base_url] + list(sitemap_urls)))
            
            state['to_visit'] = [u for u in initial_urls if u]
            state['session'] = session
            state['base_url'] = base_url
            state['domain'] = urlparse(base_url).netloc
            state['crawl_limit'] = 800
            state['phase'] = 'crawling'
            log(f"シードURLを{len(state['to_visit'])}件生成。クロールを開始します。")
        except Exception as e:
            log(f"初期化エラー: {e}")
            state['phase'] = 'error'
        return state

    if state['phase'] == 'crawling':
        crawl_batch_size = 5
        session = state['session']
        base_url = state['base_url']
        domain = state['domain']
        
        crawled_in_this_step = 0
        while state['to_visit'] and len(state['pages']) < state['crawl_limit'] and crawled_in_this_step < crawl_batch_size:
            url_to_crawl = state['to_visit'].pop(0)
            normalized_url = normalize_url(url_to_crawl, base_url)
            if not normalized_url or normalized_url in state['visited']: continue

            try:
                log(f"クロール中: {normalized_url}")
                response = session.get(normalized_url, timeout=20)
                state['visited'].add(normalized_url)
                if response.status_code != 200: continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                if is_noindex_page(soup): continue
                
                title = (soup.title.string.strip() if soup.title and soup.title.string else normalized_url)
                title = re.sub(r'\s*[|\-]\s*.*(arigataya|ありがたや).*$', '', title, flags=re.IGNORECASE).strip()
                
                # この時点でページを確定
                if normalized_url not in state['pages']:
                    state['pages'][normalized_url] = {'title': title, 'outbound_links': []}
                
                extracted = extract_links(soup, normalized_url)
                
                new_links_count = 0
                for link_data in extracted:
                    target_normalized_url = normalize_url(link_data['url'], base_url)
                    if not target_normalized_url: continue
                    
                    if is_internal(target_normalized_url, domain) and is_content(target_normalized_url, base_url):
                        link_key = (normalized_url, target_normalized_url)
                        if link_key not in state['processed_links']:
                            state['processed_links'].add(link_key)
                            state['links'].append(link_key)
                            state['detailed_links'].append({
                                'source_url': normalized_url, 'source_title': title,
                                'target_url': target_normalized_url, 'anchor_text': link_data['anchor_text']
                            })
                        
                        # ★★★ ここが最重要修正点 ★★★
                        # 新しいクロール対象を追加するロジック
                        if target_normalized_url not in state['visited'] and target_normalized_url not in state['to_visit']:
                            state['to_visit'].append(target_normalized_url)
                            new_links_count += 1
                
                if new_links_count > 0:
                    log(f"  -> {new_links_count}個の新しいURLを発見")

                crawled_in_this_step += 1
                time.sleep(0.5)
            except Exception as e:
                log(f"クロールエラー: {url_to_crawl} - {e}")
                continue
        
        total_known_urls = len(state['to_visit']) + len(state['visited'])
        progress = len(state['visited']) / total_known_urls if total_known_urls > 0 else 0
        state['progress'] = progress
        state['progress_text'] = f"クロール中: {len(state['visited'])} / {total_known_urls} (発見済み)"
        
        if not state['to_visit'] or len(state['pages']) >= state['crawl_limit']:
            log(f"クロール完了。{len(state['pages'])}ページを発見。最終処理に入ります。")
            state['phase'] = 'completed'
        
        return state

    return state

def generate_csv(state):
    # (この関数は変更なし)
    pass
