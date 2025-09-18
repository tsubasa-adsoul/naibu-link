import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import re
import csv
from io import StringIO

def analyze_step(state):
    
    def log(message):
        if 'log' not in state: state['log'] = []
        state['log'].append(f"[{time.strftime('%H:%M:%S')}] {message}")
        if len(state['log']) > 100: state['log'] = state['log'][-100:]

    def normalize_url(url):
        # ローカル版と全く同じ正規化ロジック
        parsed = urlparse(url)
        scheme = 'https'
        netloc = parsed.netloc.replace('www.', '')
        path = parsed.path.rstrip('/')

        # crecaeru.com専用の正規化
        if '/wp/' in path:
            path = path.replace('/wp/', '/')

        # 重複スラッシュを修正
        path = re.sub(r'/+', '/', path)

        # トップページ以外には末尾スラッシュを付与
        if path and not path.endswith('/'):
            path += '/'

        return f"{scheme}://{netloc}{path}"

    def is_content(url):
        # ローカル版のis_contentロジックを完全コピー
        normalized_url = normalize_url(url)
        path = urlparse(normalized_url).path.lower().split('?')[0].rstrip('/')
        
        # まず重要なページを明示的に許可
        if any(re.search(pattern, path) for pattern in [
            r'^/category/[a-z0-9\-]+$',           # カテゴリページ
            r'^/category/[a-z0-9\-]+/page/\d+$',  # カテゴリページネーション
            r'^/[a-z0-9\-]+$',                    # 記事ページ
            r'^/$',                               # トップページ
            r'^$'                                 # ルート
        ]):
            return True
        
        # 除外パターンをチェック
        if any(re.search(e, path) for e in [
            r'/sitemap',                    # sitemap を含むパス全て
            r'sitemap.*\.(xml|html)$',      # sitemap.xml, sitemap-*.html 等
            r'/page/\d+$',                  # ページネーション（カテゴリ以外）
            r'-mg',                         # -mg を含むURL
            r'/site/',                      # /site/ を含むURL
            r'/wp-',                        # WordPress関連
            r'/tag/',                       # タグページ
            r'/wp-content',                 # WordPress コンテンツ
            r'/wp-admin',                   # WordPress 管理画面
            r'/wp-json',                    # WordPress JSON API
            r'#',                           # アンカーリンク
            r'\?utm_',                      # UTMパラメータ
            r'/feed/',                      # RSS/Atom フィード
            r'mailto:',                     # メールリンク
            r'tel:',                        # 電話リンク
            r'/privacy',                    # プライバシーポリシー
            r'/terms',                      # 利用規約
            r'/contact',                    # お問い合わせ
            r'/go-',                        # クッションページ（go-で始まる）
            r'/redirect',                   # リダイレクトページ
            r'/exit',                       # 離脱ページ
            r'/out',                        # 外部リンクページ
            r'\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|rar|doc|docx|xls|xlsx)$'  # ファイル
        ]):
            return False
        
        # その他は基本的に許可（記事ページの可能性が高い）
        return True

    def is_noindex_page(soup):
        """ローカル版のNOINDEXページ判定をコピー"""
        try:
            # robots meta タグをチェック
            meta_robots = soup.find('meta', attrs={'name': 'robots'})
            if meta_robots and meta_robots.get('content'):
                content = meta_robots.get('content').lower()
                if 'noindex' in content:
                    return True
            
            # 個別のnoindex meta タグもチェック
            noindex_meta = soup.find('meta', attrs={'name': 'googlebot', 'content': lambda x: x and 'noindex' in x.lower()})
            if noindex_meta:
                return True
                
            return False
            
        except Exception as e:
            return False

    def extract_links(soup):
        """ローカル版のリンク抽出ロジックを完全コピー"""
        selectors = [
            '.post_content',           # crecaeru専用
            '.entry-content',          # WordPress一般
            '.article-content',        # 記事コンテンツ
            'main .content',           # メインコンテンツ
            '[class*="content"]',      # content を含むクラス
            'main',                    # メインエリア
            'article'                  # 記事エリア
        ]
        
        for selector in selectors:
            areas = soup.select(selector)
            if areas:
                links = []
                for area in areas:
                    # 元の除外処理 + gnav除外
                    for exclude in area.select('header, footer, nav, aside, .sidebar, .widget, .share, .related, .popular-posts, .breadcrumb, .author-box, .navigation, #gnav.l-header__gnav.c-gnavWrap'):
                        exclude.decompose()
                    
                    # 1. 通常のaタグリンクを抽出
                    found_links = area.find_all('a', href=True)
                    for link in found_links:
                        anchor_text = link.get_text(strip=True) or link.get('title', '') or '[リンク]'
                        links.append({
                            'url': link['href'],
                            'anchor_text': anchor_text[:100]
                        })
                    
                    # 2. onclick属性のあるタグを抽出（crecaeru特有）
                    onclick_elements = area.find_all(attrs={'onclick': True})
                    for element in onclick_elements:
                        onclick_attr = element.get('onclick', '')
                        # "window.location.href='URL'" からURLを抽出
                        url_match = re.search(r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]", onclick_attr)
                        if url_match:
                            extracted_url = url_match.group(1)
                            anchor_text = element.get_text(strip=True) or element.get('title', '') or '[onclick リンク]'
                            links.append({
                                'url': extracted_url,
                                'anchor_text': anchor_text[:100]
                            })
                    
                if links:
                    return links
        
        return []

    def extract_from_sitemap(url):
        # ローカル版のサイトマップ抽出をコピー
        urls = set()
        try:
            res = requests.get(url, timeout=10)
            res.raise_for_status()
            soup = BeautifulSoup(res.content, 'xml')
            locs = soup.find_all('loc')
            if soup.find('sitemapindex'):
                for loc in locs:
                    urls.update(extract_from_sitemap(loc.text.strip()))
            else:
                for loc in locs:
                    loc_url = loc.text.strip()
                    # サイトマップファイル自体は除外
                    if not re.search(r'sitemap.*\.(xml|html)$', loc_url.lower()):
                        urls.add(normalize_url(loc_url))
        except Exception as e:
            log(f"サイトマップ取得エラー: {e}")
        return list(urls)

    def generate_seed_urls(base_url):
        # ローカル版のシードURL生成をコピー
        sitemap_root = urljoin(base_url, '/sitemap.xml')
        sitemap_urls = extract_from_sitemap(sitemap_root)
        log(f"サイトマップから {len(sitemap_urls)} 個のURLを取得")
        
        # サイトマップが空の場合、手動でURLを追加
        if len(sitemap_urls) == 0:
            log("サイトマップが空のため、手動でURLを追加します")
            manual_urls = [
                "https://crecaeru.co.jp/",
                "https://crecaeru.co.jp/arigataya/",
                "https://crecaeru.co.jp/more-pay/",
                "https://crecaeru.co.jp/pay-ful/",
                "https://crecaeru.co.jp/category/sakibarai-kaitori/",
                "https://crecaeru.co.jp/yarikuri/"
            ]
            return manual_urls
        
        return list(set([normalize_url(base_url)] + sitemap_urls))

    def is_internal(url, domain):
        return urlparse(url).netloc.replace('www.', '') == domain.replace('www.', '')

    if state['phase'] == 'initializing':
        log("フェーズ1: 記事URLの収集を開始します。")
        try:
            base_url = "https://crecaeru.co.jp"
            
            pages = {}
            links = []
            detailed_links = []  # 詳細リンク情報用
            visited = set()
            to_visit = generate_seed_urls(base_url)
            domain = urlparse(base_url).netloc
            processed_links_list = []  # set()の代わりにlistで管理

            session = requests.Session()
            session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})

            log(f"初期シードURL数: {len(to_visit)}")
            
            # 重複を除去
            unique_to_visit = []
            seen = set()
            for url in to_visit:
                normalized = normalize_url(url)
                if normalized not in seen:
                    seen.add(normalized)
                    unique_to_visit.append(normalized)
            
            to_visit = unique_to_visit
            log(f"重複除去後のシードURL数: {len(to_visit)}")
            
            state.update({
                'session': session, 'base_url': base_url, 'domain': domain,
                'to_visit': to_visit, 'visited': list(visited), 'pages': pages, 
                'links': links, 'detailed_links': detailed_links, 
                'processed_links_list': processed_links_list,  # listとして保存
                'phase': 'crawling'
            })
            
        except Exception as e:
            log(f"初期化エラー: {e}")
            state['phase'] = 'error'
        return state

    if state['phase'] == 'crawling':
        # ステートから値を取得
        session = state['session']
        base_url = state['base_url']
        domain = state['domain']
        to_visit = state['to_visit']
        visited = set(state.get('visited', []))  # listからsetに変換
        pages = state['pages']
        links = state['links']
        detailed_links = state['detailed_links']
        processed_links_list = state.get('processed_links_list', [])
        
        # 処理済みリンクをsetに変換（高速化のため）
        processed_links = set()
        for link_pair in processed_links_list:
            if isinstance(link_pair, (list, tuple)) and len(link_pair) == 2:
                processed_links.add(tuple(link_pair))
        
        crawled_count = 0
        new_processed_links = []  # 新規追加分を記録
        
        while to_visit and len(pages) < 500 and crawled_count < 10:
            url = to_visit.pop(0)
            normalized_url = normalize_url(url)
            if normalized_url in visited:
                continue

            try:
                response = session.get(url, timeout=10)
                if response.status_code != 200:
                    continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # NOINDEXページを除外
                if is_noindex_page(soup):
                    log(f"NOINDEXページをスキップ: {url}")
                    visited.add(normalized_url)
                    continue
                
                # 新しいリンクを発見
                extracted_links = extract_links(soup)

                # ページ情報を保存
                title = soup.title.string.strip() if soup.title and soup.title.string else normalized_url
                
                # crecaeru | クレかえる などのサイト名を除去
                title = re.sub(r'\s*[|\-]\s*.*(crecaeru|クレかえる|crecaeru|クレカエル).*$', '', title, flags=re.IGNORECASE)
                
                pages[normalized_url] = {
                    'title': title,
                    'outbound_links': []
                }

                # このページからの内部リンクを記録
                link_count_for_this_page = 0
                for link_data in extracted_links:
                    link_url = link_data['url']
                    anchor_text = link_data['anchor_text']
                    
                    # 相対URLを絶対URLに変換
                    if not link_url.startswith(('http://', 'https://')):
                        link_url = urljoin(normalized_url, link_url)
                    
                    normalized_link = normalize_url(link_url)
                    
                    if (is_internal(normalized_link, domain) and 
                        is_content(normalized_link)):
                        
                        # 重複チェック（同じソース→ターゲットのリンクは1回だけ）
                        link_key = (normalized_url, normalized_link)
                        if link_key not in processed_links:
                            processed_links.add(link_key)
                            new_processed_links.append(list(link_key))  # listとして保存
                            
                            links.append((normalized_url, normalized_link))
                            pages[normalized_url]['outbound_links'].append(normalized_link)
                            
                            # 詳細リンク情報を保存
                            detailed_links.append({
                                'source_url': normalized_url,
                                'source_title': title,
                                'target_url': normalized_link,
                                'anchor_text': anchor_text
                            })
                            link_count_for_this_page += 1
                        
                        # 新規URLの発見
                        if (normalized_link not in visited and 
                            normalized_link not in to_visit):
                            to_visit.append(normalized_link)

                visited.add(normalized_url)
                crawled_count += 1
                log(f"{len(pages)}件目: {title[:30]}... ({link_count_for_this_page}個のリンクを抽出)")

                time.sleep(0.1)

            except Exception as e:
                log(f"エラー: {url} - {e}")
                continue

        # 被リンク数を計算
        for url in pages:
            pages[url]['inbound_links'] = sum(1 for _, tgt in links if tgt == url)

        # 処理済みリンクリストを更新
        processed_links_list.extend(new_processed_links)
        
        # state更新
        state.update({
            'pages': pages, 
            'links': links, 
            'detailed_links': detailed_links,
            'to_visit': to_visit, 
            'visited': list(visited),  # setからlistに変換して保存
            'processed_links_list': processed_links_list,  # listとして保存
            'phase': 'crawling' if to_visit else 'completed'
        })

        total_urls = len(visited) + len(to_visit)
        state['progress'] = len(visited) / total_urls if total_urls > 0 else 1
        state['progress_text'] = f"進捗: {len(visited)} / {total_urls} ページ"

        if not to_visit or len(pages) >= 500:
            log(f"クロール完了。総ページ数: {len(pages)}, 総リンク数: {len(links)}")
            state['phase'] = 'completed'
        
        return state

    return state

def generate_csv(state):
    # ローカル版のCSV生成ロジックを完全コピー
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['A_番号', 'B_ページタイトル', 'C_URL', 'D_被リンク元ページタイトル', 'E_被リンク元ページURL', 'F_被リンク元ページアンカーテキスト'])
    
    pages = state.get('pages', {})
    detailed_links = state.get('detailed_links', [])
    
    if not pages: 
        return output.getvalue()

    # ターゲットURL別にグループ化
    target_groups = {}
    for link in detailed_links:
        target_url = link['target_url']
        if target_url not in target_groups:
            target_groups[target_url] = []
        target_groups[target_url].append(link)
    
    # 被リンク数でソート
    sorted_targets = sorted(target_groups.items(), key=lambda x: len(x[1]), reverse=True)
    
    # ページ番号マッピング作成（同じタイトル+URLには同じ番号）
    page_numbers = {}
    current_page_number = 1
    
    # 被リンクありページの番号割り当て
    for target_url, links_to_target in sorted_targets:
        target_info = pages.get(target_url, {})
        target_title = target_info.get('title', target_url)
        page_key = (target_title, target_url)
        
        if page_key not in page_numbers:
            page_numbers[page_key] = current_page_number
            current_page_number += 1
    
    # 孤立ページの番号割り当て
    for url, info in pages.items():
        if info.get('inbound_links', 0) == 0:
            page_key = (info['title'], url)
            if page_key not in page_numbers:
                page_numbers[page_key] = current_page_number
                current_page_number += 1
    
    # 被リンクありページの出力
    for target_url, links_to_target in sorted_targets:
        target_info = pages.get(target_url, {})
        target_title = target_info.get('title', target_url)
        page_key = (target_title, target_url)
        page_number = page_numbers[page_key]
        
        if links_to_target:
            # 被リンクがある場合、各被リンクを1行ずつ出力
            for link in links_to_target:
                writer.writerow([
                    page_number,                      # A_番号（統一）
                    target_title,                    # B_ページタイトル
                    target_url,                      # C_URL
                    link['source_title'],            # D_被リンク元ページタイトル
                    link['source_url'],              # E_被リンク元ページURL
                    link['anchor_text']              # F_被リンク元ページアンカーテキスト
                ])
    
    # 孤立ページ（被リンクが0の）も追加
    for url, info in pages.items():
        if info.get('inbound_links', 0) == 0:
            page_key = (info['title'], url)
            page_number = page_numbers[page_key]
            
            writer.writerow([
                page_number,         # A_番号
                info['title'],      # B_ページタイトル
                url,               # C_URL
                '',                # D_被リンク元ページタイトル
                '',                # E_被リンク元ページURL
                ''                 # F_被リンク元ページアンカーテキスト
            ])
    
    return output.getvalue()
