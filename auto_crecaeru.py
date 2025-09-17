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
        if not isinstance(url, str): return ""
        try:
            parsed = urlparse(url)
            scheme = 'https'
            netloc = parsed.netloc.replace('www.', '')
            path = parsed.path.rstrip('/')
            
            # crecaeru専用正規化
            if '/wp/' in path:
                path = path.replace('/wp/', '/')
            
            path = re.sub(r'/+', '/', path)
            
            if path and not path.endswith('/'):
                path += '/'
                
            return f"{scheme}://{netloc}{path}"
        except: return ""

    def is_content(url):
        try:
            path = urlparse(url).path.lower().split('?')[0].rstrip('/')
            
            # 許可パターン
            allow_patterns = [
                r'^/category/[a-z0-9\-]+$',
                r'^/category/[a-z0-9\-]+/page/\d+$',
                r'^/[a-z0-9\-]+$',
                r'^/$',
                r'^$'
            ]
            
            if any(re.search(pattern, path) for pattern in allow_patterns):
                return True
            
            # 除外パターン
            exclude_patterns = [
                r'/sitemap', r'sitemap.*\.(xml|html)$', r'/page/\d+$', r'-mg',
                r'/site/', r'/wp-', r'/tag/', r'/wp-content', r'/wp-admin', r'/wp-json',
                r'#', r'\?utm_', r'/feed/', r'mailto:', r'tel:', r'/privacy', r'/terms',
                r'/contact', r'/go-', r'/redirect', r'/exit', r'/out',
                r'\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|rar|doc|docx|xls|xlsx)$'
            ]
            
            if any(re.search(e, path) for e in exclude_patterns):
                return False
            
            return True
        except:
            return False

    def is_noindex_page(soup):
        try:
            meta_robots = soup.find('meta', attrs={'name': 'robots'})
            if meta_robots and meta_robots.get('content'):
                content = meta_robots.get('content').lower()
                if 'noindex' in content:
                    return True
            return False
        except:
            return False

    def extract_links(soup):
        links = []
        selectors = ['.post_content', '.entry-content', '.article-content', 'main .content', 'main', 'article']
        
        for selector in selectors:
            areas = soup.select(selector)
            if areas:
                for area in areas:
                    # gnav除外
                    gnav = area.select_one('#gnav.l-header__gnav.c-gnavWrap')
                    if gnav:
                        gnav.decompose()
                    
                    # その他除外
                    for exclude in area.select('header, footer, nav, aside, .sidebar, .widget, .share, .related, .popular-posts, .breadcrumb, .author-box, .navigation'):
                        exclude.decompose()
                    
                    # aタグリンク
                    for link in area.find_all('a', href=True):
                        anchor_text = link.get_text(strip=True) or link.get('title', '') or '[リンク]'
                        links.append({'url': link['href'], 'anchor_text': anchor_text[:100]})
                    
                    # onclickリンク
                    for element in area.find_all(attrs={'onclick': True}):
                        onclick_attr = element.get('onclick', '')
                        url_match = re.search(r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]", onclick_attr)
                        if url_match:
                            extracted_url = url_match.group(1)
                            anchor_text = element.get_text(strip=True) or '[onclick]'
                            links.append({'url': extracted_url, 'anchor_text': anchor_text[:100]})
                
                if links:
                    return links
        
        return []

    def extract_from_sitemap(url, session):
        urls = set()
        try:
            res = session.get(url, timeout=10)
            if not res.ok: return urls
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
            log(f"サイトマップエラー: {e}")
        return list(urls)

    if state['phase'] == 'initializing':
        log("crecaeru分析を開始します")
        try:
            base_url = "https://crecaeru.co.jp"
            session = requests.Session()
            session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
            
            sitemap_urls = extract_from_sitemap(urljoin(base_url, '/sitemap.xml'), session)
            
            # 手動追加URL
            manual_urls = [
                base_url,
                f"{base_url}/yamagata/",
                f"{base_url}/donnatokimo/", 
                f"{base_url}/impact-experience/",
                f"{base_url}/paidy-gendogaku/",
                f"{base_url}/convenience-store/",
                f"{base_url}/quick-change-experience/",
                f"{base_url}/long-store/",
                f"{base_url}/site/kau-ru-aucardnasi",
                f"{base_url}/privacy-policy/"
            ]
            
            all_urls = list(set(sitemap_urls + manual_urls))
            
            state.update({
                'session': session, 'base_url': base_url, 'domain': urlparse(base_url).netloc.replace('www.', ''),
                'to_visit': [u for u in all_urls if is_content(u)],
                'visited': set(), 'pages': {}, 'links': [], 'phase': 'crawling'
            })
            log(f"クロール対象: {len(state['to_visit'])}件")
            if not state['to_visit']:
                state['phase'] = 'error'
        except Exception as e:
            log(f"初期化エラー: {e}")
            state['phase'] = 'error'
        return state

    if state['phase'] == 'crawling':
        session, base_url, domain = state['session'], state['base_url'], state['domain']
        crawled_count = 0
        
        while state['to_visit'] and crawled_count < 10:
            url = state['to_visit'].pop(0)
            if url in state['visited']: continue
            state['visited'].add(url)
            
            try:
                log(f"クロール: {url}")
                res = session.get(url, timeout=15)
                if not res.ok: continue

                soup = BeautifulSoup(res.text, 'html.parser')
                if is_noindex_page(soup): continue

                title = (soup.find('h1') or soup.find('title'))
                title = title.get_text(strip=True) if title else url
                title = re.sub(r'\s*[|\-].*(crecaeru|クレかえる).*$', '', title, flags=re.IGNORECASE).strip()
                state['pages'][url] = {'title': title}
                
                for link in extract_links(soup):
                    norm_link = normalize_url(urljoin(base_url, link['url']))
                    if norm_link and norm_link.startswith(f"https://{domain}") and is_content(norm_link):
                        state['links'].append({
                            'source_url': url, 'source_title': title,
                            'target_url': norm_link, 'anchor_text': link['anchor_text']
                        })
                        if norm_link not in state['visited'] and norm_link not in state['to_visit']:
                            state['to_visit'].append(norm_link)
                
                crawled_count += 1
                time.sleep(0.3)
            except Exception as e:
                log(f"エラー: {url} - {e}")
        
        total_urls = len(state['visited']) + len(state['to_visit'])
        state['progress'] = len(state['visited']) / total_urls if total_urls > 0 else 1
        state['progress_text'] = f"進捗: {len(state['visited'])} / {total_urls}"

        if not state['to_visit']:
            log("クロール完了")
            state['phase'] = 'completed'
        return state

    return state

def generate_csv(state):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['A_番号', 'B_ページタイトル', 'C_URL', 'D_被リンク元ページタイトル', 'E_被リンク元ページURL', 'F_被リンク元ページアンカーテキスト'])
    
    pages = state.get('pages', {})
    links = state.get('links', [])
    if not pages: return output.getvalue()

    # 被リンク数計算
    target_counts = {}
    for link in links:
        target = link['target_url']
        target_counts[target] = target_counts.get(target, 0) + 1

    # 被リンク数順でソート
    sorted_targets = sorted(target_counts.items(), key=lambda x: x[1], reverse=True)
    
    row_num = 1
    for target_url, count in sorted_targets:
        target_title = pages.get(target_url, {}).get('title', target_url)
        target_links = [l for l in links if l['target_url'] == target_url]
        
        for link in target_links:
            writer.writerow([row_num, target_title, target_url, link['source_title'], link['source_url'], link['anchor_text']])
        row_num += 1

    # 孤立ページ
    for url, info in pages.items():
        if url not in target_counts:
            writer.writerow([row_num, info['title'], url, '', '', ''])
            row_num += 1
            
    return output.getvalue()
