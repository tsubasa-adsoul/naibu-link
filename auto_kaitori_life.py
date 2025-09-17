# auto_kaitori_life.py （改造後）

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
    kaitori-life.co.jp の分析を実行し、結果をCSV文字列で返す関数。
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
            path = re.sub(r'/+', '/', path)
            return f"{scheme}://{netloc}{path}"
        except: return ""

    def detect_site_type(url):
        domain = urlparse(url).netloc.lower()
        if 'kaitori-life.co.jp' in domain or 'kaitori-life.com' in domain: return 'kaitori_life'
        elif 'kau-ru.co.jp' in domain: return 'kauru'
        elif 'friend-pay.com' in domain: return 'friend_pay'
        elif 'kurekaeru.com' in domain: return 'kurekaeru'
        else: return 'unknown'

    def get_exclude_selectors(site_type):
        base = ['header', 'footer', 'nav', 'aside', '.sidebar', '.widget', '.share', '.related', '.popular-posts', '.breadcrumb', '.author-box', '.navigation', '.sns', '.sns-top']
        specific = {
            'kaitori_life': ['#nav-container.header-style4-animate.animate'],
            'kauru': ['.textwidget', '.textwidget.custom-html-widget'],
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
        status_callback(f"サイトマップから {len(sitemap_urls)} 個のURLを取得")
        return list(set(seed_urls))

    def is_content(url, base_url_for_relative):
        if not url: return False
        try:
            parsed = urlparse(normalize_url(url, base_url_for_relative))
            path = parsed.path.lower().rstrip('/')
            
            allow_patterns = [r'^/$', r'^$', r'^/[a-z0-9\-]+$', r'^/[a-z0-9\-_]+$', r'^/category/[a-z0-9\-]+$', r'^/category/[a-z0-9\-]+/page/\d+$', r'^/credit-list$', r'^/method$', r'^/purchase$', r'^/how_to$', r'^/manual$', r'^/media$']
            if any(re.search(p, path) for p in allow_patterns): return True
            
            exclude_patterns = [r'/sitemap', r'/wp-admin', r'/wp-json', r'/wp-content', r'#', r'/feed/', r'mailto:', r'tel:', r'/privacy', r'/terms', r'/contact', r'/profiles', r'/disclaimer', r'/law\.php', r'\.php$', r'/go-', r'/redirect', r'/exit', r'/out', r'/site/', r'/tag/', r'/page/\d+$', r'\.(jpg|jpeg|png|gif|svg|webp|bmp|pdf|docx?|xlsx?|zip|rar|mp4|mp3)']
            if any(re.search(p, path) for p in exclude_patterns): return False
            
            if '?utm_' in url or '?fbclid=' in url or '?gclid=' in url: return False
            return True
        except: return False

    def is_noindex_page(soup):
        try:
            meta_robots = soup.find('meta', attrs={'name': 'robots'})
            if meta_robots and 'noindex' in meta_robots.get('content', '').lower(): return True
            title = soup.find('title')
            if title and any(k in title.get_text('').lower() for k in ['外部サイト', 'リダイレクト', '移動中', '外部リンク', 'cushion']): return True
            body_text = soup.get_text('').lower()
            if any(p in body_text for p in ['外部サイトに移動します', 'リダイレクトしています', '外部リンクです', '別サイトに移動', 'このリンクは外部サイト']): return True
            return False
        except: return False

    def is_internal(url, domain, base_url_for_relative):
        try:
            return urlparse(normalize_url(url, base_url_for_relative)).netloc.replace('www.', '') == domain.replace('www.', '')
        except: return False

    def extract_links(soup, site_type, current_url):
        nonlocal excluded_links_count
        selectors = ['.cps-post-main .entry-content', '.entry-content', '.post-content', '.article-content', 'main .content', '[class*="content"]', 'main', 'article']
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
                        href = link['href']
                        if (href and not href.startswith('#') and '/site/' not in href and not any(d in href for d in ['facebook.com', 'twitter.com', 'x.com', 'line.me', 'hatena.ne.jp', 'instagram.com', 'getpocket.com'])):
                            full_url = urljoin(current_url, href)
                            links.append({'url': full_url, 'anchor_text': link.get_text(strip=True) or link.get('title', '') or '[リンク]'})
                if links: return links
        
        all_links = []
        for link in soup.find_all('a', href=True):
            href = link['href']
            if (href and not href.startswith('#') and '/site/' not in href and not any(d in href for d in ['facebook.com', 'twitter.com', 'x.com', 'line.me', 'hatena.ne.jp'])):
                full_url = urljoin(current_url, href)
                all_links.append({'url': full_url, 'anchor_text': link.get_text(strip=True) or link.get('title', '') or '[リンク]'})
        return all_links

    # --- ここからが分析の実行部分です ---
    try:
        base_url = "https://kaitori-life.co.jp"
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
        while to_visit and crawl_count < 500: # 上限設定
            url = to_visit.pop(0)
            normalized_url = normalize_url(url, base_url)
            if not normalized_url or normalized_url in visited: continue

            try:
                response = session.get(url, timeout=15)
                if response.status_code != 200: continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                if is_noindex_page(soup):
                    visited.add(normalized_url)
                    continue
                
                extracted = extract_links(soup, site_type, url)
                
                title = soup.title.string.strip() if soup.title and soup.title.string else normalized_url
                for name in ['kaitori-life', '買取LIFE', 'kau-ru', 'カウール']:
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
                status_callback(f"クロール中 ({crawl_count}/500): {title[:50]}...")
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
