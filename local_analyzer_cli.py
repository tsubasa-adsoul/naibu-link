#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ローカル環境用 内部リンク分析コマンドラインツール
- 指定されたURLをクロールし、内部リンク構造を解析してCSVに出力します。
- Streamlitアプリから呼び出されることを想定しています。
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import re
from datetime import datetime
import csv
import sys
import os
import argparse

class LocalLinkAnalyzer:
    """
    サイトのクロールとリンク分析を行うクラス。
    """
    def __init__(self, base_url, output_file, site_name=""):
        self.base_url = base_url
        self.output_file = output_file
        self.site_name = site_name
        self.pages = {}
        self.links = []
        self.detailed_links = []
        self.domain = urlparse(base_url).netloc.replace('www.', '')
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'})

    def extract_from_sitemap(self, url):
        urls = set()
        try:
            res = self.session.get(url, timeout=10)
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
            print(f"[警告] サイトマップの取得に失敗: {url} - {e}", file=sys.stderr)
        return list(urls)

    def generate_seed_urls(self):
        sitemap_root = urljoin(self.base_url, '/sitemap.xml')
        sitemap_urls = self.extract_from_sitemap(sitemap_root)
        print(f"サイトマップから {len(sitemap_urls)} 個のURLを取得しました。")
        return list(set([self.normalize_url(self.base_url)] + sitemap_urls))

    def is_content(self, url):
        normalized_url = self.normalize_url(url)
        path = urlparse(normalized_url).path.lower().split('?')[0].rstrip('/')
        
        # 除外パターン
        exclude_patterns = [
            r'/sitemap', r'sitemap.*\.(xml|html)$', r'/page/\d+$', r'-mg', r'/site/', 
            r'/wp-', r'/tag/', r'/wp-content', r'/wp-admin', r'/wp-json', r'#', 
            r'\?utm_', r'/feed/', r'mailto:', r'tel:', r'/privacy', r'/terms', 
            r'/contact', r'/go-', r'/redirect', r'/exit', r'/out',
            r'\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|rar|doc|docx|xls|xlsx)$'
        ]
        if any(re.search(e, path) for e in exclude_patterns):
            return False
        
        return True

    def is_noindex_page(self, soup):
        try:
            meta_robots = soup.find('meta', attrs={'name': 'robots'})
            if meta_robots and 'noindex' in meta_robots.get('content', '').lower():
                return True
            
            noindex_meta = soup.find('meta', attrs={'name': 'googlebot', 'content': lambda x: x and 'noindex' in x.lower()})
            if noindex_meta:
                return True
            
            title = soup.find('title')
            if title and any(keyword in title.get_text('').lower() for keyword in ['外部サイト', 'リダイレクト', '移動中']):
                return True
            
            return False
        except Exception:
            return False

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

        links = []
        
        # 通常のaタグ
        for link in content_area.find_all('a', href=True):
            href = link['href']
            if href:
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
        print(f"「{self.site_name}」の分析を開始します。 URL: {self.base_url}")
        
        pages = {}
        links = []
        detailed_links = []
        visited = set()
        to_visit = self.generate_seed_urls()
        processed_links = set()

        crawl_limit = 500
        count = 0

        while to_visit and count < crawl_limit:
            url = to_visit.pop(0)
            normalized_url = self.normalize_url(url)
            if normalized_url in visited:
                continue

            try:
                response = self.session.get(url, timeout=10)
                if response.status_code != 200:
                    continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                if self.is_noindex_page(soup):
                    print(f"  - スキップ (NOINDEX): {url}")
                    visited.add(normalized_url)
                    continue
                
                title = soup.title.string.strip() if soup.title and soup.title.string else normalized_url
                title = re.sub(r'\s*[|\-].*$', '', title).strip() # サイト名を削除

                pages[normalized_url] = {'title': title, 'outbound_links': []}
                
                extracted_links = self.extract_links(soup, url)
                
                for link_data in extracted_links:
                    link_url = self.normalize_url(link_data['url'])
                    
                    if urlparse(link_url).netloc.replace('www.','') == self.domain and self.is_content(link_url):
                        link_key = (normalized_url, link_url)
                        if link_key not in processed_links:
                            processed_links.add(link_key)
                            links.append((normalized_url, link_url))
                            pages[normalized_url]['outbound_links'].append(link_url)
                            detailed_links.append({
                                'source_url': normalized_url,
                                'source_title': title,
                                'target_url': link_url,
                                'anchor_text': link_data['anchor_text']
                            })
                        
                        if link_url not in visited and link_url not in to_visit:
                            to_visit.append(link_url)

                visited.add(normalized_url)
                count += 1
                print(f"  - クロール完了 ({count}/{len(visited)}): {url}")
                time.sleep(0.1)

            except Exception as e:
                print(f"  - エラー: {url} - {e}", file=sys.stderr)
                continue

        for url in pages:
            pages[url]['inbound_links'] = sum(1 for _, tgt in links if tgt == url)

        self.pages = pages
        self.detailed_links = detailed_links
        print(f"\n分析完了: {len(pages)}ページ, {len(links)}リンクを検出しました。")
        self.export_to_csv()

    def export_to_csv(self):
        print(f"CSVファイルへの出力を開始します: {self.output_file}")
        try:
            with open(self.output_file, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'A_番号', 'B_ページタイトル', 'C_URL',
                    'D_被リンク元ページタイトル', 'E_被リンク元ページURL', 'F_被リンク元ページアンカーテキスト'
                ])

                unique_pages = sorted(self.pages.items(), key=lambda item: item[1]['inbound_links'], reverse=True)
                page_number_map = {url: i for i, (url, _) in enumerate(unique_pages, 1)}

                if not self.detailed_links and self.pages: # リンクが全くない場合
                    for url, info in self.pages.items():
                        page_number = page_number_map.get(url, 0)
                        writer.writerow([page_number, info['title'], url, '', '', ''])
                else:
                    # 被リンクありページ
                    for link in self.detailed_links:
                        target_url = link['target_url']
                        if target_url in page_number_map:
                            target_info = self.pages.get(target_url, {})
                            page_number = page_number_map[target_url]
                            writer.writerow([
                                page_number,
                                target_info.get('title', target_url),
                                target_url,
                                link['source_title'],
                                link['source_url'],
                                link['anchor_text']
                            ])
                    
                    # 孤立ページ
                    for url, info in self.pages.items():
                        if info['inbound_links'] == 0:
                            page_number = page_number_map.get(url, 0)
                            writer.writerow([page_number, info['title'], url, '', '', ''])
            
            print(f"CSVファイルの保存が完了しました。")
            return True
        except Exception as e:
            print(f"CSV保存中に致命的なエラーが発生しました: {e}", file=sys.stderr)
            return False

def main():
    parser = argparse.ArgumentParser(description="指定されたサイトの内部リンクを分析し、CSVに出力します。")
    parser.add_argument("site_name", help="分析対象のサイト名（例: arigataya）")
    parser.add_argument("output_file", help="出力するCSVファイルのパス")
    args = parser.parse_args()

    # 主の管理サイトリスト
    site_definitions = {
        "arigataya": "https://arigataya.co.jp",
        "kau-ru": "https://kau-ru.com",
        "kaitori-life": "https://kaitori-life.com",
        "friendpay": "https://friend-pay.com",
        "crecaeru": "https://crecaeru.com",
        # --- ここに他の5サイトの情報を追加してください ---
        # "site6": "https://site6.com",
        # "site7": "https://site7.com",
        # "site8": "https://site8.com",
        # "site9": "https://site9.com",
        # "site10": "https://site10.com",
    }

    base_url = site_definitions.get(args.site_name)
    if not base_url:
        print(f"エラー: 定義されていないサイト名です: {args.site_name}", file=sys.stderr)
        sys.exit(1)

    analyzer = LocalLinkAnalyzer(base_url, args.output_file, args.site_name)
    analyzer.run_analysis()

if __name__ == "__main__":
    main()
