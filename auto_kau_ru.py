# auto_kau_ru.py （改造後）

# 必要なライブラリのみをインポート
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
import time
import re
import csv
from io import StringIO

# ★★★ このファイルが呼び出されたときに実行される本体です ★★★
def analyze(status_callback):
    """
    kau-ru.co.jp の分析を実行し、結果をCSV文字列で返す関数。
    主のオリジナルのロジックを、一切変更せずに移植。
    """

    # --- 主のオリジナルのコードを、この関数の中にそのまま配置します ---
    
    # ページやリンク情報を保存する変数
    pages = {}
    links = []
    detailed_links = []
    excluded_links_count = 0

    # --- 主のオリジナルの関数群（クロールロジックの心臓部） ---
    # これらは一切変更いたしません。

    def normalize_url(url, base_url_for_relative):
        if not url: return ""
        if url.startswith('/'):
            try:
                base_domain = f"{urlparse(base_url_for_relative).scheme}://{urlparse(base_url_for_relative).netloc}"
                url = base_domain + url
            except: return ""
        try:
            parsed = urlparse(url)
            scheme = 'https'
            netloc = parsed.netloc.replace('www.', '')
            path = parsed.path.rstrip('/')
            if parsed.query:
                query_params = parse_qs(parsed.query)
                for param in ['p', 'page_id', 'cat']:
                    if param in query_params and query_params[param][0].isdigit():
                        return f"{scheme}://{netloc}{path}?{param}={query_params[param][0]}"
                if any(param in query_params for param in ['m', 'author', 'tag']):
                    return f"{scheme}://{netloc}{path}?{parsed.query}"
            return f"{scheme}://{netloc}{path}"
        except: return ""

    def detect_site_type(url):
        domain = urlparse(url).netloc.lower()
        if 'kau-ru.co.jp' in domain: return 'kauru'
        elif 'kaitori-life.com' in domain: return 'kaitori_life'
        elif 'friend-pay.com' in domain: return 'friend_pay'
        elif 'kurekaeru.com' in domain: return 'kurekaeru'
        else: return 'unknown'

    def get_exclude_selectors(site_type):
        base = ['header', 'footer', 'nav', 'aside', '.sidebar', '.widget']
        specific = {
            'kauru': ['.textwidget', '.textwidget.custom-html-widget'],
            'kaitori_life': ['#nav-container.header-style4-animate.animate'],
            'friend_pay': ['.l-header__inner.l-container', '.l-footer__nav', '.c-tabBody.p-postListTabBody'],
            'kurekaeru': ['#gnav.l-header__gnav.c-gnavWrap']
        }
        return base + specific.get(site_type, [])

    def extract_from_sitemap(url, session, base_url_for_relative):
        urls = set()
        try:
            res = session.get(url, timeout=15)
            res.raise_for_status()
            soup = BeautifulSoup(res.content, 'xml')
            locs = soup.find_all('loc')
            if soup.find('sitemapindex'):
                for loc in locs:
                    urls.update(extract_from_sitemap(loc.text.strip(), session, base_url_for_relative))
            else:
                for loc in locs:
                    loc_url = loc.text.strip()
                    if not re.search(r'sitemap.*\.(xml|html)$', loc_url.lower()):
                        urls.add(normalize_url(loc_url, base_url_for_relative))
        except Exception as e:
            status_callback(f"[警告] サイトマップ取得失敗: {url} - {e}")
        return list(urls)

    def generate_seed_urls(base_url, session):
        seed_urls = [normalize_url(base_url, base_url)]
        sitemap_root = urljoin(base_url, '/sitemap.xml')
        sitemap_urls = extract_from_sitemap(sitemap_root, session, base_url)
        seed_urls.extend(sitemap_urls)
        
        wp_sitemaps = ['/wp-sitemap.xml', '/wp-sitemap-posts-post-1.xml', '/sitemap_index.xml', '/post-sitemap.xml', '/sitemap-posttype-post.xml']
        for sitemap_path in wp_sitemaps:
            try:
                additional_urls = extract_from_sitemap(urljoin(base_url, sitemap_path), session, base_url)
                if additional_urls:
                    seed_urls.extend(additional_urls)
                    status_callback(f"{sitemap_path} から {len(additional_urls)} 個のURLを取得")
            except: pass
        
        base_domain = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"
        status_callback("手動URLパターン生成中 (?p=1-30000)...")
        for post_id in range(1, 30001):
            seed_urls.append(f"{base_domain}/media/?p={post_id}")
        
        status_callback(f"総シードURL数: {len(set(seed_urls))}")
        return list(set(seed_urls))

    def is_content(url, base_url_for_relative):
        parsed = urlparse(normalize_url(url, base_url_for_relative))
        path = parsed.path.lower().rstrip('/')
        query = parsed.query.lower()
        if '/site/' in path: return False
        if re.search(r'\.(jpg|jpeg|png|gif|svg|webp|bmp|pdf|docx?|xlsx?|zip|rar|mp4|mp3)$', path, re.IGNORECASE): return False
        if query.startswith('p=') and query[2:].isdigit(): return True
        if query.startswith('page_id=') and query[8:].isdigit(): return True
        if query.startswith('cat=') and query[4:].isdigit(): return True
        if query.startswith('cat=') and len(query) > 4: return True
        if query.startswith('category_name='): return True
        if any(query.startswith(p) for p in ['m=', 'author=', 'tag=']): return True
        if any(re.search(p, path) for p in [r'^/$', r'^$', r'^/blog', r'^/news', r'^/media', r'^/posts', r'^/article', r'^/category/[a-z0-9\-]+$', r'^/[a-z0-9\-]+$']): return True
        if '?utm_' in url or '?fbclid=' in url or '?gclid=' in url: return False
        if any(re.search(p, url.lower()) for p in [r'/sitemap', r'/wp-admin', r'/wp-json', r'#', r'/feed/', r'mailto:', r'tel:', r'/privacy', r'/terms', r'/contact']): return False
        return True

    def is_internal(url, domain, base_url_for_relative):
        try:
            return urlparse(normalize_url(url, base_url_for_relative)).netloc.replace('www.', '') == domain.replace('www.', '')
        except: return False

    def is_attachment_page(soup):
        if not soup.title or not soup.title.string: return False
        title = soup.title.string.strip()
        if '|' in title and title.split('|')[0].strip().endswith('-min'): return True
        return False

    def extract_links(soup, site_type, current_url):
        nonlocal excluded_links_count
        selectors = ['.entry-content', '.post-content', '.content', 'main', 'article']
        exclude_selectors = get_exclude_selectors(site_type)
        
        for selector in selectors:
            areas = soup.select(selector)
            if areas:
                links = []
                for area in areas:
                    for exclude_selector in exclude_selectors:
                        for elem in area.select(exclude_selector):
                            excluded_links_count += len(elem.find_all('a', href=True))
                            elem.decompose()
                    for link in area.find_all('a', href=True):
                        full_url = urljoin(current_url, link['href'])
                        links.append({'url': full_url, 'anchor_text': link.get_text(strip=True) or link.get('title', '') or '[リンク]'})
                if links: return links
        
        all_links = []
        for link in soup.find_all('a', href=True):
            full_url = urljoin(current_url, link['href'])
            all_links.append({'url': full_url, 'anchor_text': link.get_text(strip=True) or link.get('title', '') or '[リンク]'})
        return all_links

    # --- ここからが分析の実行部分です ---
    try:
        base_url = "https://kau-ru.co.jp"
        domain = urlparse(base_url).netloc
        site_type = detect_site_type(base_url)
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})

        to_visit = generate_seed_urls(base_url, session)
        visited = set()
        processed_links = set()
        
        unique_to_visit = []
        seen_urls = set()
        for url in to_visit:
            normalized = normalize_url(url, base_url)
            if normalized and normalized not in seen_urls:
                seen_urls.add(normalized)
                unique_to_visit.append(normalized)
        to_visit = unique_to_visit
        status_callback(f"重複除去後のシードURL数: {len(to_visit)}")

        crawl_count = 0
        while to_visit and crawl_count < 1000: # 上限設定
            url = to_visit.pop(0)
            normalized_url = normalize_url(url, base_url)
            if not normalized_url or normalized_url in visited: continue

            try:
                response = session.get(url, timeout=15)
                if response.status_code != 200: continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                if is_attachment_page(soup): continue
                if 'attachment_id=' in urlparse(response.url).query: continue
                
                extracted = extract_links(soup, site_type, url)
                
                title = soup.title.string.strip() if soup.title and soup.title.string else normalized_url
                for name in ['kau-ru', 'カウール', 'kaitori-life', '買取LIFE', 'friend-pay', 'フレンドペイ', 'kurekaeru', 'クレかえる']:
                    title = re.sub(rf'\s*[|\-]\s*.*{re.escape(name)}.*$', '', title, flags=re.IGNORECASE)
                title = title.strip()
                
                pages[normalized_url] = {'title': title, 'outbound_links': []}

                for link_data in extracted:
                    normalized_link = normalize_url(link_data['url'], base_url)
                    if not normalized_link: continue
                    
                    if is_internal(normalized_link, domain, base_url) and is_content(normalized_link, base_url):
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
                time.sleep(0.1)

            except Exception as e:
                status_callback(f"  - エラー発生: {url} - {e}")
                continue

        for url in pages:
            pages[url]['inbound_links'] = len(set([src for src, tgt in links if tgt == url]))
        
        status_callback(f"分析完了。{len(pages)}ページ、{len(links)}リンクを検出。除外リンク: {excluded_links_count}")

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
    
    page_numbers = {}
    current_page_number = 1
    
    for target_url, _ in sorted_targets:
        target_info = pages.get(target_url, {})
        page_key = (target_info.get('title', target_url), target_url)
        if page_key not in page_numbers:
            page_numbers[page_key] = current_page_number
            current_page_number += 1
            
    for url, info in pages.items():
        if info.get('inbound_links', 0) == 0:
            page_key = (info['title'], url)
            if page_key not in page_numbers:
                page_numbers[page_key] = current_page_number
                current_page_number += 1

    for target_url, links_to_target in sorted_targets:
        target_info = pages.get(target_url, {})
        target_title = target_info.get('title', target_url)
        page_key = (target_title, target_url)
        page_number = page_numbers.get(page_key)
        if page_number:
            for link in links_to_target:
                writer.writerow([page_number, target_title, target_url, link['source_title'], link['source_url'], link['anchor_text']])

    for url, info in pages.items():
        if info.get('inbound_links', 0) == 0:
            page_key = (info['title'], url)
            page_number = page_numbers.get(page_key)
            if page_number:
                writer.writerow([page_number, info['title'], url, '', '', ''])

    return output.getvalue()
