# auto_crecaeru.py （クラウド完全対応・汎用版）

# main.pyの汎用クロール機能を呼び出すために、必要なライブラリをインポート
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import re
import pandas as pd

def crawl_site(site_name, base_url, max_pages=200, status_callback=None):
    """
    main.pyの思想に基づいた、汎用的なクロール関数。
    crecaeru特有の処理を追加。
    """
    
    def log(msg):
        if status_callback:
            status_callback(msg)
        else:
            print(msg)

    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0'})
    domain = urlparse(base_url).netloc.lower().replace('www.', '')

    # 汎用的なURL判定ロジック
    def is_content_url(url):
        try:
            path = urlparse(url).path.lower()
            exclude = [r'\.xml', r'/wp-admin/', r'/wp-content/', r'/feed/', r'\.(jpg|png|pdf)$', r'#', r'\?']
            if any(re.search(p, path) for p in exclude): return False
            return True
        except:
            return False

    # サイトマップからURL収集
    sitemap_urls = set([base_url])
    try:
        res = session.get(urljoin(base_url, '/sitemap.xml'), timeout=20)
        if res.ok:
            soup = BeautifulSoup(res.content, 'lxml')
            for loc in soup.find_all('loc'):
                sitemap_urls.add(loc.text.strip())
    except Exception as e:
        log(f"サイトマップ取得エラー: {e}")
        
    to_visit = [u for u in sitemap_urls if is_content_url(u)][:max_pages]
    log(f"クロール対象URL: {len(to_visit)}件")

    visited = set()
    pages = {}
    all_links = []
    
    for i, url in enumerate(to_visit):
        if url in visited: continue
        
        try:
            log(f"クロール中: {i+1}/{len(to_visit)} - {url[:70]}...")
            
            res = session.get(url, timeout=15)
            if not res.ok: continue
            
            soup = BeautifulSoup(res.text, 'html.parser')
            
            if soup.find('meta', attrs={'name': 'robots', 'content': re.compile(r'noindex', re.I)}):
                continue
                
            title_tag = soup.find('h1') or soup.find('title')
            title = title_tag.get_text(strip=True) if title_tag else url
            title = re.sub(r'\s*[|\-].*$', '', title).strip()
            
            pages[url] = {'title': title}
            
            # --- crecaeru特有の処理 ---
            content_area = soup.select_one('.post_content, .entry-content, main') or soup.body
            # gnavを除外
            if gnav := content_area.select_one('#gnav.l-header__gnav.c-gnavWrap'):
                gnav.decompose()
            # -------------------------

            for a in content_area.find_all('a', href=True):
                href = a.get('href')
                if href and not href.startswith('#'):
                    norm_link = normalize_url(href, base_url)
                    link_domain = urlparse(norm_link).netloc.lower().replace('www.', '')
                    if link_domain == domain and is_content_url(norm_link):
                        all_links.append({
                            'source_url': url, 'source_title': title,
                            'target_url': norm_link,
                            'anchor_text': a.get_text(strip=True) or '[リンク]'
                        })
                        if norm_link not in visited and norm_link not in to_visit and len(to_visit) < max_pages:
                            to_visit.append(norm_link)
            
            visited.add(url)
            time.sleep(0.5)
            
        except Exception as e:
            log(f"エラー: {url} - {e}")

    log("分析データを生成中...")
    
    # DataFrameに変換して返す
    if not all_links:
        return pd.DataFrame()
        
    return pd.DataFrame(all_links)


# ★★★ このファイルが呼び出されたときに実行される本体です ★★★
def analyze(status_callback):
    """
    main.pyの思想に基づき、crecaeruの分析を実行する。
    """
    config = {
        "base_url": "https://kurekaeru.jp",
        "site_name": "クレかえる"
    }

    # 汎用クロール関数を呼び出し
    df_links = crawl_site(config["site_name"], config["base_url"], max_pages=200, status_callback=status_callback)

    if df_links.empty:
        return "" # 空の文字列を返す

    # main.pyのダッシュボードが要求するCSV形式に変換
    
    # ページ情報を作成
    pages = {}
    for _, row in df_links.iterrows():
        pages[row['source_url']] = {'title': row['source_title']}
        pages[row['target_url']] = {'title': "取得中..."} # 仮置き

    # 被リンク数を計算
    target_counts = df_links['target_url'].value_counts().to_dict()

    # CSVデータ生成
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['番号', 'ページタイトル', 'URL', '被リンク元タイトル', '被リンク元URL', 'アンカーテキスト'])

    sorted_targets = sorted(target_counts.items(), key=lambda x: x[1], reverse=True)
    
    row_num = 1
    for target_url, _ in sorted_targets:
        target_title = pages.get(target_url, {}).get('title', target_url)
        
        for _, link in df_links[df_links['target_url'] == target_url].iterrows():
            writer.writerow([row_num, target_title, target_url, link['source_title'], link['source_url'], link['anchor_text']])
        row_num += 1

    # 孤立ページ
    for url, info in pages.items():
        if url not in target_counts:
            writer.writerow([row_num, info['title'], url, '', '', ''])
            row_num += 1

    return output.getvalue()
