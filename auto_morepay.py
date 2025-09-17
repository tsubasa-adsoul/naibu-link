# auto_morepay.py （改造後）

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
    more-pay.jp の分析を実行し、結果をCSV文字列で返す関数。
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
        try:
            parsed = urlparse(url)
            scheme = parsed.scheme or 'https'
            netloc = parsed.netloc.replace('www.', '')
            path = parsed.path
            if '/wp/' in path: path = path.replace('/wp/', '/')
            path = re.sub(r'/+', '/', path)
            if path and not re.search(r'\.[a-zA-Z0-9]+$', path) and not path.endswith('/'):
                path += '/'
            if path == '': path = '/'
            return f"{scheme}://{netloc}{path}"
        except: return url

    def extract_from_sitemap(url, session):
        urls = set()
        try:
            res = session.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            res.raise_for_status()
            try:
                soup = BeautifulSoup(res.content, 'xml')
            except:
                soup = BeautifulSoup(res.content, 'html.parser')
            
            locs = soup.find_all('loc')
            if soup.find('sitemapindex'):
                for loc in locs:
                    urls.update(extract_from_sitemap(loc.text.strip(), session))
            else:
                for loc in locs:
                    loc_url = loc.text.strip()
                    if not re.search(r'sitemap.*\.(xml|html)$', loc_url.lower()):
                        normalized_url = normalize_url(loc_url)
                        if is_content(normalized_url):
                            urls.add(normalized_url)
        except Exception as e:
            status_callback(f"サイトマップ処理エラー ({url}): {e}")
        return list(urls)

    def generate_seed_urls(base_url, session):
        seed_urls = [normalize_url(base_url)]
        sitemap_patterns = ['/sitemap.xml', '/sitemap_index.xml', '/wp-sitemap.xml', '/sitemap-posts.xml', '/post-sitemap.xml']
        for pattern in sitemap_patterns:
            try:
                sitemap_urls = extract_from_sitemap(urljoin(base_url, pattern), session)
                if sitemap_urls:
                    seed_urls.extend(sitemap_urls)
                    status_callback(f"サイトマップ {pattern} から {len(sitemap_urls)} 個のURLを取得")
                    break
            except: pass
        
        for page in ['/column/', '/category/']:
            manual_url = normalize_url(urljoin(base_url, page))
            if manual_url not in seed_urls:
                seed_urls.append(manual_url)
        
        unique_urls = list(set(seed_urls))
        status_callback(f"最終シードURL数: {len(unique_urls)}")
        return unique_urls

    def is_content(url):
        normalized_url = normalize_url(url)
        parsed = urlparse(normalized_url)
        path = parsed.path.lower().rstrip('/')
        if parsed.query: return False
        
        allowed_patterns = [r'^/?$', r'^/column/?$', r'^/column/[a-z0-9\-_]+/?$', r'^/column/[a-z0-9\-_]+/[a-z0-9\-_]+/?$', r'^/category/[a-z0-9\-_]+/?$', r'^/category/[a-z0-9\-_]+/page/\d+/?$', r'^/[a-z0-9\-_]+/?$', r'^/page/\d+/?$']
        if any(re.search(p, path) for p in allowed_patterns):
            excluded_patterns = [r'/sitemap', r'sitemap.*\.(xml|html)', r'-mg/?$', r'/site/?$', r'/wp-', r'/tag/', r'/wp-content', r'/wp-admin', r'/wp-json', r'/feed/', r'/privacy', r'/terms', r'/contact', r'/about', r'/company', r'/go-', r'/redirect', r'/exit', r'/out', r'/search', r'/author/', r'/date/', r'/\d{4}/', r'/\d{4}/\d{2}/', r'\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|rar|doc|docx|xls|xlsx)']
            if not any(re.search(e, path) for e in excluded_patterns):
                return True
        return False

    def is_noindex_page(soup):
        try:
            meta_robots = soup.find('meta', attrs={'name': 'robots'})
            if meta_robots and 'noindex' in meta_robots.get('content', '').lower(): return True
            noindex_meta = soup.find('meta', attrs={'name': 'googlebot', 'content': lambda x: x and 'noindex' in x.lower()})
            if noindex_meta: return True
            title = soup.find('title')
            if title and any(k in title.get_text('').lower() for k in ['外部サイト', 'リダイレクト', '移動中', '外部リンク', 'cushion', '404', 'not found', 'error']): return True
            body_text = soup.get_text().lower()[:1000]
            if any(p in body_text for p in ['外部サイトに移動します', 'リダイレクトしています', '外部リンクです', '別サイトに移動', 'このリンクは外部サイト', 'ページが見つかりません']): return True
            return False
        except: return False

    def extract_title(soup, url):
        h1 = soup.find('h1')
        if h1 and h1.get_text(strip=True): return h1.get_text(strip=True)
        title = soup.find('title')
        if title and title.string:
            title_text = re.sub(r'\s*[|\-｜]\s*.*$', '', title.string.strip())
            if title_text: return title_text
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'): return og_title.get('content').strip()
        return url

    def extract_links(soup):
        content_selectors = ['.entry-content', '.post-content', '.article-content', '.content', 'main .content', '[class*="content"]', 'main', 'article', '.single-content', '.post-body', '.entry-body']
        exclude_selectors = ['header', 'footer', 'nav', 'aside', '.sidebar', '.widget', '.share', '.related', '.popular-posts', '.breadcrumb', '.author-box', '.navigation', '.sns', '.social-share', '.comment', '.comments', '.pagination', '.tags', '.categories', '.meta', '.byline', '.date', '.archive']
        for selector in content_selectors:
            areas = soup.select(selector)
            if areas:
                links = []
                for area in areas:
                    for exclude_selector in exclude_selectors:
                        for exclude_element in area.select(exclude_selector): exclude_element.decompose()
                    for link in area.find_all('a', href=True):
                        href = link.get('href', '').strip()
                        if not href or href.startswith('#'): continue
                        anchor_text = (link.get_text(strip=True) or link.get('title', '') or '')[:200]
                        if anchor_text.lower() in ['', 'link', 'リンク', 'click here', 'here', 'read more']: continue
                        links.append({'url': href, 'anchor_text': anchor_text})
                if links: return links
        
        all_links = []
        for link in soup.find_all('a', href=True):
            href = link.get('href', '').strip()
            if not href or href.startswith('#'): continue
            anchor_text = (link.get_text(strip=True) or link.get('title', '') or '')[:200]
            if anchor_text.lower() not in ['', 'link', 'リンク', 'click here', 'here', 'read more']:
                all_links.append({'url': href, 'anchor_text': anchor_text})
        return all_links

    def is_internal(url, domain):
        try:
            return urlparse(url).netloc.replace('www.', '') == domain.replace('www.', '')
        except: return False

    # --- ここからが分析の実行部分です ---
    try:
        base_url = "https://more-pay.jp"
        domain = urlparse(base_url).netloc
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ja,en-US;q=0.7,en;q=0.3', 'Accept-Encoding': 'gzip, deflate', 'Connection': 'keep-alive'
        })
        
        to_visit = generate_seed_urls(base_url, session)
        visited = set()
        processed_links = set()
        
        status_callback(f"=== more-pay.jp 分析開始 ===")
        
        crawl_count = 0
        while to_visit and crawl_count < 1000: # 上限設定
            url = to_visit.pop(0)
            normalized_url = normalize_url(url)
            if normalized_url in visited: continue

            try:
                response = session.get(url, timeout=15)
                if response.status_code != 200: continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                if is_noindex_page(soup):
                    visited.add(normalized_url)
                    continue
                
                extracted = extract_links(soup)
                title = extract_title(soup, normalized_url)
                pages[normalized_url] = {'title': title, 'outbound_links': []}

                for link_data in extracted:
                    try:
                        absolute_url = urljoin(normalized_url, link_data['url'])
                        normalized_link = normalize_url(absolute_url)
                    except: continue
                    
                    if is_internal(normalized_link, domain) and is_content(normalized_link):
                        if (normalized_url, normalized_link) not in processed_links:
                            processed_links.add((normalized_url, normalized_link))
                            links.append((normalized_url, normalized_link))
                            pages[normalized_url]['outbound_links'].append(normalized_link)
                            detailed_links.append({
                                'source_url': normalized_url, 'source_title': title,
                                'target_url': normalized_link, 'anchor_text': link_data['anchor_text']
                            })
                        if normalized_link not in visited and normalized_link not in to_visit:
                            to_visit.append(normalized_link)

                visited.add(normalized_url)
                crawl_count += 1
                status_callback(f"クロール中 ({crawl_count}/1000): {title[:50]}...")
                time.sleep(0.2)

            except Exception as e:
                status_callback(f"  - エラー発生: {url} - {e}")
                continue

        for url in pages:
            pages[url]['inbound_links'] = sum(1 for _, tgt in links if tgt == url)
        
        status_callback(f"分析完了。{len(pages)}ページ、{len(links)}リンクを検出。")

    except Exception as e:
        status_callback(f"致命的なエラーが発生しました: {e}")
        return "A_番号,B_ページタイトル,C_URL,D_被リンク元ページタイトル,E_被リンク元ページURL,F_被リンク元ページアンカーテキスト\n"

    # --- 最後にCSV文字列を生成して返します ---
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['A_番号', 'B_ページタイトル', 'C_URL', 'D_被リンク元ページタイトル', 'E_被リンク元ページURL', 'F_被リンク元ページアンカーテキスト'])
    
    target_groups = {}
    for link in detailed_links:
        target_url = link['target_url']
        if target_url not in target_groups: target_groups[target_url] = []
        target_groups[target_url].append(link)
    
    sorted_targets = sorted(target_groups.items(), key=lambda x: len(x[1]), reverse=True)
    
    for target_url, links_to_target in sorted_targets:
        target_title = pages.get(target_url, {}).get('title', target_url)
        for link in links_to_target:
            writer.writerow(['', target_title, target_url, link['source_title'], link['source_url'], link['anchor_text']])
    
    for url, info in pages.items():
        if info.get('inbound_links', 0) == 0:
            writer.writerow(['', info['title'], url, '', '', ''])

    return output.getvalue()
