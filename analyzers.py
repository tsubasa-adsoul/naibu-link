# analyzers.py

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import re
import csv
import sys
from io import StringIO

class SiteAnalyzer:
    """
    特定のサイトをクロールし、内部リンク情報を分析してCSV形式の文字列を生成するクラス。
    （Streamlit Cloudの環境に合わせ、クロール性能を強化した改良版）
    """
    def __init__(self, site_name, streamlit_status_update_callback=None):
        
        # ★★★ 修正点①：主が管理する全てのサイトをここに記述してください ★★★
        self.site_definitions = {
            # 基本の5サイト
            "arigataya": "https://arigataya.co.jp",
            "kau-ru": "https://kau-ru.com",
            "kaitori-life": "https://kaitori-life.com",
            "friendpay": "https://friend-pay.com",
            "crecaeru": "https://crecaeru.com",
            "bicgift": "https://bic-gift.co.jp",
            # "サイト名7": "https://example-7.com",
            # "サイト名8": "https://example-8.com",
            # "サイト名9": "https://example-9.com",
            # "サイト名10": "https://example-10.com",
            # "サイト名11": "https://example-11.com",
            # "サイト名12": "https://example-12.com",
            # "サイト名13": "https://example-13.com",
            # "サイト名14": "https://example-14.com",
        }
        
        self.site_name = site_name
        self.base_url = self.site_definitions.get(site_name)
        if not self.base_url:
            raise ValueError(f"定義されていないサイト名です: {site_name}")

        self.pages = {}
        self.links = []
        self.detailed_links = []
        self.domain = urlparse(self.base_url).netloc.replace('www.', '')
        self.session = requests.Session()
        # より一般的なユーザーエージェントに変更
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
        })
        
        self.st_callback = streamlit_status_update_callback

    def _update_status(self, message):
        if self.st_callback:
            self.st_callback(message)
        else:
            print(message, file=sys.stderr)

    def extract_from_sitemap(self, url):
        urls = set()
        try:
            # ★★★ 修正点②：タイムアウト時間を延長 ★★★
            res = self.session.get(url, timeout=20)
            res.raise_for_status()
            soup = BeautifulSoup(res.content, 'xml')
            locs = soup.find_all('loc')
            if soup.find('sitemapindex'):
                for loc in locs:
                    urls.update(self.extract_from_sitemap(loc.text.strip()))
            else:
                for loc in locs:
                    loc_url = loc.text.strip()
                    if not re.search(r'sitemap.*\.(xml|html)$', loc_url.lower()):
                        urls.add(self.normalize_url(loc_url))
        except Exception as e:
            self._update_status(f"[警告] サイトマップ取得失敗: {url} - {e}")
        return list(urls)

    def generate_seed_urls(self):
        sitemap_root = urljoin(self.base_url, '/sitemap.xml')
        sitemap_urls = self.extract_from_sitemap(sitemap_root)
        self._update_status(f"サイトマップから {len(sitemap_urls)} 個のURLを取得しました。")
        return list(set([self.normalize_url(self.base_url)] + sitemap_urls))

    def is_content(self, url):
        # (この部分は変更なし)
        normalized_url = self.normalize_url(url)
        path = urlparse(normalized_url).path.lower().split('?')[0].rstrip('/')
        exclude_patterns = [
            r'/sitemap', r'sitemap.*\.(xml|html)$', r'/page/\d+$', r'-mg', r'/site/', 
            r'/wp-', r'/tag/', r'/wp-content', r'/wp-admin', r'/wp-json', r'#', 
            r'\?utm_', r'/feed/', r'mailto:', r'tel:', r'/privacy', r'/terms', 
            r'/contact', r'/go-', r'/redirect', r'/exit', r'/out',
            r'\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|rar|doc|docx|xls|xlsx)$'
        ]
        return not any(re.search(e, path) for e in exclude_patterns)

    def is_noindex_page(self, soup):
        try:
            meta_robots = soup.find('meta', attrs={'name': 'robots'})
            if meta_robots and 'noindex' in meta_robots.get('content', '').lower():
                return True
            return False
        except Exception:
            return False

    # ★★★ 修正点③：主のオリジナルに近づけた、より強力なリンク抽出ロジック ★★★
    def extract_links(self, soup, page_url):
        selectors = [
            '.post_content', '.entry-content', '.article-content', 
            'main .content', '[class*="content"]', 'main', 'article'
        ]
        
        content_area = None
        for selector in selectors:
            area = soup.select_one(selector)
            if area:
                content_area = area
                break
        
        if not content_area:
            content_area = soup.body # フォールバック

        # 除外要素を先に削除する（主のオリジナルの優れたロジックを再現）
        for exclude in content_area.select('header, footer, nav, aside, .sidebar, .widget, .share, .related, .popular-posts, .breadcrumb, .author-box, .navigation'):
            exclude.decompose()

        links = []
        # 通常のaタグ
        for link in content_area.find_all('a', href=True):
            href = link['href']
            # javascript:void(0) などを除外
            if href and not href.lower().startswith('javascript:'):
                full_url = urljoin(page_url, href)
                anchor_text = link.get_text(strip=True) or link.get('title', '') or '[リンク]'
                links.append({'url': full_url, 'anchor_text': anchor_text[:100]})
        
        # onclick属性
        for element in content_area.find_all(attrs={'onclick': True}):
            onclick_attr = element.get('onclick', '')
            match = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", onclick_attr)
            if match:
                url = match.group(1)
                full_url = urljoin(page_url, url)
                anchor_text = element.get_text(strip=True) or '[onclick]'
                links.append({'url': full_url, 'anchor_text': anchor_text[:100]})
                
        return links

    def normalize_url(self, url):
        try:
            url = url.strip().split('#')[0]
            parsed = urlparse(url)
            scheme = parsed.scheme or 'https'
            netloc = parsed.netloc.replace('www.', '')
            path = parsed.path.rstrip('/') or '/'
            path = re.sub(r'/+', '/', path)
            return f"{scheme}://{netloc}{path}"
        except Exception:
            return url

    def run_analysis(self):
        self._update_status(f"「{self.site_name}」の分析を開始します...")
        
        visited = set()
        to_visit = self.generate_seed_urls()
        processed_links = set()
        
        # ★★★ 修正点④：クロール上限を拡大 ★★★
        crawl_limit = 800
        count = 0

        while to_visit and count < crawl_limit:
            url = to_visit.pop(0)
            normalized_url = self.normalize_url(url)
            if normalized_url in visited:
                continue

            try:
                # ★★★ 修正点⑤：タイムアウト時間を延長 ★★★
                response = self.session.get(url, timeout=20)
                if response.status_code != 200: continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                if self.is_noindex_page(soup):
                    self._update_status(f"  - スキップ (NOINDEX): {url[:70]}...")
                    visited.add(normalized_url)
                    continue
                
                title = (soup.title.string.strip() if soup.title and soup.title.string else normalized_url)
                title = re.sub(r'\s*[|\-].*$', '', title).strip()

                self.pages[normalized_url] = {'title': title, 'outbound_links': []}
                
                for link_data in self.extract_links(soup, url):
                    link_url = self.normalize_url(link_data['url'])
                    if urlparse(link_url).netloc.replace('www.','') == self.domain and self.is_content(link_url):
                        if (normalized_url, link_url) not in processed_links:
                            processed_links.add((normalized_url, link_url))
                            self.links.append((normalized_url, link_url))
                            self.pages[normalized_url]['outbound_links'].append(link_url)
                            self.detailed_links.append({
                                'source_url': normalized_url, 'source_title': title,
                                'target_url': link_url, 'anchor_text': link_data['anchor_text']
                            })
                        if link_url not in visited and link_url not in to_visit:
                            to_visit.append(link_url)

                visited.add(normalized_url)
                count += 1
                self._update_status(f"  - クロール完了 ({count}/{crawl_limit}): {url[:70]}...")
                # クラウド環境での負荷を考慮した待機時間
                time.sleep(0.1)

            except requests.exceptions.RequestException as e:
                self._update_status(f"  - ネットワークエラー: {url[:70]}... - {e}")
                continue
            except Exception as e:
                self._update_status(f"  - 不明なエラー: {url[:70]}... - {e}")
                continue

        for url in self.pages:
            pages[url]['inbound_links'] = sum(1 for _, tgt in self.links if tgt == url)

        self._update_status(f"\n分析完了: {len(self.pages)}ページ, {len(self.links)}リンクを検出。CSVを生成します。")
        return self.get_csv_string()

    def get_csv_string(self):
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['A_番号', 'B_ページタイトル', 'C_URL', 'D_被リンク元ページタイトル', 'E_被リンク元ページURL', 'F_被リンク元ページアンカーテキスト'])
        
        unique_pages = sorted(self.pages.items(), key=lambda item: item[1]['inbound_links'], reverse=True)
        page_number_map = {url: i for i, (url, _) in enumerate(unique_pages, 1)}

        for link in self.detailed_links:
            target_url = link['target_url']
            if target_url in page_number_map:
                target_info = self.pages.get(target_url, {})
                writer.writerow([
                    page_number_map[target_url], target_info.get('title', target_url), target_url,
                    link['source_title'], link['source_url'], link['anchor_text']
                ])
        
        for url, info in self.pages.items():
            if info['inbound_links'] == 0:
                writer.writerow([page_number_map.get(url, 0), info['title'], url, '', '', ''])
        
        return output.getvalue()
