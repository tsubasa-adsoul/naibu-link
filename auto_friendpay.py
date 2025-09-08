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

class FriendPayAnalyzer:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("🔗 friendpay専用内部リンク分析ツール（改修版・onclick対応）")
        self.root.geometry("1200x800")
        self.pages = {}
        self.links = []
        self.detailed_links = []  # 詳細リンク情報用
        self.analysis_data = None
        self.is_analyzing = False
        self.excluded_links_count = 0  # 除外されたリンク数をカウント
        
        self.setup_ui()
        
        # 自動分析開始（EXE化対応）
        self.root.after(1000, self.auto_start_analysis)  # 1秒後に自動開始

    def setup_ui(self):
        self.main_frame = ctk.CTkScrollableFrame(self.root)
        self.main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        title_label = ctk.CTkLabel(self.main_frame, text="🔗 friendpay専用内部リンク分析ツール（改修版・onclick対応）",
                                   font=ctk.CTkFont(size=28, weight="bold"))
        title_label.pack(pady=20)

        self.url_entry = ctk.CTkEntry(self.main_frame, placeholder_text="https://friendpay.jp", width=500)
        self.url_entry.pack(pady=10)
        self.url_entry.insert(0, "https://friendpay.jp")

        self.analyze_button = ctk.CTkButton(self.main_frame, text="分析開始", command=self.start_analysis)
        self.analyze_button.pack(pady=10)

        self.status_label = ctk.CTkLabel(self.main_frame, text="")
        self.status_label.pack(pady=10)

        self.progress_bar = ctk.CTkProgressBar(self.main_frame, width=400)
        self.progress_bar.pack(pady=5)
        self.progress_bar.stop()

        self.result_frame = ctk.CTkScrollableFrame(self.main_frame, height=400)
        self.result_frame.pack(fill="both", expand=True, pady=20)

        # エクスポートボタン
        ctk.CTkButton(self.main_frame, text="詳細CSVエクスポート", command=self.export_detailed_csv).pack(pady=10)

    def detect_site_type(self, url):
        """サイトタイプを判定"""
        domain = urlparse(url).netloc.lower()
        
        if 'friendpay.jp' in domain or 'friend-pay.com' in domain:
            return 'friend_pay'
        elif 'kaitori-life.co.jp' in domain or 'kaitori-life.com' in domain:
            return 'kaitori_life'
        elif 'kau-ru.co.jp' in domain:
            return 'kauru'
        elif 'kurekaeru.com' in domain:
            return 'kurekaeru'
        else:
            return 'unknown'

    def get_exclude_selectors(self, site_type):
        """サイトタイプに応じた除外セレクターを返す"""
        base_selectors = ['header', 'footer', 'nav', 'aside', '.sidebar', '.widget', '.share', '.related', '.popular-posts', '.breadcrumb', '.author-box', '.navigation']
        
        site_specific_selectors = {
            'friend_pay': [
                '.l-header__inner.l-container',   # フレンドペイ: ヘッダー内部
                '.l-footer__nav',                 # フレンドペイ: フッターナビ
                '.c-tabBody.p-postListTabBody'   # フレンドペイ: タブボディ
            ],
            'kaitori_life': [
                '#nav-container.header-style4-animate.animate'  # 買取LIFE: ナビゲーション
            ],
            'kauru': [
                '.textwidget',                    # カウール: textwidget
                '.textwidget.custom-html-widget'  # カウール: custom-html-widget付きtextwidget
            ],
            'kurekaeru': [
                '#gnav.l-header__gnav.c-gnavWrap'  # クレかえる: グローバルナビ
            ]
        }
        
        return base_selectors + site_specific_selectors.get(site_type, [])

    def auto_start_analysis(self):
        """EXE化対応：自動で分析開始"""
        print("=== friendpay.jp 自動分析開始 ===")
        self.status_label.configure(text="自動分析を開始します...")
        self.start_analysis()

    def start_analysis(self):
        url = self.url_entry.get().strip()
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        # サイトタイプを判定
        site_type = self.detect_site_type(url)
        print(f"サイトタイプ判定: {site_type}")
        
        self.analyze_button.configure(state="disabled")
        self.status_label.configure(text="クロール中...")
        self.progress_bar.start()
        self.excluded_links_count = 0  # リセット
        
        thread = threading.Thread(target=self.analyze_site, args=(url,))
        thread.daemon = True
        thread.start()

    def extract_from_sitemap(self, url):
        urls = set()
        try:
            res = requests.get(url, timeout=10)
            res.raise_for_status()
            soup = BeautifulSoup(res.content, 'xml')
            locs = soup.find_all('loc')
            if soup.find('sitemapindex'):
                for loc in locs:
                    urls.update(self.extract_from_sitemap(loc.text.strip()))
            else:
                for loc in locs:
                    loc_url = loc.text.strip()
                    # サイトマップファイル自体は除外
                    if not re.search(r'sitemap.*\.(xml|html)$', loc_url.lower()):
                        urls.add(self.normalize_url(loc_url))
        except Exception as e:
            print(f"サイトマップ取得エラー: {e}")
        return list(urls)

    def generate_seed_urls(self, base_url):
        seed_urls = [self.normalize_url(base_url)]
        
        # サイトマップからURL取得
        sitemap_root = urljoin(base_url, '/sitemap.xml')
        sitemap_urls = self.extract_from_sitemap(sitemap_root)
        seed_urls.extend(sitemap_urls)
        
        print(f"=== {urlparse(base_url).netloc} 分析開始 ===")
        print(f"サイトマップから {len(sitemap_urls)} 個のURLを取得")
        print(f"総シードURL数: {len(seed_urls)}")
        return list(set(seed_urls))

    def is_content(self, url):
        """コンテンツページかどうか判定"""
        if not url:
            return False
            
        try:
            # 正規化後のURLで判定
            normalized_url = self.normalize_url(url)
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
            exclude_patterns = [
                r'/sitemap', r'sitemap.*\.(xml|html)$', r'/page/\d+$', r'-mg',
                r'/site/', r'/wp-', r'/tag/', r'/wp-content', r'/wp-admin', r'/wp-json',
                r'#', r'\?utm_', r'/feed/', r'mailto:', r'tel:', r'/privacy', r'/terms',
                r'/contact', r'/go-', r'/redirect', r'/exit', r'/out',
                r'\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|rar|doc|docx|xls|xlsx)$'
            ]
            
            for pattern in exclude_patterns:
                if re.search(pattern, path):
                    return False
            
            return True
            
        except Exception as e:
            print(f"is_content判定エラー: {url} -> {e}")
            return False

    def is_noindex_page(self, soup):
        """NOINDEXページかどうか判定"""
        try:
            # robots meta タグをチェック
            meta_robots = soup.find('meta', attrs={'name': 'robots'})
            if meta_robots and meta_robots.get('content'):
                content = meta_robots.get('content').lower()
                if 'noindex' in content:
                    return True
            
            # クッションページの典型的なパターンをチェック
            title = soup.find('title')
            if title and title.get_text():
                title_text = title.get_text().lower()
                if any(keyword in title_text for keyword in ['外部サイト', 'リダイレクト', '移動中', '外部リンク', 'cushion']):
                    return True
            
            # bodyに警告テキストがある場合
            body_text = soup.get_text().lower()
            if any(phrase in body_text for phrase in [
                '外部サイトに移動します',
                'リダイレクトしています',
                '外部リンクです',
                '別サイトに移動',
                'このリンクは外部サイト'
            ]):
                return True
                
            return False
            
        except Exception as e:
            print(f"NOINDEXチェック中にエラー: {e}")
            return False

    def normalize_url(self, url):
        """URL正規化処理（フレンドペイ対応）"""
        if not url:
            return ""
            
        # 相対URLの処理
        if url.startswith('/'):
            try:
                base_domain = f"{urlparse(self.url_entry.get()).scheme}://{urlparse(self.url_entry.get()).netloc}"
                url = base_domain + url
            except:
                return ""
        
        try:
            parsed = urlparse(url)
            scheme = 'https'
            netloc = parsed.netloc.replace('www.', '')
            path = parsed.path.rstrip('/')

            # friendpay.jp専用の正規化
            if '/wp/' in path:
                path = path.replace('/wp/', '/')

            # 重複スラッシュを修正
            path = re.sub(r'/+', '/', path)

            # トップページ以外には末尾スラッシュを付与
            if path and not path.endswith('/'):
                path += '/'

            return f"{scheme}://{netloc}{path}"
        except Exception as e:
            print(f"URL正規化エラー: {url} -> {e}")
            return ""

    def is_internal(self, url, domain):
        try:
            return urlparse(url).netloc.replace('www.', '') == domain.replace('www.', '')
        except:
            return False

    def analyze_site(self, base_url):
        try:
            pages = {}
            links = []
            detailed_links = []  # 詳細リンク情報用
            visited = set()
            to_visit = self.generate_seed_urls(base_url)
            domain = urlparse(base_url).netloc
            processed_links = set()  # 重複除去用
            site_type = self.detect_site_type(base_url)

            session = requests.Session()
            session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})

            # 重複除去
            unique_to_visit = []
            seen = set()
            for url in to_visit:
                normalized = self.normalize_url(url)
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    unique_to_visit.append(normalized)
            
            to_visit = unique_to_visit
            print(f"重複除去後のシードURL数: {len(to_visit)}")

            while to_visit and len(pages) < 500:
                url = to_visit.pop(0)
                normalized_url = self.normalize_url(url)
                if not normalized_url or normalized_url in visited:
                    continue

                try:
                    print(f"処理中: {normalized_url}")
                    response = session.get(url, timeout=15)
                    if response.status_code != 200:
                        print(f"  HTTPエラー: {response.status_code}")
                        continue
                    
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    # NOINDEXページを除外
                    if self.is_noindex_page(soup):
                        print(f"  NOINDEXページをスキップ: {url}")
                        visited.add(normalized_url)
                        continue
                    
                    extracted_links = self.extract_links(soup, site_type)
                    new_links_found = 0

                    # ページ情報を保存
                    title = soup.title.string.strip() if soup.title and soup.title.string else normalized_url
                    # サイト名除去
                    for site_name in ['friendpay', 'フレンドペイ', 'friend-pay']:
                        title = re.sub(rf'\s*[|\-]\s*.*{re.escape(site_name)}.*$', '', title, flags=re.IGNORECASE)
                    title = title.strip()
                    
                    pages[normalized_url] = {'title': title, 'outbound_links': []}

                    # このページからの内部リンクを記録
                    for link in extracted_links:
                        normalized_link = self.normalize_url(link['url'])
                        if not normalized_link:
                            continue
                            
                        anchor_text = link['anchor_text']
                        
                        if (self.is_internal(normalized_link, domain) and 
                            self.is_content(normalized_link)):
                            
                            # 重複チェック（同じソース→ターゲットのリンクは1回だけ）
                            link_key = (normalized_url, normalized_link)
                            if link_key not in processed_links:
                                processed_links.add(link_key)
                                
                                links.append((normalized_url, normalized_link))
                                pages[normalized_url]['outbound_links'].append(normalized_link)
                                
                                # 詳細リンク情報を保存
                                detailed_links.append({
                                    'source_url': normalized_url,
                                    'source_title': title,
                                    'target_url': normalized_link,
                                    'anchor_text': anchor_text
                                })
                        
                        # 新規URLの発見
                        if (self.is_internal(normalized_link, domain) and
                            self.is_content(normalized_link) and
                            normalized_link not in visited and
                            normalized_link not in to_visit):
                            to_visit.append(normalized_link)
                            new_links_found += 1

                    visited.add(normalized_url)

                    status_text = f"{len(pages)}件目: {title[:50]}..."
                    if new_links_found > 0:
                        status_text += f" (新規リンク{new_links_found}件発見)"
                    
                    self.root.after(0, lambda text=status_text: self.status_label.configure(text=text))
                    self.root.after(0, lambda: self.progress_bar.set(min(len(pages) / 500, 1.0)))
                    time.sleep(0.1)

                except Exception as e:
                    print(f"  エラー: {e}")
                    continue

            # 被リンク数を計算
            for url in pages:
                pages[url]['inbound_links'] = len(set([src for src, tgt in links if tgt == url]))

            self.pages = pages
            self.links = links
            self.detailed_links = detailed_links
            
            print(f"=== 分析完了: {len(pages)}ページ, {len(links)}リンク, 除外{self.excluded_links_count}リンク ===")
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

    def extract_links(self, soup, site_type):
        """フレンドペイ専用の最適化されたリンク抽出（サイト別除外対応・onclick対応版）"""
        selectors = [
            '.post_content',           # フレンドペイ専用
            '.entry-content',          # WordPress一般
            '.article-content',        # 記事コンテンツ
            'main .content',           # メインコンテンツ
            '[class*="content"]',      # content を含むクラス
            'main',                    # メインエリア
            'article'                  # 記事エリア
        ]
        
        exclude_selectors = self.get_exclude_selectors(site_type)
        
        print(f"  サイトタイプ {site_type} の除外セレクター: {exclude_selectors}")
        
        for selector in selectors:
            areas = soup.select(selector)
            if areas:
                links = []
                for area in areas:
                    # サイト別除外処理
                    excluded_count = 0
                    for exclude_selector in exclude_selectors:
                        excluded_elements = area.select(exclude_selector)
                        for elem in excluded_elements:
                            excluded_count += len(elem.find_all('a', href=True))
                            excluded_count += len(elem.find_all(attrs={'onclick': True}))
                            elem.decompose()
                    
                    if excluded_count > 0:
                        print(f"    除外したリンク数: {excluded_count}")
                        self.excluded_links_count += excluded_count
                    
                    # 1. 通常のaタグリンクを抽出
                    found_links = area.find_all('a', href=True)
                    for link in found_links:
                        anchor_text = link.get_text(strip=True) or link.get('title', '') or '[リンク]'
                        links.append({
                            'url': link['href'],
                            'anchor_text': anchor_text[:100]
                        })
                    
                    # 2. onclick属性のあるタグを抽出（フレンドペイ特有）
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
                            print(f"    onclick リンク検出: {extracted_url} (アンカー: {anchor_text})")
                
                if links:
                    print(f"  セレクタ '{selector}' で {len(links)} 個のリンクを発見")
                    return links
        
        # フォールバック
        print("  フォールバック処理でリンク抽出")
        all_links = []
        
        # 通常のaタグ
        for link in soup.find_all('a', href=True):
            anchor_text = link.get_text(strip=True) or link.get('title', '') or '[リンク]'
            all_links.append({
                'url': link['href'],
                'anchor_text': anchor_text[:100]
            })
        
        # onclick属性のタグ
        onclick_elements = soup.find_all(attrs={'onclick': True})
        for element in onclick_elements:
            onclick_attr = element.get('onclick', '')
            url_match = re.search(r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]", onclick_attr)
            if url_match:
                extracted_url = url_match.group(1)
                anchor_text = element.get_text(strip=True) or element.get('title', '') or '[onclick リンク]'
                all_links.append({
                    'url': extracted_url,
                    'anchor_text': anchor_text[:100]
                })
        
        return all_links

    def show_results(self):
        for widget in self.result_frame.winfo_children():
            widget.destroy()

        total_pages = len(self.pages)
        total_links = len(self.links)
        isolated_pages = sum(1 for p in self.pages.values() if p['inbound_links'] == 0)
        popular_pages = sum(1 for p in self.pages.values() if p['inbound_links'] >= 5)

        stats_label = ctk.CTkLabel(self.result_frame,
                                   text=f"📊 分析結果: {total_pages}ページ | {total_links}内部リンク | 除外{self.excluded_links_count}リンク | 孤立記事{isolated_pages}件 | 人気記事{popular_pages}件",
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
            
            label = ctk.CTkLabel(self.result_frame, text=label_text, anchor="w", justify="left", font=ctk.CTkFont(size=11))
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
            csv_filename = f"friendpay-{date_folder}.csv"
            filename = os.path.join(folder_path, csv_filename)
            
            if not self.detailed_links:
                print("詳細データなし - CSVエクスポートをスキップ")
                return
            
            with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                # ヘッダー行（6列構成）
                writer.writerow([
                    'A_番号', 'B_ページタイトル', 'C_URL',
                    'D_被リンク元ページタイトル', 'E_被リンク元ページURL', 'F_被リンク元ページアンカーテキスト'
                ])
                
                # ターゲットURL別にグループ化
                target_groups = {}
                for link in self.detailed_links:
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
                    target_info = self.pages.get(target_url, {})
                    target_title = target_info.get('title', target_url)
                    page_key = (target_title, target_url)
                    
                    if page_key not in page_numbers:
                        page_numbers[page_key] = current_page_number
                        current_page_number += 1
                
                # 孤立ページの番号割り当て
                for url, info in self.pages.items():
                    if info['inbound_links'] == 0:
                        page_key = (info['title'], url)
                        if page_key not in page_numbers:
                            page_numbers[page_key] = current_page_number
                            current_page_number += 1
                
                # 被リンクありページの出力
                for target_url, links_to_target in sorted_targets:
                    target_info = self.pages.get(target_url, {})
                    target_title = target_info.get('title', target_url)
                    page_key = (target_title, target_url)
                    page_number = page_numbers[page_key]
                    
                    if links_to_target:
                        # 被リンクがある場合、各被リンクを1行ずつ出力（同じページ番号）
                        for link in links_to_target:
                            writer.writerow([
                                page_number,                     # A_番号（統一）
                                target_title,                    # B_ページタイトル
                                target_url,                      # C_URL
                                link['source_title'],            # D_被リンク元ページタイトル
                                link['source_url'],              # E_被リンク元ページURL
                                link['anchor_text']              # F_被リンク元ページアンカーテキスト
                            ])
                
                # 孤立ページ（被リンクが0の）の出力
                for url, info in self.pages.items():
                    if info['inbound_links'] == 0:
                        page_key = (info['title'], url)
                        page_number = page_numbers[page_key]
                        
                        writer.writerow([
                            page_number,        # A_番号
                            info['title'],      # B_ページタイトル
                            url,               # C_URL
                            '',                # D_被リンク元ページタイトル
                            '',                # E_被リンク元ページURL
                            ''                 # F_被リンク元ページアンカーテキスト
                        ])
            
            print(f"=== 自動CSVエクスポート完了: {folder_path}/{csv_filename} ===")
            print(f"ユニークページ数: {len(page_numbers)}")
            self.status_label.configure(text=f"分析完了！CSVファイル保存: {csv_filename}")
            
        except Exception as e:
            print(f"自動CSVエクスポートエラー: {e}")
            self.status_label.configure(text="分析完了（CSV保存エラー）")

    def export_detailed_csv(self):
        """詳細CSV出力（被リンク詳細）"""
        if not self.detailed_links:
            messagebox.showerror("エラー", "詳細データが存在しません")
            return

        today = datetime.now().strftime("%Y-%m-%d")
        default_filename = f"friendpay-{today}.csv"

        filename = filedialog.asksaveasfilename(
            defaultextension=".csv", 
            filetypes=[("CSV files", "*.csv")],
            initialvalue=default_filename
        )
        
        if filename:
            try:
                with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    # ヘッダー行（6列構成）
                    writer.writerow([
                        'A_番号', 'B_ページタイトル', 'C_URL',
                        'D_被リンク元ページタイトル', 'E_被リンク元ページURL', 'F_被リンク元ページアンカーテキスト'
                    ])
                    
                    # ターゲットURL別にグループ化
                    target_groups = {}
                    for link in self.detailed_links:
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
                        target_info = self.pages.get(target_url, {})
                        target_title = target_info.get('title', target_url)
                        page_key = (target_title, target_url)
                        
                        if page_key not in page_numbers:
                            page_numbers[page_key] = current_page_number
                            current_page_number += 1
                    
                    # 孤立ページの番号割り当て
                    for url, info in self.pages.items():
                        if info['inbound_links'] == 0:
                            page_key = (info['title'], url)
                            if page_key not in page_numbers:
                                page_numbers[page_key] = current_page_number
                                current_page_number += 1
                    
                    # 被リンクありページの出力
                    for target_url, links_to_target in sorted_targets:
                        target_info = self.pages.get(target_url, {})
                        target_title = target_info.get('title', target_url)
                        page_key = (target_title, target_url)
                        page_number = page_numbers[page_key]
                        
                        if links_to_target:
                            # 被リンクがある場合、各被リンクを1行ずつ出力（同じページ番号）
                            for link in links_to_target:
                                writer.writerow([
                                    page_number,                     # A_番号（統一）
                                    target_title,                    # B_ページタイトル
                                    target_url,                      # C_URL
                                    link['source_title'],            # D_被リンク元ページタイトル
                                    link['source_url'],              # E_被リンク元ページURL
                                    link['anchor_text']              # F_被リンク元ページアンカーテキスト
                                ])
                    
                    # 孤立ページ（被リンクが0の）の出力
                    for url, info in self.pages.items():
                        if info['inbound_links'] == 0:
                            page_key = (info['title'], url)
                            page_number = page_numbers[page_key]
                            
                            writer.writerow([
                                page_number,        # A_番号
                                info['title'],      # B_ページタイトル
                                url,               # C_URL
                                '',                # D_被リンク元ページタイトル
                                '',                # E_被リンク元ページURL
                                ''                 # F_被リンク元ページアンカーテキスト
                            ])
                
                messagebox.showinfo("完了", f"詳細CSVを保存しました: {filename}\nユニークページ数: {len(page_numbers)}")
            except Exception as e:
                messagebox.showerror("エラー", f"保存に失敗: {e}")

    def run(self):
        self.root.mainloop()

def main():
    app = FriendPayAnalyzer()
    app.run()

if __name__ == "__main__":
    main()