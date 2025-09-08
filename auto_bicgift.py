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

class LinkAnalyzerApp:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("🔗 内部リンク分析ツール（bic-gift.co.jp SANGOテーマ専用・全自動版）")
        self.root.geometry("1200x800")

        self.pages = {}
        self.links = []
        self.detailed_links = []  # 詳細リンク情報用
        self.analysis_data = None
        self.is_analyzing = False

        self.setup_ui()
        
        # 全自動化：起動1秒後に自動で分析開始
        self.root.after(1000, self.auto_start_analysis)

    def setup_ui(self):
        self.main_frame = ctk.CTkScrollableFrame(self.root)
        self.main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        title_label = ctk.CTkLabel(self.main_frame, text="🔗 内部リンク分析ツール（bic-gift.co.jp SANGOテーマ専用・全自動版）",
                                   font=ctk.CTkFont(size=24, weight="bold"))
        title_label.pack(pady=20)

        self.url_entry = ctk.CTkEntry(self.main_frame, placeholder_text="https://bic-gift.co.jp", width=500)
        self.url_entry.pack(pady=10)
        self.url_entry.insert(0, "https://bic-gift.co.jp")

        self.analyze_button = ctk.CTkButton(self.main_frame, text="分析開始", command=self.start_analysis)
        self.analyze_button.pack(pady=10)

        self.status_label = ctk.CTkLabel(self.main_frame, text="")
        self.status_label.pack(pady=10)

        self.progress_bar = ctk.CTkProgressBar(self.main_frame, width=400)
        self.progress_bar.pack(pady=5)
        self.progress_bar.stop()

        self.result_frame = ctk.CTkScrollableFrame(self.main_frame, height=400)
        self.result_frame.pack(fill="both", expand=True, pady=20)

        # 詳細CSVエクスポートボタンのみ（従来CSVエクスポートは削除）
        button_frame = ctk.CTkFrame(self.main_frame)
        button_frame.pack(pady=10)
        
        self.detailed_export_btn = ctk.CTkButton(button_frame, text="詳細CSVエクスポート", command=self.export_detailed_csv)
        self.detailed_export_btn.pack(side="left", padx=5)

    def auto_start_analysis(self):
        """全自動化：自動分析開始"""
        print("=== bic-gift.co.jp (SANGO) 自動分析開始 ===")
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
                    if not re.search(r'sitemap.*\.(xml|html)$', loc_url.lower()):
                        urls.add(self.normalize_url(loc_url))
        except:
            pass
        return list(urls)

    def generate_seed_urls(self, base_url):
        sitemap_root = urljoin(base_url, '/sitemap.xml')
        sitemap_urls = self.extract_from_sitemap(sitemap_root)
        print(f"サイトマップから {len(sitemap_urls)} 個のURLを取得")
        return list(set([self.normalize_url(base_url)] + sitemap_urls))

    def is_content(self, url):
        # 正規化後のURLで判定
        normalized_url = self.normalize_url(url)
        path = urlparse(normalized_url).path.lower().split('?')[0].rstrip('/')
        
        # まず重要なページを明示的に許可
        if any(re.search(pattern, path) for pattern in [
            r'^/$',                               # トップページ
            r'^$',                                # ルート
            r'^/blog$',                           # ブログトップページ
            r'^/blog/[a-z0-9\-_]+$',             # ブログ記事ページ
            r'^/[a-z0-9\-_]+$',                  # 固定ページ・記事
            r'^/category/[a-z0-9\-_]+$',         # カテゴリページ
            r'^/category/[a-z0-9\-_]+/page/\d+$', # カテゴリページネーション
            r'^/blog/category/[a-z0-9\-_]+$',    # ブログカテゴリ
            r'^/blog/category/[a-z0-9\-_]+/page/\d+$', # ブログカテゴリページネーション
        ]):
            return True
        
        # 除外パターンをチェック
        if any(re.search(e, path) for e in [
            r'/sitemap',                    # sitemap を含むパス全て
            r'sitemap.*\.(xml|html)$',      # sitemap.xml, sitemap-*.html 等
            r'/page/\d+$',                  # ページネーション（カテゴリ以外）
            r'/site/',                      # /site/ を含むURL（リダイレクト用）
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
            r'/about',                      # 会社概要
            r'/company',                    # 会社情報
            r'/profiles',                   # 運営者情報
            r'/disclaimer',                 # 免責事項
            r'/law\.php',                   # 古物営業法
            r'\.php$',                      # PHPファイル
            r'/go-',                        # クッションページ（go-で始まる）
            r'/redirect',                   # リダイレクトページ
            r'/exit',                       # 離脱ページ
            r'/out',                        # 外部リンクページ
            r'/search',                     # 検索ページ
            r'/author/',                    # 著者ページ
            r'/date/',                      # 日付アーカイブ
            r'\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|rar|doc|docx|xls|xlsx)$'  # ファイル
        ]):
            return False
        
        # その他は基本的に許可（記事ページの可能性が高い）
        return True

    def is_noindex_page(self, soup):
        """NOINDEXページかどうか判定"""
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
            print(f"NOINDEXチェック中にエラー: {e}")
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

            session = requests.Session()
            session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})

            print(f"初期シードURL数: {len(to_visit)}")
            
            # 重複を除去
            unique_to_visit = []
            seen = set()
            for url in to_visit:
                normalized = self.normalize_url(url)
                if normalized not in seen:
                    seen.add(normalized)
                    unique_to_visit.append(normalized)
            
            to_visit = unique_to_visit
            print(f"重複除去後のシードURL数: {len(to_visit)}")

            while to_visit and len(pages) < 500:
                url = to_visit.pop(0)
                normalized_url = self.normalize_url(url)
                if normalized_url in visited:
                    continue

                try:
                    response = session.get(url, timeout=10)
                    if response.status_code != 200:
                        continue
                    
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    # NOINDEXページを除外
                    if self.is_noindex_page(soup):
                        print(f"NOINDEXページをスキップ: {url}")
                        visited.add(normalized_url)
                        continue
                    
                    # 新しいリンクを発見
                    extracted_links = self.extract_links(soup)
                    new_links_found = 0

                    # ページ情報を保存
                    title = soup.title.string.strip() if soup.title and soup.title.string else normalized_url
                    
                    # bic-gift | ビックギフト などのサイト名を除去
                    title = re.sub(r'\s*[|\-]\s*.*(bic-gift|ビックギフト).*$', '', title, flags=re.IGNORECASE)
                    
                    pages[normalized_url] = {
                        'title': title,
                        'outbound_links': []
                    }

                    # このページからの内部リンクを記録
                    for link_data in extracted_links:
                        link_url = link_data['url']
                        anchor_text = link_data['anchor_text']
                        normalized_link = self.normalize_url(link_url)
                        
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
                            if (normalized_link not in visited and 
                                normalized_link not in to_visit):
                                to_visit.append(normalized_link)
                                new_links_found += 1

                    visited.add(normalized_url)

                    # ステータス更新
                    status_text = f"{len(pages)}件目: {normalized_url[:60]}..."
                    if new_links_found > 0:
                        status_text += f" (新規リンク{new_links_found}件発見)"
                    
                    self.root.after(0, lambda text=status_text: self.status_label.configure(text=text))
                    self.root.after(0, lambda: self.progress_bar.set(min(len(pages) / 500, 1.0)))

                    time.sleep(0.1)

                except Exception as e:
                    print(f"エラー: {url} - {e}")
                    continue

            # 被リンク数を計算
            for url in pages:
                pages[url]['inbound_links'] = sum(1 for _, tgt in links if tgt == url)

            self.pages = pages
            self.links = links
            self.detailed_links = detailed_links
            
            print(f"最終結果: {len(pages)}ページ, {len(links)}リンク")
            self.root.after(0, self.show_results)
            
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("エラー", f"サイト分析中にエラーが発生しました: {e}"))
        finally:
            self.root.after(0, lambda: self.analyze_button.configure(state="normal"))
            self.root.after(0, lambda: self.progress_bar.stop())
            self.root.after(0, lambda: self.status_label.configure(text="分析完了"))
            
            # 全自動化：分析完了2秒後に自動でCSVエクスポート
            self.root.after(2000, self.auto_export_csv)

    def auto_export_csv(self):
        """全自動化：自動CSVエクスポート（EXE化対応）"""
        try:
            # EXE化対応：実行ファイルと同じディレクトリに保存
            if hasattr(sys, '_MEIPASS'):
                # PyInstaller でEXE化された場合
                base_dir = os.path.dirname(sys.executable)
            else:
                # 通常のPythonスクリプト実行の場合
                base_dir = os.path.dirname(os.path.abspath(__file__))
            
            # 日付フォルダ作成
            today = datetime.now()
            date_folder = today.strftime("%Y-%m-%d")  # 2025-06-20 形式
            folder_path = os.path.join(base_dir, date_folder)
            
            # フォルダが存在しない場合は作成
            os.makedirs(folder_path, exist_ok=True)
            print(f"日付フォルダ作成: {date_folder}")
            
            # CSVファイル名設定
            csv_filename = f"bic-gift-{date_folder}.csv"
            filename = os.path.join(folder_path, csv_filename)
            
            # 詳細CSVエクスポート実行
            self.export_detailed_csv_to_file(filename)
            
            print(f"=== 自動CSVエクスポート完了: {date_folder}/{csv_filename} ===")
            
        except Exception as e:
            print(f"自動CSVエクスポートエラー: {e}")

    def extract_links(self, soup):
        """SANGOテーマ専用のリンク抽出（詳細情報付き）"""
        # SANGOテーマ専用のセレクタ（推定）
        selectors = [
            '.entry-content',                    # SANGO標準
            '.post-content',                     # SANGO記事コンテンツ
            '.content',                          # シンプルなコンテンツ
            '.article-content',                  # 記事エリア
            '.main-content',                     # メインコンテンツ
            '.post-body',                        # 投稿本文
            '.entry-body',                       # エントリー本文
            'main .content',                     # メインエリア内のコンテンツ
            '[class*="content"]',                # content を含むクラス
            '.single-content',                   # シングルページコンテンツ
            '.page-content',                     # ページコンテンツ
            'main',                              # メインエリア
            'article'                            # 記事エリア
        ]
        
        for selector in selectors:
            areas = soup.select(selector)
            if areas:
                links = []
                for area in areas:
                    # 除外要素を削除（SANGO対応）
                    for exclude in area.select('header, footer, nav, aside, .sidebar, .widget, .share, .related, .popular-posts, .breadcrumb, .author-box, .navigation, .sns, .sns-share, .social-share, .entry-footer, .entry-meta, .post-meta, .category-list, .tag-list'):
                        exclude.decompose()
                    
                    # リンクを抽出
                    found_links = area.find_all('a', href=True)
                    for link in found_links:
                        href = link['href']
                        # 基本的な除外のみ
                        if (href and 
                            not href.startswith('#') and 
                            '/site/' not in href and
                            not any(domain in href for domain in ['facebook.com', 'twitter.com', 'x.com', 'line.me', 'hatena.ne.jp', 'instagram.com', 'getpocket.com', 'youtube.com'])):
                            
                            anchor_text = link.get_text(strip=True) or link.get('title', '') or '[リンク]'
                            links.append({
                                'url': href,
                                'anchor_text': anchor_text[:100]  # 長すぎる場合は切り詰め
                            })
                    
                if links:
                    print(f"セレクタ '{selector}' で {len(links)} 個のリンクを発見")
                    return links
        
        # フォールバック：全体からリンクを取得（ただし除外エリアは避ける）
        print("フォールバック: 全体からリンク抽出")
        # SANGOテーマでよくある除外エリアを削除
        for exclude in soup.select('header, footer, nav, aside, .sidebar, .widget, .share, .related, .popular-posts, .breadcrumb, .author-box, .navigation, .sns, .entry-footer, .post-meta'):
            exclude.decompose()
            
        all_links = []
        for link in soup.find_all('a', href=True):
            href = link['href']
            if (href and 
                not href.startswith('#') and 
                '/site/' not in href and
                not any(domain in href for domain in ['facebook.com', 'twitter.com', 'x.com', 'line.me', 'hatena.ne.jp'])):
                
                anchor_text = link.get_text(strip=True) or link.get('title', '') or '[リンク]'
                all_links.append({
                    'url': href,
                    'anchor_text': anchor_text[:100]
                })
        return all_links

    def normalize_url(self, url):
        parsed = urlparse(url)
        scheme = 'https'
        netloc = parsed.netloc.replace('www.', '')
        path = parsed.path.rstrip('/')
        
        # 重複スラッシュを修正
        path = re.sub(r'/+', '/', path)
        
        return f"{scheme}://{netloc}{path}"

    def is_internal(self, url, domain):
        return urlparse(url).netloc.replace('www.', '') == domain.replace('www.', '')

    def show_results(self):
        self.result_frame.configure(height=400)
        for widget in self.result_frame.winfo_children():
            widget.destroy()

        # 統計情報を表示
        total_pages = len(self.pages)
        total_links = len(self.links)
        isolated_pages = sum(1 for p in self.pages.values() if p['inbound_links'] == 0)
        popular_pages = sum(1 for p in self.pages.values() if p['inbound_links'] >= 5)

        stats_label = ctk.CTkLabel(self.result_frame,
                                   text=f"📊 分析結果: {total_pages}ページ | {total_links}内部リンク | 孤立記事{isolated_pages}件 | 人気記事{popular_pages}件",
                                   font=ctk.CTkFont(size=16, weight="bold"))
        stats_label.pack(pady=10)

        # 結果一覧を表示
        sorted_pages = sorted(self.pages.items(), key=lambda x: x[1]['inbound_links'], reverse=True)
        for i, (url, info) in enumerate(sorted_pages):
            # SEO評価
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

    def export_detailed_csv(self):
        """詳細CSV出力（被リンク詳細）"""
        if not self.detailed_links:
            messagebox.showerror("エラー", "詳細データが存在しません")
            return

        filename = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if filename:
            self.export_detailed_csv_to_file(filename)

    def export_detailed_csv_to_file(self, filename):
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
                
                row_number = 1
                for target_url, links_to_target in sorted_targets:
                    # ターゲットページの情報を取得
                    target_info = self.pages.get(target_url, {})
                    target_title = target_info.get('title', target_url)
                    
                    if links_to_target:
                        # 被リンクがある場合、各被リンクを1行ずつ出力
                        for link in links_to_target:
                            writer.writerow([
                                row_number,                      # A_番号
                                target_title,                    # B_ページタイトル
                                target_url,                      # C_URL
                                link['source_title'],            # D_被リンク元ページタイトル
                                link['source_url'],              # E_被リンク元ページURL
                                link['anchor_text']              # F_被リンク元ページアンカーテキスト
                            ])
                            row_number += 1
                
                # 孤立ページ（被リンクが0の）も追加
                for url, info in self.pages.items():
                    if info['inbound_links'] == 0:
                        writer.writerow([
                            row_number,         # A_番号
                            info['title'],      # B_ページタイトル
                            url,               # C_URL
                            '',                # D_被リンク元ページタイトル
                            '',                # E_被リンク元ページURL
                            ''                 # F_被リンク元ページアンカーテキスト
                        ])
                        row_number += 1
            
            messagebox.showinfo("完了", f"詳細CSVを保存しました: {filename}")
        except Exception as e:
            messagebox.showerror("エラー", f"保存に失敗: {e}")

    def run(self):
        self.root.mainloop()

def main():
    app = LinkAnalyzerApp()
    app.run()

if __name__ == "__main__":
    main()