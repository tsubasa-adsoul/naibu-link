# bic-gift.py （改造後）

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
    bic-gift.co.jp の分析を実行し、結果をCSV文字列で返す関数。
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
        path = re.sub(r'/+', '/', path)
        return f"{scheme}://{netloc}{path}"

    def extract_from_sitemap(url, session):
        urls = set()
        try:
            res = session.get(url, timeout=15)
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
        
        allow_patterns = [r'^/$', r'^$', r'^/blog$', r'^/blog/[a-z0-9\-_]+$', r'^/[a-z0-9\-_]+$', r'^/category/[a-z0-9\-_]+$', r'^/category/[a-z0-9\-_]+/page/\d+$', r'^/blog/category/[a-z0-9\-_]+$', r'^/blog/category/[a-z0-9\-_]+/page/\d+$']
        if any(re.search(p, path) for p in allow_patterns):
            return True
        
        exclude_patterns = [r'/sitemap', r'sitemap.*\.(xml|html)', r'/page/\d+', r'/site/', r'/wp-', r'/tag/', r'/wp-content', r'/wp-admin', r'/wp-json', r'#', r'\?utm_', r'/feed/', r'mailto:', r'tel:', r'/privacy', r'/terms', r'/contact', r'/about', r'/company', r'/profiles', r'/disclaimer', r'/law\.php', r'\.php$', r'/go-', r'/redirect', r'/exit', r'/out', r'/search', r'/author/', r'/date/', r'\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|rar|doc|docx|xls|xlsx)']
        if any(re.search(e, path) for e in exclude_patterns):
            return False
        
        return True

    def is_noindex_page(soup):
        try:
            meta_robots = soup.find('meta', attrs={'name': 'robots'})
            if meta_robots and 'noindex' in meta_robots.get('content', '').lower():
                return True
            noindex_meta = soup.find('meta', attrs={'name': 'googlebot', 'content': lambda x: x and 'noindex' in x.lower()})
            if noindex_meta:
                return True
            return False
        except:
            return False

    def extract_links(soup, current_url):
        selectors = ['.entry-content', '.post-content', '.content', '.article-content', '.main-content', '.post-body', '.entry-body', 'main .content', '[class*="content"]', '.single-content', '.page-content', 'main', 'article']
        for selector in selectors:
            areas = soup.select(selector)
            if areas:
                links = []
                for area in areas:
                    for exclude in area.select('header, footer, nav, aside, .sidebar, .widget, .share, .related, .popular-posts, .breadcrumb, .author-box, .navigation, .sns, .sns-share, .social-share, .entry-footer, .entry-meta, .post-meta, .category-list, .tag-list'):
                        exclude.decompose()
                    for link in area.find_all('a', href=True):
                        href = link['href']
                        if (href and not href.startswith('#') and '/site/' not in href and not any(d in href for d in ['facebook.com', 'twitter.com', 'x.com', 'line.me', 'hatena.ne.jp', 'instagram.com', 'getpocket.com', 'youtube.com'])):
                            full_url = urljoin(current_url, href)
                            links.append({'url': full_url, 'anchor_text': link.get_text(strip=True) or link.get('title', '') or '[リンク]'})
                if links:
                    return links
        
        for exclude in soup.select('header, footer, nav, aside, .sidebar, .widget, .share, .related, .popular-posts, .breadcrumb, .author-box, .navigation, .sns, .entry-footer, .post-meta'):
            exclude.decompose()
        all_links = []
        for link in soup.find_all('a', href=True):
            href = link['href']
            if (href and not href.startswith('#') and '/site/' not in href and not any(d in href for d in ['facebook.com', 'twitter.com', 'x.com', 'line.me', 'hatena.ne.jp'])):
                full_url = urljoin(current_url, href)
                all_links.append({'url': full_url, 'anchor_text': link.get_text(strip=True) or link.get('title', '') or '[リンク]'})
        return all_links

    def is_internal(url, domain):
        return urlparse(url).netloc.replace('www.', '') == domain.replace('www.', '')

    # --- ここからが分析の実行部分です ---
    try:
        base_url = "https://bic-gift.co.jp"
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
                title = re.sub(r'\s*[|\-]\s*.*(bic-gift|ビックギフト).*$', '', title, flags=re.IGNORECASE)
                
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
    # 主のオリジナルのCSV書き出しロジックを再現
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['A_番号', 'B_ページタイトル', 'C_URL', 'D_被リンク元ページタイトル', 'E_被リンク元ページURL', 'F_被リンク元ページアンカーテキスト'])
    
    target_groups = {}
    for link in detailed_links:
        target_url = link['target_url']
        if target_url not in target_groups: target_groups[target_url] = []
        target_groups[target_url].append(link)
    
    sorted_targets = sorted(target_groups.items(), key=lambda x: len(x[1]), reverse=True)
    
    row_number = 1
    # 主のロジックでは連番が連続してしまうため、main.py側で番号を振るように変更します
    for target_url, links_to_target in sorted_targets:
        target_title = pages.get(target_url, {}).get('title', target_url)
        for link in links_to_target:
            writer.writerow(['', target_title, target_url, link['source_title'], link['source_url'], link['anchor_text']])
    
    for url, info in pages.items():
        if info.get('inbound_links', 0) == 0:
            writer.writerow(['', info['title'], url, '', '', ''])

    return output.getvalue()
