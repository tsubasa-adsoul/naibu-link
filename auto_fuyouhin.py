import tkinter as tk
from tkinter import messagebox, filedialog
import customtkinter as ctk
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import json
import time
import re
import threading
import webbrowser
from datetime import datetime
import csv
import sys
import os
import html

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

class FuyohinKaishuAnalyzer:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("🔗 fuyohin-kaishu.co.jp専用内部リンク分析ツール（修正版）")
        self.root.geometry("1400x900")

        self.domain = "fuyohin-kaishu.co.jp"
        self.categories = [
            {
                'name': 'ゴミ屋敷・汚部屋',
                'url': 'https://fuyohin-kaishu.co.jp/garbage-house',
                'path': '/garbage-house/',
                'id': 174
            },
            {
                'name': '不用品回収',
                'url': 'https://fuyohin-kaishu.co.jp/unwanted-items',
                'path': '/unwanted-items/',
                'id': 173
            },
            {
                'name': '未分類',
                'url': 'https://fuyohin-kaishu.co.jp/uncategorized',
                'path': '/uncategorized/',
                'id': 1
            },
            {
                'name': '遺品整理・生前整理',
                'url': 'https://fuyohin-kaishu.co.jp/sorting-out-belongings',
                'path': '/sorting-out-belongings/',
                'id': 176
            }
        ]

        self.pages = {}
        self.links = []
        self.detailed_links = []
        self.is_analyzing = False

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })

        self.setup_ui()
        self.root.after(1000, self.auto_start_analysis)

    def setup_ui(self):
        self.main_frame = ctk.CTkScrollableFrame(self.root)
        self.main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        title_label = ctk.CTkLabel(
            self.main_frame, 
            text="🔗 fuyohin-kaishu.co.jp専用内部リンク分析ツール（修正版）",
            font=ctk.CTkFont(size=28, weight="bold")
        )
        title_label.pack(pady=20)

        url_frame = ctk.CTkFrame(self.main_frame)
        url_frame.pack(fill="x", pady=10)
        
        ctk.CTkLabel(url_frame, text="対象カテゴリ:", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=20, pady=5)
        for category in self.categories:
            ctk.CTkLabel(url_frame, text=f"• {category['name']}: {category['url']}", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=40, pady=2)

        button_frame = ctk.CTkFrame(self.main_frame)
        button_frame.pack(pady=20)
        
        self.analyze_button = ctk.CTkButton(
            button_frame, 
            text="分析開始", 
            command=self.start_analysis,
            font=ctk.CTkFont(size=16, weight="bold"),
            width=200,
            height=40
        )
        self.analyze_button.pack(side="left", padx=10)

        self.export_button = ctk.CTkButton(
            button_frame, 
            text="詳細CSVエクスポート", 
            command=self.export_detailed_csv,
            font=ctk.CTkFont(size=16, weight="bold"),
            width=200,
            height=40
        )
        self.export_button.pack(side="left", padx=10)

        self.status_label = ctk.CTkLabel(
            self.main_frame,
            text="準備完了",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.status_label.pack(pady=10)

        self.progress_bar = ctk.CTkProgressBar(self.main_frame, width=600)
        self.progress_bar.pack(pady=10)
        self.progress_bar.set(0)

        self.result_frame = ctk.CTkScrollableFrame(self.main_frame, height=400)
        self.result_frame.pack(fill="both", expand=True, pady=20)

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")

    def auto_start_analysis(self):
        self.log("=== fuyohin-kaishu.co.jp 自動分析開始 ===")
        self.start_analysis()

    def start_analysis(self):
        if self.is_analyzing:
            return
            
        self.analyze_button.configure(state="disabled")
        self.status_label.configure(text="分析中...")
        self.progress_bar.start()

        thread = threading.Thread(target=self.analyze_site)
        thread.daemon = True
        thread.start()

    def get_all_articles_comprehensive(self):
        all_articles = []
        
        for category in self.categories:
            self.log(f"=== {category['name']} カテゴリ分析開始 ===")
            category_articles = self.get_articles_from_category(category)
            
            if category_articles:
                all_articles.extend(category_articles)
                self.log(f"{category['name']}: {len(category_articles)}記事収集")
            
            time.sleep(1)
        
        api_articles = self.get_articles_from_wp_api()
        if api_articles:
            all_articles.extend(api_articles)
            self.log(f"WordPress API: {len(api_articles)}記事追加")
        
        sitemap_articles = self.get_articles_from_sitemap()
        if sitemap_articles:
            all_articles.extend(sitemap_articles)
            self.log(f"サイトマップ: {len(sitemap_articles)}記事追加")
        
        unique_articles = self.remove_duplicate_articles(all_articles)
        
        self.log(f"=== 全記事収集完了: {len(unique_articles)}記事 ===")
        return unique_articles

    def get_articles_from_category(self, category):
        articles = []
        base_url = category['url']
        
        page = 1
        max_pages = 20
        
        while page <= max_pages:
            try:
                if page == 1:
                    list_url = base_url
                else:
                    list_url = f"{base_url}/page/{page}"
                
                self.log(f"  ページ{page}を確認中: {list_url}")
                response = self.session.get(list_url, timeout=30)
                
                if response.status_code != 200:
                    break
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                page_articles = []
                
                post_list_items = soup.find_all(['article', 'div'], class_=re.compile(r'p-postList__item|post-item|entry-item'))
                for item in post_list_items:
                    link = item.find('a', href=True)
                    if link:
                        href = link.get('href')
                        if not href:
                            continue
                        
                        if href.startswith('/'):
                            full_url = f"https://{self.domain}{href}"
                        elif href.startswith('http'):
                            full_url = href
                        else:
                            continue
                        
                        if category['path'] in full_url:
                            if any(ex in full_url for ex in ['page/', 'feed/', '#', '?']):
                                continue
                            
                            if not any(a['url'] == full_url for a in articles + page_articles):
                                link_text = self.extract_link_title(link, item)
                                if link_text and len(link_text) > 3:
                                    page_articles.append({
                                        'url': full_url.rstrip('/'),
                                        'title': link_text,
                                        'category': category['name']
                                    })
                
                direct_links = soup.find_all('a', href=re.compile(category['path']))
                for link in direct_links:
                    href = link.get('href')
                    if href and category['path'] in href:
                        if href.startswith('/'):
                            full_url = f"https://{self.domain}{href}"
                        elif href.startswith('http'):
                            full_url = href
                        else:
                            continue
                        
                        if any(ex in full_url for ex in ['page/', 'feed/', '#', '?']):
                            continue
                        
                        if not any(a['url'] == full_url for a in articles + page_articles):
                            link_text = self.extract_link_title(link, None)
                            if link_text and len(link_text) > 3:
                                page_articles.append({
                                    'url': full_url.rstrip('/'),
                                    'title': link_text,
                                    'category': category['name']
                                })
                
                if page_articles:
                    articles.extend(page_articles)
                    self.log(f"    ページ{page}: {len(page_articles)}記事発見")
                else:
                    break
                
                page += 1
                time.sleep(0.8)
                
            except Exception as e:
                self.log(f"  ページ{page}エラー: {str(e)}")
                break
        
        return articles

    def extract_link_title(self, link, container):
        link_text = link.get_text(strip=True)
        if link_text and len(link_text) > 5 and not link_text.lower() in ['続きを読む', 'read more', '詳細']:
            return link_text[:150]
        
        if link.get('title'):
            return link.get('title').strip()[:150]
        
        if container:
            title_selectors = [
                '.p-postList__title',
                '.entry-title', 
                '.post-title',
                'h2', 'h3', 'h4'
            ]
            
            for selector in title_selectors:
                title_element = container.select_one(selector)
                if title_element:
                    title_text = title_element.get_text(strip=True)
                    if title_text and len(title_text) > 5:
                        return title_text[:150]
        
        return link.get('href', 'リンク')[:150]

    def get_articles_from_wp_api(self):
        articles = []
        
        try:
            api_url = f"https://{self.domain}/wp-json/wp/v2/posts"
            
            page = 1
            per_page = 100
            
            while page <= 10:
                params = {
                    'page': page,
                    'per_page': per_page,
                    'status': 'publish'
                }
                
                self.log(f"WordPress API ページ{page}を取得中...")
                response = self.session.get(api_url, params=params, timeout=30)
                
                if response.status_code != 200:
                    self.log(f"WordPress API エラー: {response.status_code}")
                    break
                
                posts = response.json()
                if not posts:
                    break
                
                for post in posts:
                    post_url = post.get('link', '')
                    if any(cat['path'] in post_url for cat in self.categories):
                        category_name = "その他"
                        for cat in self.categories:
                            if cat['path'] in post_url:
                                category_name = cat['name']
                                break
                        
                        title = post.get('title', {}).get('rendered', '')
                        if title:
                            title = html.unescape(title)
                            title = re.sub(r'<[^>]+>', '', title)
                            title = title.strip()
                            
                            if len(title) > 3:
                                articles.append({
                                    'url': post_url.rstrip('/'),
                                    'title': title[:150],
                                    'category': category_name
                                })
                                self.log(f"  API記事取得: {title[:30]}...")
                
                page += 1
                time.sleep(0.5)
                
        except Exception as e:
            self.log(f"WordPress API取得エラー: {str(e)}")
        
        return articles

    def get_articles_from_sitemap(self):
        articles = []
        
        sitemap_urls = [
            f"https://{self.domain}/sitemap.xml",
            f"https://{self.domain}/wp-sitemap.xml",
            f"https://{self.domain}/sitemap_index.xml",
            f"https://{self.domain}/wp-sitemap-posts-post-1.xml"
        ]
        
        for sitemap_url in sitemap_urls:
            try:
                response = self.session.get(sitemap_url, timeout=30)
                
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'xml')
                    
                    urls = soup.find_all('url')
                    for url in urls:
                        loc = url.find('loc')
                        if loc:
                            url_text = loc.text.rstrip('/')
                            for category in self.categories:
                                if category['path'] in url_text:
                                    slug = url_text.split('/')[-1]
                                    title = slug.replace('-', ' ').title() if slug else f"記事 - {category['name']}"
                                    
                                    articles.append({
                                        'url': url_text,
                                        'title': title,
                                        'category': category['name']
                                    })
                                    break
                    
                    if articles:
                        break
                        
            except Exception as e:
                continue
        
        return articles

    def remove_duplicate_articles(self, articles):
        unique_articles = []
        seen_urls = set()
        
        for article in articles:
            url = article['url'].rstrip('/')
            if url not in seen_urls:
                unique_articles.append(article)
                seen_urls.add(url)
        
        return unique_articles

    def analyze_site(self):
        try:
            self.is_analyzing = True
            
            self.root.after(0, lambda: self.status_label.configure(text="記事一覧を取得中..."))
            articles = self.get_all_articles_comprehensive()
            
            if not articles:
                raise Exception("記事が見つかりませんでした")
            
            self.log(f"合計 {len(articles)} 記事を発見")
            
            pages = {}
            detailed_links = []
            processed_links = set()
            
            for i, article in enumerate(articles):
                try:
                    status_text = f"記事分析中 {i+1}/{len(articles)}: {article['title'][:30]}..."
                    self.root.after(0, lambda text=status_text: self.status_label.configure(text=text))
                    self.root.after(0, lambda: self.progress_bar.set((i+1) / len(articles)))
                    
                    response = self.session.get(article['url'], timeout=30)
                    
                    if response.status_code != 200:
                        pages[article['url']] = {
                            'title': article['title'],
                            'category': article.get('category', '不明'),
                            'outbound_links': [],
                            'inbound_links': 0
                        }
                        self.log(f"  アクセス失敗 {response.status_code}: {article['title']}")
                        continue
                    
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    page_title = self.extract_page_title(soup, article)
                    
                    pages[article['url']] = {
                        'title': page_title,
                        'category': article.get('category', '不明'),
                        'outbound_links': [],
                        'inbound_links': 0
                    }
                    
                    content = self.extract_main_content(soup)
                    if content:
                        links_data = self.extract_links(content)
                        
                        for link_data in links_data:
                            target_url = self.normalize_url(link_data['url'])
                            
                            if self.is_target_article(target_url):
                                link_key = (article['url'], target_url)
                                if link_key not in processed_links:
                                    processed_links.add(link_key)
                                    
                                    pages[article['url']]['outbound_links'].append(target_url)
                                    
                                    detailed_links.append({
                                        'source_url': article['url'],
                                        'source_title': page_title,
                                        'source_category': article.get('category', '不明'),
                                        'target_url': target_url,
                                        'anchor_text': link_data['anchor_text']
                                    })
                    
                    time.sleep(0.3)
                    
                except Exception as e:
                    self.log(f"記事分析エラー {article['url']}: {str(e)}")
                    if article['url'] not in pages:
                        pages[article['url']] = {
                            'title': article['title'],
                            'category': article.get('category', '不明'),
                            'outbound_links': [],
                            'inbound_links': 0
                        }
                    continue
            
            # 【重要】リンク先ページのタイトルを取得
            self.log("=== リンク先ページタイトルを取得中 ===")
            self.fetch_missing_page_titles(detailed_links, pages)
            
            for link in detailed_links:
                target_url = link['target_url']
                if target_url in pages:
                    pages[target_url]['inbound_links'] += 1
            
            self.pages = pages
            self.detailed_links = detailed_links
            
            self.log(f"最終結果: {len(pages)}ページ, {len(detailed_links)}内部リンク")
            self.root.after(0, self.show_results)
            self.root.after(2000, self.auto_export_csv)
            
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("エラー", f"分析中にエラーが発生しました: {e}"))
        finally:
            self.is_analyzing = False
            self.root.after(0, lambda: self.analyze_button.configure(state="normal"))
            self.root.after(0, lambda: self.progress_bar.stop())
            self.root.after(0, lambda: self.status_label.configure(text="分析完了"))

    def fetch_missing_page_titles(self, detailed_links, pages):
        """リンク先ページのタイトルを取得（重要な修正）"""
        
        # リンク先URLでまだタイトルが取得されていないページを特定
        missing_urls = set()
        for link in detailed_links:
            target_url = link['target_url']
            if target_url not in pages:
                missing_urls.add(target_url)
        
        self.log(f"タイトル未取得のページ: {len(missing_urls)}個")
        
        for i, url in enumerate(missing_urls):
            try:
                self.log(f"  タイトル取得中 {i+1}/{len(missing_urls)}: {url}")
                response = self.session.get(url, timeout=30)
                
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    # URLからカテゴリを推定
                    category = "その他"
                    for cat in self.categories:
                        if cat['path'] in url:
                            category = cat['name']
                            break
                    
                    # ダミー記事オブジェクトを作成してタイトル抽出
                    dummy_article = {
                        'url': url,
                        'title': '',
                        'category': category
                    }
                    
                    page_title = self.extract_page_title(soup, dummy_article)
                    
                    pages[url] = {
                        'title': page_title,
                        'category': category,
                        'outbound_links': [],
                        'inbound_links': 0
                    }
                    
                    self.log(f"    取得成功: {page_title[:50]}")
                else:
                    # アクセス失敗時はURLからタイトルを生成
                    slug = url.split('/')[-1]
                    generated_title = slug.replace('-', ' ').title() if slug else url
                    
                    pages[url] = {
                        'title': generated_title,
                        'category': category,
                        'outbound_links': [],
                        'inbound_links': 0
                    }
                    
                    self.log(f"    アクセス失敗、タイトル生成: {generated_title}")
                
                time.sleep(0.5)  # レート制限
                
            except Exception as e:
                # エラー時もフォールバック処理
                slug = url.split('/')[-1]
                fallback_title = slug.replace('-', ' ').title() if slug else url
                
                pages[url] = {
                    'title': fallback_title,
                    'category': "その他",
                    'outbound_links': [],
                    'inbound_links': 0
                }
                
                self.log(f"    エラー、フォールバック: {fallback_title}")

    def extract_page_title(self, soup, article):
        """ページタイトルを正しく抽出"""
        
        title_selectors = [
            '.c-postTitle__ttl',
            'h1.c-postTitle__ttl',
            '.entry-title',
            '.post-title',
            '.article-title',
            'h1'
        ]
        
        for selector in title_selectors:
            try:
                title_elements = soup.select(selector)
                
                for title_element in title_elements:
                    if title_element and title_element.get_text(strip=True):
                        title_text = title_element.get_text(strip=True)
                        
                        if len(title_text) > 3 and not title_text.lower() in ['home', 'top', 'ホーム']:
                            return title_text
            except Exception as e:
                continue
        
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
            
            title = re.sub(r'\s*[|\-–]\s*.*(不用品回収|fuyohin|kaishu).*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s*[|\-–]\s*.*不用品回収隊.*$', '', title, flags=re.IGNORECASE)
            
            if len(title.strip()) > 3:
                return title.strip()
        
        if article.get('title') and len(article['title']) > 3:
            if not article['title'].startswith('http') and '/' not in article['title']:
                return article['title']
        
        path = urlparse(article['url']).path
        if path:
            slug = path.strip('/').split('/')[-1]
            
            if slug and slug != 'wp' and len(slug) > 1:
                generated_title = slug.replace('-', ' ').replace('_', ' ').title()
                return generated_title
        
        return f"記事({article['url'].split('/')[-1] if article['url'].split('/')[-1] else 'unknown'})"

    def extract_main_content(self, soup):
        exclude_selectors = [
            '#sidebar', '.l-sidebar', '.sidebar',
            '.p-relatedPosts', '.related-posts',
            '.p-pnLinks', '.prev-next-links',
            '.c-shareBtns', '.share-buttons',
            '.p-authorBox', '.author-box',
            '#breadcrumb', '.breadcrumb',
            '.widget', '.c-widget',
            '.footer_cta', '.fixed-banner'
        ]
        
        for selector in exclude_selectors:
            for element in soup.select(selector):
                element.decompose()
        
        content_selectors = [
            '.post_content',
            '.entry-content',
            '.post-content',
            'main article',
            '#main_content'
        ]
        
        for selector in content_selectors:
            content = soup.select_one(selector)
            if content:
                return content
        
        return soup.find('main') or soup.find('article')

    def extract_links(self, content):
        links = []
        
        if not content:
            return links
        
        for link in content.find_all('a', href=True):
            href = link.get('href')
            anchor_text = link.get_text(strip=True) or link.get('title', '') or '[リンク]'
            
            if href and len(anchor_text) > 0:
                links.append({
                    'url': href,
                    'anchor_text': anchor_text[:100]
                })
        
        return links

    def normalize_url(self, url):
        if url.startswith('/'):
            url = f"https://{self.domain}{url}"
        
        parsed = urlparse(url)
        if parsed.netloc != self.domain:
            return url
        
        path = parsed.path.rstrip('/')
        if path and not path.endswith('/'):
            path += '/'
        
        return f"https://{self.domain}{path}"

    def is_target_article(self, url):
        target_paths = [cat['path'] for cat in self.categories]
        
        if not any(target_path in url for target_path in target_paths):
            return False
        
        exclude_patterns = [
            '/wp-admin/', '/wp-content/', '/wp-json/',
            '.jpg', '.jpeg', '.png', '.gif', '.pdf',
            '/feed/', '/page/', '#', '?',
            '/contact', '/privacy', '/terms'
        ]
        
        return not any(pattern in url.lower() for pattern in exclude_patterns)

    def show_results(self):
        for widget in self.result_frame.winfo_children():
            widget.destroy()

        total_pages = len(self.pages)
        total_links = len(self.detailed_links)
        isolated_pages = sum(1 for p in self.pages.values() if p['inbound_links'] == 0)
        popular_pages = sum(1 for p in self.pages.values() if p['inbound_links'] >= 5)

        stats_label = ctk.CTkLabel(
            self.result_frame,
            text=f"分析結果: {total_pages}ページ | {total_links}内部リンク | 孤立記事{isolated_pages}件 | 人気記事{popular_pages}件",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        stats_label.pack(pady=10)

        for category in self.categories:
            category_pages = [p for p in self.pages.values() if p.get('category') == category['name']]
            if category_pages:
                avg_inbound = sum(p['inbound_links'] for p in category_pages) / len(category_pages)
                ctk.CTkLabel(
                    self.result_frame,
                    text=f"{category['name']}: {len(category_pages)}記事, 平均被リンク数: {avg_inbound:.1f}",
                    font=ctk.CTkFont(size=12)
                ).pack(anchor="w", padx=20)

        sorted_pages = sorted(self.pages.items(), key=lambda x: x[1]['inbound_links'], reverse=True)
        
        ctk.CTkLabel(
            self.result_frame,
            text="被リンク数トップ10:",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(pady=(20, 5), anchor="w")
        
        for i, (url, info) in enumerate(sorted_pages[:10]):
            label_text = f"{i+1:2d}. [{info['inbound_links']:2d}被リンク] {info['title'][:60]}..."
            
            ctk.CTkLabel(
                self.result_frame,
                text=label_text,
                anchor="w",
                font=ctk.CTkFont(size=11)
            ).pack(fill="x", padx=20, pady=1)

    def auto_export_csv(self):
        try:
            if hasattr(sys, '_MEIPASS'):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))
            
            today = datetime.now()
            date_folder = today.strftime("%Y-%m-%d")
            folder_path = os.path.join(base_dir, date_folder)
            
            os.makedirs(folder_path, exist_ok=True)
            
            csv_filename = f"fuyohin-kaishu-{date_folder}.csv"
            filename = os.path.join(folder_path, csv_filename)
            
            self.export_detailed_csv_to_file(filename)
            
            self.log(f"=== 自動CSVエクスポート完了: {date_folder}/{csv_filename} ===")
            
        except Exception as e:
            self.log(f"自動CSVエクスポートエラー: {e}")

    def export_detailed_csv(self):
        if not self.detailed_links and not self.pages:
            messagebox.showerror("エラー", "詳細データが存在しません")
            return

        filename = filedialog.asksaveasfilename(
            defaultextension=".csv", 
            filetypes=[("CSV files", "*.csv")],
            initialname=f"fuyohin-kaishu-{datetime.now().strftime('%Y-%m-%d')}.csv"
        )
        if filename:
            self.export_detailed_csv_to_file(filename)

    def export_detailed_csv_to_file(self, filename):
        try:
            print(f"\n=== CSV出力開始 ===")
            print(f"総ページ数: {len(self.pages)}")
            print(f"内部リンク数: {len(self.detailed_links)}")
            
            with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                
                writer.writerow([
                    '番号', 'ページタイトル', 'URL',
                    '被リンク元タイトル', '被リンク元URL', 'アンカーテキスト'
                ])
                
                row_number = 1
                
                target_groups = {}
                for link in self.detailed_links:
                    target_url = link['target_url']
                    if target_url not in target_groups:
                        target_groups[target_url] = []
                    target_groups[target_url].append(link)
                
                sorted_targets = sorted(target_groups.items(), key=lambda x: len(x[1]), reverse=True)
                processed_urls = set()
                
                for target_url, links_to_target in sorted_targets:
                    target_info = self.pages.get(target_url, {})
                    target_title = target_info.get('title', 'タイトル不明')
                    
                    # デバッグ出力
                    print(f"出力中 - ページ: {target_title[:30]}... (被リンク{len(links_to_target)}個)")
                    print(f"  URL: {target_url}")
                    print(f"  タイトル: '{target_title}'")
                    
                    processed_urls.add(target_url)
                    
                    for link in links_to_target:
                        writer.writerow([
                            row_number,
                            target_title,
                            target_url,
                            link['source_title'],
                            link['source_url'],
                            link['anchor_text']
                        ])
                        row_number += 1
                
                isolated_pages = []
                for url, info in self.pages.items():
                    if url not in processed_urls:
                        isolated_pages.append((url, info))
                
                print(f"孤立ページ数: {len(isolated_pages)}")
                
                isolated_pages.sort(key=lambda x: x[1].get('title', ''))
                
                for url, info in isolated_pages:
                    title = info.get('title', 'タイトル不明')
                    print(f"孤立ページ出力: {title[:30]}...")
                    
                    writer.writerow([
                        row_number,
                        title,
                        url,
                        '（被リンクなし）',
                        '',
                        ''
                    ])
                    row_number += 1
            
            print(f"=== CSV出力完了: {row_number-1}行 ===")
            messagebox.showinfo("完了", f"詳細CSVを保存しました: {filename}\n総行数: {row_number-1}行")
            
        except Exception as e:
            print(f"CSV出力エラー: {e}")
            messagebox.showerror("エラー", f"保存に失敗: {e}")

def main():
    app = FuyohinKaishuAnalyzer()
    app.root.mainloop()

if __name__ == "__main__":
    main()