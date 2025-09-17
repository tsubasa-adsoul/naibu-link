# arigataya.py （改造後）

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
    arigataya.co.jp の分析を実行し、結果をCSV文字列で返す関数。
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
        parsed = urlparse(url)
        scheme = 'https'
        netloc = parsed.netloc.replace('www.', '')
        path = parsed.path.rstrip('/')
        if '/wp/' in path: path = path.replace('/wp/', '/')
        path = re.sub(r'/+', '/', path)
        if path and not path.endswith('/'): path += '/'
        return f"{scheme}://{netloc}{path}"

    def extract_from_sitemap(url, session):
        urls = set()
        try:
            res = session.get(url, timeout=15) # タイムアウトを少し延長
            res.raise_for_status()
            soup = BeautifulSoup(res.content, 'xml')
            locs = soup.find_all('loc')
            if soup.find('sitemapindex'):
                for loc in locs:
                    urls.update(extract_from_sitemap(loc.text.strip(), session))
            else:
                for loc in locs:
                    loc_url = loc.text.strip()
                    if not re.search(r'sitemap.*\.(xml|html)$', loc_url.lower()):
                        urls.add(normalize_url(loc_url))
        except Exception as e:
            status_callback(f"[警告] サイトマップ取得失敗: {url} - {e}")
        return list(urls)

    def generate_seed_urls(base_url, session):
        sitemap_root = urljoin(base_url, '/sitemap.xml')
        sitemap_urls = extract_from_sitemap(sitemap_root, session)
        status_callback(f"サイトマップから {len(sitemap_urls)} 個のURLを取得")
        return list(set([normalize_url(base_url)] + sitemap_urls))

    def is_content(url):
        normalized_url = normalize_url(url)
        path = urlparse(normalized_url).path.lower().split('?')[0].rstrip('/')
        if any(re.search(p, path) for p in [r'^/category/[a-z0-9\-]+', r'^/category/[a-z0-9\-]+/page/\d+', r'^/[a-z0-9\-]+', r'^/$', r'^$']):
            return True
        if any(re.search(e, path) for e in [r'/sitemap', r'sitemap.*\.(xml|html)', r'/page/\d+', r'-mg', r'/site/', r'/wp-', r'/tag/', r'/wp-content', r'/wp-admin', r'/wp-json', r'#', r'\?utm_', r'/feed/', r'mailto:', r'tel:', r'/privacy', r'/terms', r'/contact', r'/go-', r'/redirect', r'/exit', r'/out', r'\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|rar|doc|docx|xls|xlsx)']):
            return False
        return True

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
        except:
            return False
            
    def extract_links(soup, current_url):
        selectors = ['.post_content', '.entry-content', '.article-content', 'main .content', '[class*="content"]', 'main', 'article']
        for selector in selectors:
            areas = soup.select(selector)
            if areas:
                links = []
                for area in areas:
                    for exclude in area.select('header, footer, nav, aside, .sidebar, .widget, .share, .related, .popular-posts, .breadcrumb, .author-box, .navigation'):
                        exclude.decompose()
                    for link in area.find_all('a', href=True):
                        full_url = urljoin(current_url, link['href'])
                        links.append({'url': full_url, 'anchor_text': link.get_text(strip=True) or link.get('title', '') or '[リンク]'})
                    for element in area.find_all(attrs={'onclick': True}):
                        match = re.search(r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]", element.get('onclick', ''))
                        if match:
                            full_url = urljoin(current_url, match.group(1))
                            links.append({'url': full_url, 'anchor_text': element.get_text(strip=True) or element.get('title', '') or '[onclick リンク]'})
                if links: return links
        
        all_links = []
        for link in soup.find_all('a', href=True):
            full_url = urljoin(current_url, link['href'])
            all_links.append({'url': full_url, 'anchor_text': link.get_text(strip=True) or link.get('title', '') or '[リンク]'})
        for element in soup.find_all(attrs={'onclick': True}):
            match = re.search(r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]", element.get('onclick', ''))
            if match:
                full_url = urljoin(current_url, match.group(1))
                all_links.append({'url': full_url, 'anchor_text': element.get_text(strip=True) or element.get('title', '') or '[onclick リンク]'})
        return all_links

    def is_internal(url, domain):
        return urlparse(url).netloc.replace('www.', '') == domain.replace('www.', '')
        
    # --- ここからが分析の実行部分です ---
    try:
        base_url = "https://arigataya.co.jp"
        domain = urlparse(base_url).netloc
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})

        to_visit = generate_seed_urls(base_url, session)
        visited = set()
        processed_links = set()
        
        unique_to_visit = []
        seen_urls = set()
        for url in to_visit:
            normalized = normalize_url(url)
            if normalized not in seen_urls:
                seen_urls.add(normalized)
                unique_to_visit.append(normalized)
        to_visit = unique_to_visit
        status_callback(f"重複除去後のシードURL数: {len(to_visit)}")

        crawl_count = 0
        while to_visit and crawl_count < 500: # 上限設定
            url = to_visit.pop(0)
            normalized_url = normalize_url(url)
            if normalized_url in visited:
                continue

            try:
                response = session.get(url, timeout=15)
                if response.status_code != 200: continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                if is_noindex_page(soup):
                    visited.add(normalized_url)
                    continue
                
                extracted = extract_links(soup, url)
                
                title = soup.title.string.strip() if soup.title and soup.title.string else normalized_url
                title = re.sub(r'\s*[|\-]\s*.*(arigataya|ありがたや).*$', '', title, flags=re.IGNORECASE)
                
                pages[normalized_url] = {'title': title, 'outbound_links': []}

                for link_data in extracted:
                    normalized_link = normalize_url(link_data['url'])
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
                status_callback(f"クロール中 ({crawl_count}/500): {normalized_url[:70]}...")
                time.sleep(0.1)

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
    
    unique_pages = sorted(pages.items(), key=lambda item: item[1].get('inbound_links', 0), reverse=True)
    page_number_map = {url: i for i, (url, _) in enumerate(unique_pages, 1)}

    for link in detailed_links:
        target_url = link.get('target_url', '')
        if target_url in page_number_map:
            page_number = page_number_map[target_url]
            target_title = pages.get(target_url, {}).get('title', target_url)
            writer.writerow([page_number, target_title, target_url, link.get('source_title', ''), link.get('source_url', ''), link.get('anchor_text', '')])
    
    for url, info in pages.items():
        if info.get('inbound_links', 0) == 0:
            page_number = page_number_map.get(url, 0)
            if page_number:
                writer.writerow([page_number, info['title'], url, '', '', ''])

    return output.getvalue()
