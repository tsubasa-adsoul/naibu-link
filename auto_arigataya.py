# auto_arigataya.py （真の最終完成版・クラウド最適化）

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import re
import csv
from io import StringIO

# ★★★ このファイルが呼び出されたときに実行される本体です ★★★
def analyze_step(state):
    
    # --- 内部で使う関数群（主のオリジナルのロジックを完全に復元） ---
    
    def log(message):
        state['log'].append(f"[{time.strftime('%H:%M:%S')}] {message}")
        if len(state['log']) > 50:
            state['log'] = state['log'][-50:]

    # 主のオリジナルの normalize_url を完全に再現
    def normalize_url(url, base_url_for_relative):
        if not url: return ""
        try:
            # 相対URLを絶対URLに変換
            if not urlparse(url).scheme:
                url = urljoin(base_url_for_relative, url)
            
            parsed = urlparse(url)
            scheme = 'https'
            netloc = parsed.netloc.replace('www.', '')
            path = parsed.path.rstrip('/')
            if '/wp/' in path: path = path.replace('/wp/', '/')
            path = re.sub(r'/+', '/', path)
            if path and not path.endswith('/'): path += '/'
            if not path: path = '/' # ルートの場合
            return f"{scheme}://{netloc}{path}"
        except Exception:
            return ""

    # 主のオリジナルの is_content を完全に再現
    def is_content(url, base_url_for_relative):
        try:
            normalized_url = normalize_url(url, base_url_for_relative)
            path = urlparse(normalized_url).path.lower().split('?')[0].rstrip('/')
            if any(re.search(p, path) for p in [r'^/category/[a-z0-9\-]+/?$', r'^/category/[a-z0-9\-]+/page/\d+/?$', r'^/[a-z0-9\-]+/?$', r'^/$', r'^$']):
                return True
            exclude_patterns = [r'/sitemap', r'sitemap.*\.(xml|html)', r'/page/\d+', r'-mg', r'/site/', r'/wp-', r'/tag/', r'/wp-content', r'/wp-admin', r'/wp-json', r'#', r'\?utm_', r'/feed/', r'mailto:', r'tel:', r'/privacy', r'/terms', r'/contact', r'/go-', r'/redirect', r'/exit', r'/out', r'\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|rar|doc|docx|xls|xlsx)']
            if any(re.search(e, path) for e in exclude_patterns): return False
            return True
        except:
            return False

    # 主のオリジナルの is_noindex_page を完全に再現
    def is_noindex_page(soup):
        try:
            meta_robots = soup.find('meta', attrs={'name': 'robots'})
            if meta_robots and 'noindex' in meta_robots.get('content', '').lower(): return True
            noindex_meta = soup.find('meta', attrs={'name': 'googlebot', 'content': lambda x: x and 'noindex' in x.lower()})
            if noindex_meta: return True
            title = soup.find('title')
            if title and any(k in title.get_text('').lower() for k in ['外部サイト', 'リダイレクト', '移動中', '外部リンク', 'cushion']): return True
            body_text = soup.get_text('').lower()
            if any(p in body_text for p in ['外部サイトに移動します', 'リダイレクトしています', '外部リンクです', '別サイトに移動', 'このリンクは外部サイト']): return True
            return False
        except: return False

    # 主のオリジナルの extract_links を完全に再現
    def extract_links(soup, current_url):
        links = []
        selectors = ['.post_content', '.entry-content', '.article-content', 'main .content', '[class*="content"]', 'main', 'article']
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
            
            sitemap_root = urljoin(base_url, '/sitemap.xml')
            sitemap_urls = set()
            try:
                res = session.get(sitemap_root, timeout=20)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.content, 'xml')
                    for loc in soup.find_all('loc'):
                        sitemap_urls.add(loc.text.strip())
            except Exception as e:
                 log(f"サイトマップ取得失敗: {e}")

            to_visit = list(set([base_url] + list(sitemap_urls)))
            
            state['to_visit'] = [normalize_url(u, base_url) for u in to_visit if normalize_url(u, base_url)]
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
            url = state['to_visit'].pop(0)
            if not url or url in state['visited']: continue

            try:
                log(f"クロール中: {url}")
                response = session.get(url, timeout=20)
                state['visited'].add(url)
                if response.status_code != 200: continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                if is_noindex_page(soup): continue
                
                title = (soup.title.string.strip() if soup.title and soup.title.string else url)
                title = re.sub(r'\s*[|\-]\s*.*(arigataya|ありがたや).*$', '', title, flags=re.IGNORECASE).strip()
                state['pages'][url] = {'title': title, 'outbound_links': []}
                
                extracted = extract_links(soup, url)
                log(f"  -> {len(extracted)}個のリンクを抽出")
                
                new_links_count = 0
                for link_data in extracted:
                    normalized_link = normalize_url(link_data['url'], base_url)
                    if not normalized_link: continue
                    
                    if is_internal(normalized_link, domain) and is_content(normalized_link, base_url):
                        link_key = (url, normalized_link)
                        if link_key not in state['processed_links']:
                            state['processed_links'].add(link_key)
                            state['links'].append((url, normalized_link))
                            state['detailed_links'].append({
                                'source_url': url, 'source_title': title,
                                'target_url': normalized_link, 'anchor_text': link_data['anchor_text']
                            })
                        if normalized_link not in state['visited'] and normalized_link not in state['to_visit']:
                            state['to_visit'].append(normalized_link)
                            new_links_count += 1
                if new_links_count > 0:
                    log(f"  -> {new_links_count}個の新しいURLを発見")

                crawled_in_this_step += 1
                time.sleep(0.5) # クラウド環境のため、より長く待機
            except Exception as e:
                log(f"クロールエラー: {url} - {e}")
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

# ★★★ CSV生成用の関数 ★★★
def generate_csv(state):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['番号', 'ページタイトル', 'URL', '被リンク元タイトル', '被リンク元URL', 'アンカーテキスト'])
    
    pages = state['pages']
    detailed_links = state['detailed_links']
    links = state['links']
    
    for url in pages:
        pages[url]['inbound_links'] = len(set(src for src, tgt in links if tgt == url))
    
    unique_pages = sorted(pages.items(), key=lambda item: item[1].get('inbound_links', 0), reverse=True)
    page_number_map = {url: i for i, (url, _) in enumerate(unique_pages, 1)}

    for link in detailed_links:
        target_url = link.get('target_url')
        if target_url in page_number_map:
            page_number = page_number_map[target_url]
            target_title = pages.get(target_url, {}).get('title', target_url)
            writer.writerow([page_number, target_title, target_url, link.get('source_title', ''), link.get('source_url', ''), link.get('anchor_text', '')])
    
    for url, info in pages.items():
        if info.get('inbound_links', 0) == 0:
            page_number = page_number_map.get(url)
            if page_number:
                writer.writerow([page_number, info['title'], url, '', '', ''])

    return output.getvalue()
