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

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

class MorePayAnalyzer:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("🔗 more-pay.jp専用内部リンク分析ツール（全自動版）")
        self.root.geometry("1200x800")

        self.pages = {}
        self.links = []
        self.detailed_links = []
        self.analysis_data = None
        self.is_analyzing = False

        self.setup_ui()
        
        # 自動分析開始（EXE化対応）
        self.root.after(1000, self.auto_start_analysis)  # 1秒後に自動開始

    def setup_ui(self):
        self.main_frame = ctk.CTkScrollableFrame(self.root)
        self.main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        title_label = ctk.CTkLabel(self.main_frame, text="🔗 more-pay.jp専用内部リンク分析ツール（全自動版）",
                                   font=ctk.CTkFont(size=28, weight="bold"))
        title_label.pack(pady=20)

        self.url_entry = ctk.CTkEntry(self.main_frame, placeholder_text="https://more-pay.jp", width=500)
        self.url_entry.pack(pady=10)
        self.url_entry.insert(0, "https://more-pay.jp")

        self.analyze_button = ctk.CTkButton(self.main_frame, text="分析開始", command=self.start_analysis)
        self.analyze_button.pack(pady=10)

        self.status_label = ctk.CTkLabel(self.main_frame, text="")
        self.status_label.pack(pady=10)

        self.progress_bar = ctk.CTkProgressBar(self.main_frame, width=400)
        self.progress_bar.pack(pady=5)
        self.progress_bar.stop()

        self.result_frame = ctk.CTkScrollableFrame(self.main_frame, height=400)
        self.result_frame.pack(fill="both", expand=True, pady=20)

        # エクスポートボタン（詳細のみ）
        ctk.CTkButton(self.main_frame, text="詳細CSVエクスポート", command=self.export_detailed_csv).pack(pady=10)

    def auto_start_analysis(self):
        """EXE化対応：自動で分析開始"""
        print("=== 自動分析開始 ===")
        self.status_label.configure(text="自動分析を開始します...")
        self.start_analysis()

    def start_analysis(self):
        url = self.url_entry.get().strip()
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        self.analyze_button.configure(state="disabled")
        self.status_label.configure(text="クロール中...")
        self.progress_bar.start()

        thread = threading.Thread(target=self.analyze_site, args=(url,))
        thread.daemon = True
        thread.start()

    def extract_from_sitemap(self, url):
        """サイトマップからURLを抽出（改善版）"""
        urls = set()
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            res = requests.get(url, timeout=10, headers=headers)
            res.raise_for_status()
            
            # XMLとして解析を試行
            try:
                soup = BeautifulSoup(res.content, 'xml')
            except:
                soup = BeautifulSoup(res.content, 'html.parser')
            
            locs = soup.find_all('loc')
            if soup.find('sitemapindex'):
                # サイトマップインデックスの場合
                for loc in locs:
                    child_sitemap_url = loc.text.strip()
                    urls.update(self.extract_from_sitemap(child_sitemap_url))
            else:
                # 通常のサイトマップの場合
                for loc in locs:
                    loc_url = loc.text.strip()
                    if not re.search(r'sitemap.*\.(xml|html)$', loc_url.lower()):
                        normalized_url = self.normalize_url(loc_url)
                        if self.is_content(normalized_url):
                            urls.add(normalized_url)
        except Exception as e:
            print(f"サイトマップ処理エラー ({url}): {e}")
        
        return list(urls)

    def generate_seed_urls(self, base_url):
        """シードURLの生成（改善版）"""
        seed_urls = [self.normalize_url(base_url)]
        
        # 複数のサイトマップパターンを試行
        sitemap_patterns = [
            '/sitemap.xml',
            '/sitemap_index.xml',
            '/wp-sitemap.xml',
            '/sitemap-posts.xml',
            '/post-sitemap.xml'
        ]
        
        for pattern in sitemap_patterns:
            sitemap_url = urljoin(base_url, pattern)
            try:
                sitemap_urls = self.extract_from_sitemap(sitemap_url)
                if sitemap_urls:
                    seed_urls.extend(sitemap_urls)
                    print(f"サイトマップ {pattern} から {len(sitemap_urls)} 個のURLを取得")
                    break  # 最初に成功したサイトマップを使用
            except Exception as e:
                print(f"サイトマップ {pattern} の取得に失敗: {e}")
        
        # 手動で重要なページを追加
        manual_pages = [
            '/column/',
            '/category/',
        ]
        
        for page in manual_pages:
            manual_url = urljoin(base_url, page)
            normalized_manual = self.normalize_url(manual_url)
            if normalized_manual not in seed_urls:
                seed_urls.append(normalized_manual)
        
        # 重複を除去
        unique_urls = []
        seen = set()
        for url in seed_urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        print(f"最終シードURL数: {len(unique_urls)}")
        return unique_urls

    def is_content(self, url):
        """コンテンツページ判定（改善版）"""
        normalized_url = self.normalize_url(url)
        parsed = urlparse(normalized_url)
        path = parsed.path.lower().rstrip('/')
        
        # クエリパラメータがある場合は除外
        if parsed.query:
            return False
        
        # more-pay.jp専用：許可パターン（より柔軟に）
        allowed_patterns = [
            r'^/?$',                                    # トップページ
            r'^/column/?$',                             # コラムトップページ
            r'^/column/[a-z0-9\-_]+/?$',               # コラム記事ページ
            r'^/column/[a-z0-9\-_]+/[a-z0-9\-_]+/?$',  # コラムサブページ（site/など）
            r'^/category/[a-z0-9\-_]+/?$',             # カテゴリページ
            r'^/category/[a-z0-9\-_]+/page/\d+/?$',    # カテゴリページネーション
            r'^/[a-z0-9\-_]+/?$',                      # 直下の記事ページ
            r'^/page/\d+/?$',                          # ページネーション
        ]
        
        if any(re.search(pattern, path) for pattern in allowed_patterns):
            # 除外パターンをチェック
            excluded_patterns = [
                r'/sitemap', r'sitemap.*\.(xml|html)$', r'-mg/?$', r'/site/?$',
                r'/wp-', r'/tag/', r'/wp-content', r'/wp-admin', r'/wp-json',
                r'/feed/', r'/privacy', r'/terms', r'/contact', r'/about', 
                r'/company', r'/go-', r'/redirect', r'/exit', r'/out',
                r'/search', r'/author/', r'/date/', r'/\d{4}/', r'/\d{4}/\d{2}/',
                r'\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|rar|doc|docx|xls|xlsx)$'
            ]
            
            if not any(re.search(e, path) for e in excluded_patterns):
                return True
        
        return False

    def is_noindex_page(self, soup):
        """NOINDEXページの判定（改善版）"""
        try:
            # metaタグのrobotsをチェック
            meta_robots = soup.find('meta', attrs={'name': 'robots'})
            if meta_robots and meta_robots.get('content'):
                content = meta_robots.get('content').lower()
                if 'noindex' in content:
                    return True
            
            # googlebotのmetaタグをチェック
            noindex_meta = soup.find('meta', attrs={'name': 'googlebot', 'content': lambda x: x and 'noindex' in x.lower()})
            if noindex_meta:
                return True
            
            # タイトルから判定
            title = soup.find('title')
            if title and title.get_text():
                title_text = title.get_text().lower()
                noindex_keywords = ['外部サイト', 'リダイレクト', '移動中', '外部リンク', 'cushion', '404', 'not found', 'error']
                if any(keyword in title_text for keyword in noindex_keywords):
                    return True
            
            # body内のテキストから判定
            body_text = soup.get_text().lower()[:1000]  # 最初の1000文字のみチェック
            noindex_phrases = [
                '外部サイトに移動します', 'リダイレクトしています', '外部リンクです',
                '別サイトに移動', 'このリンクは外部サイト', 'ページが見つかりません'
            ]
            if any(phrase in body_text for phrase in noindex_phrases):
                return True
                
            return False
            
        except Exception as e:
            print(f"NOINDEXチェック中にエラー: {e}")
            return False

    def analyze_site(self, base_url):
        try:
            pages = {}
            links = []
            detailed_links = []
            visited = set()
            to_visit = self.generate_seed_urls(base_url)
            domain = urlparse(base_url).netloc
            processed_links = set()

            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'ja,en-US;q=0.7,en;q=0.3',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive'
            })

            print(f"=== more-pay.jp 分析開始 ===")
            print(f"初期シードURL数: {len(to_visit)}")

            while to_visit and len(pages) < 1000:  # 上限を増加
                url = to_visit.pop(0)
                normalized_url = self.normalize_url(url)
                if normalized_url in visited:
                    continue

                try:
                    print(f"処理中: {normalized_url}")
                    response = session.get(url, timeout=15)  # タイムアウトを延長
                    if response.status_code != 200:
                        print(f"HTTPエラー {response.status_code}: {url}")
                        continue
                    
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    if self.is_noindex_page(soup):
                        print(f"NOINDEXページをスキップ: {url}")
                        visited.add(normalized_url)
                        continue
                    
                    extracted_links = self.extract_links(soup)
                    new_links_found = 0

                    title = self.extract_title(soup, normalized_url)
                    
                    pages[normalized_url] = {
                        'title': title,
                        'outbound_links': []
                    }

                    for link_data in extracted_links:
                        link_url = link_data['url']
                        anchor_text = link_data['anchor_text']
                        
                        # 相対URLを絶対URLに変換
                        try:
                            absolute_url = urljoin(normalized_url, link_url)
                            normalized_link = self.normalize_url(absolute_url)
                        except:
                            continue
                        
                        if (self.is_internal(normalized_link, domain) and 
                            self.is_content(normalized_link)):
                            
                            link_key = (normalized_url, normalized_link)
                            if link_key not in processed_links:
                                processed_links.add(link_key)
                                
                                links.append((normalized_url, normalized_link))
                                pages[normalized_url]['outbound_links'].append(normalized_link)
                                
                                detailed_links.append({
                                    'source_url': normalized_url,
                                    'source_title': title,
                                    'target_url': normalized_link,
                                    'anchor_text': anchor_text
                                })
                            
                            if (normalized_link not in visited and 
                                normalized_link not in to_visit):
                                to_visit.append(normalized_link)
                                new_links_found += 1

                    visited.add(normalized_url)

                    status_text = f"{len(pages)}件目: {title[:50]}..."
                    if new_links_found > 0:
                        status_text += f" (新規リンク{new_links_found}件発見)"
                    
                    self.root.after(0, lambda text=status_text: self.status_label.configure(text=text))
                    self.root.after(0, lambda: self.progress_bar.set(min(len(pages) / 1000, 1.0)))

                    time.sleep(0.2)  # レート制限を緩和

                except Exception as e:
                    print(f"エラー: {url} - {e}")
                    continue

            # 被リンク数を計算
            for url in pages:
                pages[url]['inbound_links'] = sum(1 for _, tgt in links if tgt == url)

            self.pages = pages
            self.links = links
            self.detailed_links = detailed_links
            
            print(f"=== 分析完了: {len(pages)}ページ, {len(links)}リンク ===")
            self.root.after(0, self.show_results)
            
            # 全自動化：分析完了後に自動CSVエクスポート
            if self.pages:  # データがある場合のみ
                self.root.after(2000, self.auto_export_csv)  # 2秒後に自動エクスポート
            
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("エラー", f"サイト分析中にエラーが発生しました: {e}"))
        finally:
            self.root.after(0, lambda: self.analyze_button.configure(state="normal"))
            self.root.after(0, lambda: self.progress_bar.stop())
            self.root.after(0, lambda: self.status_label.configure(text="分析完了"))

    def extract_title(self, soup, url):
        """ページタイトルの抽出（改善版）"""
        # h1タグを優先
        h1 = soup.find('h1')
        if h1 and h1.get_text(strip=True):
            return h1.get_text(strip=True)
        
        # titleタグ
        title = soup.find('title')
        if title and title.string:
            title_text = title.string.strip()
            # サイト名を除去
            title_text = re.sub(r'\s*[|\-｜]\s*.*$', '', title_text)
            if title_text:
                return title_text
        
        # og:titleを試行
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return og_title.get('content').strip()
        
        # フォールバック
        return url

    def extract_links(self, soup):
        """リンクの抽出（改善版）"""
        # WordPressの一般的なコンテンツエリアセレクタ
        content_selectors = [
            '.entry-content',          # 一般的なWordPressテーマ
            '.post-content',           # カスタムテーマ
            '.article-content',        # 記事コンテンツ
            '.content',                # 汎用コンテンツ
            'main .content',           # メインコンテンツ
            '[class*="content"]',      # contentを含むクラス
            'main',                    # メインエリア
            'article',                 # 記事エリア
            '.single-content',         # 単一記事
            '.post-body',              # 投稿本文
            '.entry-body'              # エントリー本文
        ]

        # 除外するエリアのセレクタ
        exclude_selectors = [
            'header', 'footer', 'nav', 'aside', '.sidebar', '.widget', 
            '.share', '.related', '.popular-posts', '.breadcrumb', 
            '.author-box', '.navigation', '.sns', '.social-share',
            '.comment', '.comments', '.pagination', '.tags', '.categories',
            '.meta', '.byline', '.date', '.archive'
        ]

        for selector in content_selectors:
            areas = soup.select(selector)
            if areas:
                links = []
                for area in areas:
                    # 除外エリアを削除
                    for exclude_selector in exclude_selectors:
                        for exclude_element in area.select(exclude_selector):
                            exclude_element.decompose()

                    # リンクを抽出
                    found_links = area.find_all('a', href=True)
                    for link in found_links:
                        href = link.get('href', '').strip()
                        if not href or href.startswith('#'):
                            continue
                        
                        anchor_text = link.get_text(strip=True) or link.get('title', '') or ''
                        anchor_text = anchor_text[:200]  # 長さを制限
                        
                        # 無意味なアンカーテキストをスキップ
                        if anchor_text.lower() in ['', 'link', 'リンク', 'click here', 'here', 'read more']:
                            continue
                        
                        links.append({
                            'url': href,
                            'anchor_text': anchor_text
                        })

                if links:
                    print(f"セレクタ '{selector}' で {len(links)} 個のリンクを発見")
                    return links

        # フォールバック：コンテンツエリアが見つからない場合
        print("コンテンツエリアが見つからないため、全体からリンクを抽出")
        all_links = []
        for link in soup.find_all('a', href=True):
            href = link.get('href', '').strip()
            if not href or href.startswith('#'):
                continue
            
            anchor_text = link.get_text(strip=True) or link.get('title', '') or ''
            anchor_text = anchor_text[:200]
            
            if anchor_text.lower() not in ['', 'link', 'リンク', 'click here', 'here', 'read more']:
                all_links.append({
                    'url': href,
                    'anchor_text': anchor_text
                })
        
        return all_links

    def normalize_url(self, url):
        """URL正規化（改善版）"""
        try:
            parsed = urlparse(url)
            scheme = parsed.scheme or 'https'
            netloc = parsed.netloc.replace('www.', '')
            path = parsed.path
            
            # パスの正規化
            if '/wp/' in path:
                path = path.replace('/wp/', '/')
            
            # 連続するスラッシュを単一に
            path = re.sub(r'/+', '/', path)
            
            # 末尾のスラッシュを統一（ファイル拡張子がある場合は除く）
            if path and not re.search(r'\.[a-zA-Z0-9]+$', path):
                if not path.endswith('/'):
                    path += '/'
            
            # ルートパスの場合
            if path == '':
                path = '/'
            
            return f"{scheme}://{netloc}{path}"
        except Exception as e:
            print(f"URL正規化エラー ({url}): {e}")
            return url

    def is_internal(self, url, domain):
        """内部リンク判定"""
        try:
            link_domain = urlparse(url).netloc.replace('www.', '')
            base_domain = domain.replace('www.', '')
            return link_domain == base_domain
        except:
            return False

    def show_results(self):
        self.result_frame.configure(height=400)
        for widget in self.result_frame.winfo_children():
            widget.destroy()

        total_pages = len(self.pages)
        total_links = len(self.links)
        isolated_pages = sum(1 for p in self.pages.values() if p['inbound_links'] == 0)
        popular_pages = sum(1 for p in self.pages.values() if p['inbound_links'] >= 5)

        stats_label = ctk.CTkLabel(self.result_frame,
                                   text=f"📊 分析結果: {total_pages}ページ | {total_links}内部リンク | 孤立記事{isolated_pages}件 | 人気記事{popular_pages}件",
                                   font=ctk.CTkFont(size=16, weight="bold"))
        stats_label.pack(pady=10)

        sorted_pages = sorted(self.pages.items(), key=lambda x: x[1]['inbound_links'], reverse=True)
        for i, (url, info) in enumerate(sorted_pages):
            if info['inbound_links'] == 0:
                evaluation = "🚨 要改善"
            elif info['inbound_links'] >= 10:
                evaluation = "🏆 超人気"
            elif info['inbound_links'] >= 5:
                evaluation = "✅ 人気"
            else:
                evaluation = "⚠️ 普通"

            label_text = f"{i+1:3d}. {info['title'][:50]}...\n     被リンク:{info['inbound_links']:3d} | 発リンク:{len(info['outbound_links']):3d} | {evaluation}\n     {url}"
            
            label = ctk.CTkLabel(self.result_frame,
                                 text=label_text,
                                 anchor="w", justify="left",
                                 font=ctk.CTkFont(size=11))
            label.pack(fill="x", padx=10, pady=2)

    def auto_export_csv(self):
        """全自動化：自動CSVエクスポート（EXE化対応）"""
        try:
            # EXE化対応：実行ファイルと同じディレクトリに保存
            if hasattr(sys, '_MEIPASS'):
                # PyInstallerでEXE化された場合
                base_dir = os.path.dirname(sys.executable)
            else:
                # 通常のPython実行の場合
                base_dir = os.path.dirname(os.path.abspath(__file__))
            
            # 日本の当日日付でフォルダ作成
            today = datetime.now()
            date_folder = today.strftime("%Y-%m-%d")  # 2025-06-20 形式
            folder_path = os.path.join(base_dir, date_folder)
            
            # フォルダが存在しない場合は作成
            if not os.path.exists(folder_path):
                os.makedirs(folder_path)
                print(f"日付フォルダ作成: {date_folder}")
            
            # CSVファイル名とパス
            csv_filename = f"more-pay-{date_folder}.csv"
            filename = os.path.join(folder_path, csv_filename)
            
            if not self.detailed_links:
                print("詳細データなし - CSVエクスポートをスキップ")
                return
            
            with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'A_番号', 'B_ページタイトル', 'C_URL',
                    'D_被リンク元ページタイトル', 'E_被リンク元ページURL', 'F_被リンク元ページアンカーテキスト'
                ])
                
                target_groups = {}
                for link in self.detailed_links:
                    target_url = link['target_url']
                    if target_url not in target_groups:
                        target_groups[target_url] = []
                    target_groups[target_url].append(link)
                
                sorted_targets = sorted(target_groups.items(), key=lambda x: len(x[1]), reverse=True)
                
                row_number = 1
                for target_url, links_to_target in sorted_targets:
                    target_info = self.pages.get(target_url, {})
                    target_title = target_info.get('title', target_url)
                    
                    if links_to_target:
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
                
                for url, info in self.pages.items():
                    if info['inbound_links'] == 0:
                        writer.writerow([
                            row_number,
                            info['title'],
                            url,
                            '',
                            '',
                            ''
                        ])
                        row_number += 1
            
            print(f"=== 自動CSVエクスポート完了: {folder_path}/{csv_filename} ===")
            self.status_label.configure(text=f"分析完了！CSVファイル保存: {csv_filename}")
            
        except Exception as e:
            print(f"自動CSVエクスポートエラー: {e}")
            self.status_label.configure(text="分析完了（CSV保存エラー）")

    def export_detailed_csv(self):
        if not self.detailed_links:
            messagebox.showerror("エラー", "詳細データが存在しません")
            return

        filename = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if filename:
            try:
                with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        'A_番号', 'B_ページタイトル', 'C_URL',
                        'D_被リンク元ページタイトル', 'E_被リンク元ページURL', 'F_被リンク元ページアンカーテキスト'
                    ])
                    
                    target_groups = {}
                    for link in self.detailed_links:
                        target_url = link['target_url']
                        if target_url not in target_groups:
                            target_groups[target_url] = []
                        target_groups[target_url].append(link)
                    
                    sorted_targets = sorted(target_groups.items(), key=lambda x: len(x[1]), reverse=True)
                    
                    row_number = 1
                    for target_url, links_to_target in sorted_targets:
                        target_info = self.pages.get(target_url, {})
                        target_title = target_info.get('title', target_url)
                        
                        if links_to_target:
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
                    
                    for url, info in self.pages.items():
                        if info['inbound_links'] == 0:
                            writer.writerow([
                                row_number,
                                info['title'],
                                url,
                                '',
                                '',
                                ''
                            ])
                            row_number += 1
                
                messagebox.showinfo("完了", f"詳細CSVを保存しました: {filename}")
            except Exception as e:
                messagebox.showerror("エラー", f"保存に失敗: {e}")

    def run(self):
        self.root.mainloop()

def main():
    app = MorePayAnalyzer()
    app.run()

if __name__ == "__main__":
    main()