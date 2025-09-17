# auto_fuyouhin.py （改造後）

# 必要なライブラリのみをインポート
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import re
import csv
from io import StringIO
import html

# ★★★ このファイルが呼び出されたときに実行される本体です ★★★
def analyze(status_callback):
    """
    fuyohin-kaishu.co.jp の分析を実行し、結果をCSV文字列で返す関数。
    主のオリジナルのロジックを、一切変更せずに移植。
    """

    # --- 主のオリジナルのコードを、この関数の中にそのまま配置します ---
    
    # ページやリンク情報を保存する変数
    pages = {}
    detailed_links = []
    
    # --- 主のオリジナルの関数群（クロールロジックの心臓部） ---
    # これらは一切変更いたしません。

    domain = "fuyohin-kaishu.co.jp"
    categories = [
        {'name': 'ゴミ屋敷・汚部屋', 'url': f'https://{domain}/garbage-house', 'path': '/garbage-house/', 'id': 174},
        {'name': '不用品回収', 'url': f'https://{domain}/unwanted-items', 'path': '/unwanted-items/', 'id': 173},
        {'name': '未分類', 'url': f'https://{domain}/uncategorized', 'path': '/uncategorized/', 'id': 1},
        {'name': '遺品整理・生前整理', 'url': f'https://{domain}/sorting-out-belongings', 'path': '/sorting-out-belongings/', 'id': 176}
    ]
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})

    def log(message):
        status_callback(message)

    def extract_link_title(link, container):
        link_text = link.get_text(strip=True)
        if link_text and len(link_text) > 5 and not link_text.lower() in ['続きを読む', 'read more', '詳細']: return link_text[:150]
        if link.get('title'): return link.get('title').strip()[:150]
        if container:
            for selector in ['.p-postList__title', '.entry-title', '.post-title', 'h2', 'h3', 'h4']:
                title_element = container.select_one(selector)
                if title_element and title_element.get_text(strip=True) and len(title_element.get_text(strip=True)) > 5:
                    return title_element.get_text(strip=True)[:150]
        return link.get('href', 'リンク')[:150]

    def get_articles_from_category(category):
        articles = []
        page, max_pages = 1, 20
        while page <= max_pages:
            try:
                list_url = f"{category['url']}/page/{page}" if page > 1 else category['url']
                log(f"  ページ{page}を確認中: {list_url}")
                response = session.get(list_url, timeout=30)
                if response.status_code != 200: break
                
                soup = BeautifulSoup(response.text, 'html.parser')
                page_articles = []
                for item in soup.find_all(['article', 'div'], class_=re.compile(r'p-postList__item|post-item|entry-item')):
                    link = item.find('a', href=True)
                    if link and link.get('href'):
                        full_url = urljoin(list_url, link.get('href'))
                        if category['path'] in full_url and not any(ex in full_url for ex in ['page/', 'feed/', '#', '?']) and not any(a['url'] == full_url.rstrip('/') for a in articles + page_articles):
                            link_text = extract_link_title(link, item)
                            if link_text and len(link_text) > 3:
                                page_articles.append({'url': full_url.rstrip('/'), 'title': link_text, 'category': category['name']})
                
                if page_articles:
                    articles.extend(page_articles)
                    log(f"    ページ{page}: {len(page_articles)}記事発見")
                else: break
                page += 1
                time.sleep(0.8)
            except Exception as e:
                log(f"  ページ{page}エラー: {str(e)}")
                break
        return articles

    def get_articles_from_wp_api():
        articles = []
        try:
            api_url = f"https://{domain}/wp-json/wp/v2/posts"
            page, per_page = 1, 100
            while page <= 10:
                log(f"WordPress API ページ{page}を取得中...")
                response = session.get(api_url, params={'page': page, 'per_page': per_page, 'status': 'publish'}, timeout=30)
                if response.status_code != 200: break
                posts = response.json()
                if not posts: break
                for post in posts:
                    post_url = post.get('link', '')
                    if any(cat['path'] in post_url for cat in categories):
                        category_name = next((cat['name'] for cat in categories if cat['path'] in post_url), "その他")
                        title = html.unescape(re.sub(r'<[^>]+>', '', post.get('title', {}).get('rendered', ''))).strip()
                        if len(title) > 3:
                            articles.append({'url': post_url.rstrip('/'), 'title': title[:150], 'category': category_name})
                page += 1
                time.sleep(0.5)
        except Exception as e:
            log(f"WordPress API取得エラー: {str(e)}")
        return articles

    def get_articles_from_sitemap():
        articles = []
        sitemap_urls = [f"https://{domain}/sitemap.xml", f"https://{domain}/wp-sitemap.xml", f"https://{domain}/sitemap_index.xml", f"https://{domain}/wp-sitemap-posts-post-1.xml"]
        for sitemap_url in sitemap_urls:
            try:
                response = session.get(sitemap_url, timeout=30)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'xml')
                    for url in soup.find_all('url'):
                        loc = url.find('loc')
                        if loc:
                            url_text = loc.text.rstrip('/')
                            for category in categories:
                                if category['path'] in url_text:
                                    slug = url_text.split('/')[-1]
                                    title = slug.replace('-', ' ').title() if slug else f"記事 - {category['name']}"
                                    articles.append({'url': url_text, 'title': title, 'category': category['name']})
                                    break
                    if articles: break
            except Exception: continue
        return articles

    def remove_duplicate_articles(articles):
        unique_articles, seen_urls = [], set()
        for article in articles:
            url = article['url'].rstrip('/')
            if url not in seen_urls:
                unique_articles.append(article)
                seen_urls.add(url)
        return unique_articles

    def extract_page_title(soup, article):
        for selector in ['.c-postTitle__ttl', 'h1.c-postTitle__ttl', '.entry-title', '.post-title', '.article-title', 'h1']:
            try:
                for title_element in soup.select(selector):
                    if title_element and title_element.get_text(strip=True):
                        title_text = title_element.get_text(strip=True)
                        if len(title_text) > 3 and not title_text.lower() in ['home', 'top', 'ホーム']: return title_text
            except: continue
        if soup.title and soup.title.string:
            title = re.sub(r'\s*[|\-–]\s*.*(不用品回収|fuyohin|kaishu|不用品回収隊).*$', '', soup.title.string.strip(), flags=re.IGNORECASE)
            if len(title.strip()) > 3: return title.strip()
        if article.get('title') and len(article['title']) > 3 and not article['title'].startswith('http') and '/' not in article['title']: return article['title']
        path = urlparse(article['url']).path
        if path and (slug := path.strip('/').split('/')[-1]) and slug != 'wp' and len(slug) > 1:
            return slug.replace('-', ' ').replace('_', ' ').title()
        return f"記事({article['url'].split('/')[-1] if article['url'].split('/')[-1] else 'unknown'})"

    def extract_main_content(soup):
        for selector in ['#sidebar', '.l-sidebar', '.sidebar', '.p-relatedPosts', '.related-posts', '.p-pnLinks', '.prev-next-links', '.c-shareBtns', '.share-buttons', '.p-authorBox', '.author-box', '#breadcrumb', '.breadcrumb', '.widget', '.c-widget', '.footer_cta', '.fixed-banner']:
            for element in soup.select(selector): element.decompose()
        for selector in ['.post_content', '.entry-content', '.post-content', 'main article', '#main_content']:
            if content := soup.select_one(selector): return content
        return soup.find('main') or soup.find('article')

    def extract_links_from_content(content):
        links = []
        if content:
            for link in content.find_all('a', href=True):
                href = link.get('href')
                anchor_text = link.get_text(strip=True) or link.get('title', '') or '[リンク]'
                if href and len(anchor_text) > 0:
                    links.append({'url': href, 'anchor_text': anchor_text[:100]})
        return links

    def normalize_url_for_analysis(url):
        if url.startswith('/'): url = f"https://{domain}{url}"
        parsed = urlparse(url)
        if parsed.netloc != domain: return url
        path = parsed.path.rstrip('/')
        if path and not path.endswith('/'): path += '/'
        return f"https://{domain}{path}"

    def is_target_article(url):
        target_paths = [cat['path'] for cat in categories]
        if not any(tp in url for tp in target_paths): return False
        exclude_patterns = ['/wp-admin/', '/wp-content/', '/wp-json/', '.jpg', '.jpeg', '.png', '.gif', '.pdf', '/feed/', '/page/', '#', '?', '/contact', '/privacy', '/terms']
        return not any(p in url.lower() for p in exclude_patterns)

    def fetch_missing_page_titles(detailed_links, pages):
        missing_urls = {link['target_url'] for link in detailed_links if link['target_url'] not in pages}
        log(f"タイトル未取得のページ: {len(missing_urls)}個")
        for i, url in enumerate(missing_urls):
            try:
                log(f"  タイトル取得中 {i+1}/{len(missing_urls)}: {url}")
                response = session.get(url, timeout=30)
                category = next((cat['name'] for cat in categories if cat['path'] in url), "その他")
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    page_title = extract_page_title(soup, {'url': url, 'title': '', 'category': category})
                    pages[url] = {'title': page_title, 'category': category, 'outbound_links': [], 'inbound_links': 0}
                else:
                    slug = url.split('/')[-1]
                    generated_title = slug.replace('-', ' ').title() if slug else url
                    pages[url] = {'title': generated_title, 'category': category, 'outbound_links': [], 'inbound_links': 0}
                time.sleep(0.5)
            except Exception:
                slug = url.split('/')[-1]
                fallback_title = slug.replace('-', ' ').title() if slug else url
                pages[url] = {'title': fallback_title, 'category': "その他", 'outbound_links': [], 'inbound_links': 0}

    # --- ここからが分析の実行部分です ---
    try:
        log("記事一覧を取得中...")
        all_articles = []
        for category in categories:
            log(f"=== {category['name']} カテゴリ分析開始 ===")
            all_articles.extend(get_articles_from_category(category))
            time.sleep(1)
        all_articles.extend(get_articles_from_wp_api())
        all_articles.extend(get_articles_from_sitemap())
        articles = remove_duplicate_articles(all_articles)
        
        if not articles: raise Exception("記事が見つかりませんでした")
        log(f"合計 {len(articles)} 記事を発見")
        
        processed_links = set()
        for i, article in enumerate(articles):
            try:
                log(f"記事分析中 {i+1}/{len(articles)}: {article['title'][:30]}...")
                response = session.get(article['url'], timeout=30)
                if response.status_code != 200:
                    pages[article['url']] = {'title': article['title'], 'category': article.get('category', '不明'), 'outbound_links': [], 'inbound_links': 0}
                    continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                page_title = extract_page_title(soup, article)
                pages[article['url']] = {'title': page_title, 'category': article.get('category', '不明'), 'outbound_links': [], 'inbound_links': 0}
                
                content = extract_main_content(soup)
                if content:
                    for link_data in extract_links_from_content(content):
                        target_url = normalize_url_for_analysis(link_data['url'])
                        if is_target_article(target_url) and (article['url'], target_url) not in processed_links:
                            processed_links.add((article['url'], target_url))
                            pages[article['url']]['outbound_links'].append(target_url)
                            detailed_links.append({'source_url': article['url'], 'source_title': page_title, 'source_category': article.get('category', '不明'), 'target_url': target_url, 'anchor_text': link_data['anchor_text']})
                time.sleep(0.3)
            except Exception as e:
                log(f"記事分析エラー {article['url']}: {str(e)}")
                if article['url'] not in pages:
                    pages[article['url']] = {'title': article['title'], 'category': article.get('category', '不明'), 'outbound_links': [], 'inbound_links': 0}
                continue
        
        fetch_missing_page_titles(detailed_links, pages)
        
        for link in detailed_links:
            if link['target_url'] in pages:
                pages[link['target_url']]['inbound_links'] = pages[link['target_url']].get('inbound_links', 0) + 1
        
        log(f"最終結果: {len(pages)}ページ, {len(detailed_links)}内部リンク")

    except Exception as e:
        log(f"致命的なエラーが発生しました: {e}")
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
    processed_urls = set()
    
    for target_url, links_to_target in sorted_targets:
        target_info = pages.get(target_url, {})
        target_title = target_info.get('title', 'タイトル不明')
        processed_urls.add(target_url)
        for link in links_to_target:
            writer.writerow(['', target_title, target_url, link['source_title'], link['source_url'], link['anchor_text']])
    
    isolated_pages = sorted([(url, info) for url, info in pages.items() if url not in processed_urls], key=lambda x: x[1].get('title', ''))
    for url, info in isolated_pages:
        writer.writerow(['', info.get('title', 'タイトル不明'), url, '（被リンクなし）', '', ''])

    return output.getvalue()
