# famipay.py （改造後）

# 必要なライブラリのみをインポート
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import time
import re
import csv
from io import StringIO

# ★★★ このファイルが呼び出されたときに実行される本体です ★★★
def analyze(status_callback):
    """
    famipay (flashpay.jp/famipay/) の分析を実行し、結果をCSV文字列で返す関数。
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
        path = re.sub(r'/+', '/', parsed.path.rstrip('/'))
        return f"{scheme}://{netloc}{path}"

    def is_internal(url, domain):
        parsed_url = urlparse(url)
        url_domain = parsed_url.netloc.replace('www.', '')
        target_domain = domain.replace('www.', '')
        return url_domain == target_domain

    def extract_links_for_crawling(soup, current_url):
        all_links = soup.find_all('a', href=True)
        valid_links = []
        for link in all_links:
            href = link.get('href', '')
            if (href and not href.startswith('#') and '/site/' not in href and not any(d in href for d in ['facebook.com', 'twitter.com', 'x.com', 'line.me', 'hatena.ne.jp'])):
                valid_links.append(urljoin(current_url, href))
        return valid_links

    def extract_links_for_analysis(soup, current_url):
        content_area = soup.select_one('.entry-content')
        if not content_area: return []
        valid_links = []
        for link in content_area.find_all('a', href=True):
            href = link.get('href', '')
            if (href and not href.startswith('#') and '/site/' not in href and 'respond' not in href and is_internal(urljoin(current_url, href), 'flashpay.jp')):
                anchor_text = link.get_text(strip=True) or link.get('title', '') or '[リンク]'
                valid_links.append({'url': urljoin(current_url, href), 'anchor_text': anchor_text[:100]})
        return valid_links

    def is_content(url):
        normalized_url = normalize_url(url)
        path = urlparse(normalized_url).path.lower().split('?')[0].rstrip('/')
        if path == '/famipay': return True
        return path.startswith('/famipay/') and re.match(r'^/famipay/[a-z0-9\-]+$', path)

    def is_noindex_page(soup):
        try:
            meta_robots = soup.find('meta', attrs={'name': 'robots'})
            if meta_robots and 'noindex' in meta_robots.get('content', '').lower(): return True
            noindex_meta = soup.find('meta', attrs={'name': 'googlebot', 'content': lambda x: x and 'noindex' in x.lower()})
            if noindex_meta: return True
            return False
        except:
            return False

    # --- ここからが分析の実行部分です ---
    try:
        base_url = "https://flashpay.jp/famipay/"
        domain = urlparse(base_url).netloc
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})
        
        # 第1段階: ページを収集
        status_callback("フェーズ1: ページ収集中...")
        to_visit = [normalize_url(base_url)]
        visited = set()
        
        crawl_count = 0
        while to_visit and crawl_count < 500: # 上限設定
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

                title = soup.title.string.strip() if soup.title and soup.title.string else normalized_url
                title = re.sub(r'\s*[|\-]\s*.*(famipay|ファミペイ|flashpay|フラッシュペイ).*$', '', title, flags=re.IGNORECASE)
                
                pages[normalized_url] = {'title': title, 'outbound_links': []}

                extracted_links = extract_links_for_crawling(soup, url)
                for link in extracted_links:
                    normalized_link = normalize_url(link)
                    if '/site/' in normalized_link: continue
                    if (is_internal(normalized_link, domain) and is_content(normalized_link) and normalized_link not in visited and normalized_link not in to_visit):
                        to_visit.append(normalized_link)

                visited.add(normalized_url)
                crawl_count += 1
                status_callback(f"ページ収集 ({crawl_count}/500): {normalized_url[:60]}...")
                time.sleep(0.1)
                
            except Exception as e:
                status_callback(f"  - エラー: {url} - {e}")
                continue

        # 第2段階: リンク関係を構築
        status_callback(f"フェーズ2: リンク関係構築中 ({len(pages)}ページ)...")
        processed_links = set()
        
        for i, url in enumerate(list(pages.keys())):
            try:
                status_callback(f"リンク解析中 ({i+1}/{len(pages)}): {url[:60]}...")
                response = session.get(url, timeout=15)
                if response.status_code != 200: continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                extracted_analysis_links = extract_links_for_analysis(soup, url)
                
                for link_data in extracted_analysis_links:
                    normalized_link = normalize_url(link_data['url'])
                    if '/site/' in normalized_link: continue
                    if normalized_link not in pages: continue
                    if normalized_link == url: continue

                    if (url, normalized_link) not in processed_links:
                        processed_links.add((url, normalized_link))
                        links.append((url, normalized_link))
                        pages[url]['outbound_links'].append(normalized_link)
                        detailed_links.append({
                            'source_url': url, 'source_title': pages[url]['title'],
                            'target_url': normalized_link, 'anchor_text': link_data['anchor_text']
                        })
            except Exception as e:
                status_callback(f"  - リンク解析エラー: {url} - {e}")
                continue

        for url in pages:
            pages[url]['inbound_links'] = len(set([src for src, tgt in links if tgt == url]))
            
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
    
    # main.py側で番号を振るため、ここでは番号を空にします
    for target_url, links_to_target in sorted_targets:
        target_title = pages.get(target_url, {}).get('title', target_url)
        for link in links_to_target:
            writer.writerow(['', target_title, target_url, link['source_title'], link['source_url'], link['anchor_text']])
    
    for url, info in pages.items():
        if info.get('inbound_links', 0) == 0:
            writer.writerow(['', info['title'], url, '', '', ''])

    return output.getvalue()
