import tkinter as tk
from tkinter import messagebox, filedialog
import customtkinter as ctk
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import time
import re
import threading
import csv
import sys
import os
from datetime import datetime

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

class LinkAnalyzerApp:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("🔗 famipay専用内部リンク分析ツール（全自動版）")
        self.root.geometry("1200x800")

        self.pages = {}
        self.links = []
        self.detailed_links = []  # 詳細リンク情報用

        self.setup_ui()
        
        # 全自動化：起動1秒後に自動で分析開始
        self.root.after(1000, self.auto_start_analysis)

    def setup_ui(self):
        self.main_frame = ctk.CTkScrollableFrame(self.root)
        self.main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        title_label = ctk.CTkLabel(self.main_frame, text="🔗 famipay専用内部リンク分析ツール（全自動版）",
                                   font=ctk.CTkFont(size=32, weight="bold"))
        title_label.pack(pady=20)

        self.url_entry = ctk.CTkEntry(self.main_frame, placeholder_text="https://flashpay.jp/famipay/", width=500)
        self.url_entry.pack(pady=10)
        self.url_entry.insert(0, "https://flashpay.jp/famipay/")

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
        print("=== famipay (flashpay.jp/famipay/) 自動分析開始 ===")
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

    def extract_links_for_crawling(self, soup):
        """ページ収集用：全体からリンクを取得"""
        all_links = soup.find_all('a', href=True)
        valid_links = []
        
        for link in all_links:
            href = link.get('href', '')
            # 基本的な除外のみ
            if (href and 
                not href.startswith('#') and 
                '/site/' not in href and
                not any(domain in href for domain in ['facebook.com', 'twitter.com', 'x.com', 'line.me', 'hatena.ne.jp'])):
                valid_links.append(link)
        
        return [a['href'] for a in valid_links]

    def extract_links(self, soup):
        """リンク分析用：記事本文のみから取得（詳細情報付き）"""
        content_area = soup.select_one('.entry-content')
        if not content_area:
            return []
        
        all_links = content_area.find_all('a', href=True)
        valid_links = []
        
        for link in all_links:
            href = link.get('href', '')
            
            # 最低限の除外のみ
            if (href and 
                not href.startswith('#') and 
                '/site/' not in href and
                'respond' not in href and
                self.is_internal(href, 'flashpay.jp')):
                
                # アンカーテキストを取得
                anchor_text = link.get_text(strip=True) or link.get('title', '') or '[リンク]'
                valid_links.append({
                    'url': href,
                    'anchor_text': anchor_text[:100]  # 長すぎる場合は切り詰め
                })
        
        return valid_links

    def is_content(self, url):
        normalized_url = self.normalize_url(url)
        path = urlparse(normalized_url).path.lower().split('?')[0].rstrip('/')
        # /famipay/ 直下の記事 または トップページ
        if path == '/famipay':
            return True
        return path.startswith('/famipay/') and re.match(r'^/famipay/[a-z0-9\-]+$', path)

    def is_noindex_page(self, soup):
        try:
            meta_robots = soup.find('meta', attrs={'name': 'robots'})
            if meta_robots and 'noindex' in meta_robots.get('content', '').lower():
                return True
            noindex_meta = soup.find('meta', attrs={'name': 'googlebot', 'content': lambda x: x and 'noindex' in x.lower()})
            if noindex_meta:
                return True
            return False
        except:
            return False

    def normalize_url(self, url):
        parsed = urlparse(url)
        scheme = 'https'
        netloc = parsed.netloc.replace('www.', '')
        path = re.sub(r'/+', '/', parsed.path.rstrip('/'))
        return f"{scheme}://{netloc}{path}"

    def is_internal(self, url, domain):
        parsed_url = urlparse(url)
        url_domain = parsed_url.netloc.replace('www.', '')
        target_domain = domain.replace('www.', '')
        return url_domain == target_domain

    def analyze_site(self, base_url):
        try:
            pages = {}
            links = []
            detailed_links = []  # 詳細リンク情報用
            visited = set()
            to_visit = [self.normalize_url(base_url)]
            domain = urlparse(base_url).netloc
            processed_links = set()  # 重複除去用

            session = requests.Session()
            session.headers.update({'User-Agent': 'Mozilla/5.0'})

            # 第1段階: ページを収集
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
                    
                    if self.is_noindex_page(soup):
                        visited.add(normalized_url)
                        continue

                    # ページ情報を保存
                    title = soup.title.string.strip() if soup.title and soup.title.string else normalized_url
                    
                    # famipay | ファミペイ などのサイト名を除去
                    title = re.sub(r'\s*[|\-]\s*.*(famipay|ファミペイ|flashpay|フラッシュペイ).*$', '', title, flags=re.IGNORECASE)
                    
                    pages[normalized_url] = {'title': title, 'outbound_links': []}

                    # 新しいリンクを探索リストに追加
                    extracted_links = self.extract_links_for_crawling(soup)
                    for link in extracted_links:
                        normalized_link = self.normalize_url(link)
                        
                        # /site/ を含むリンクは除外
                        if '/site/' in normalized_link:
                            continue
                            
                        if (self.is_internal(normalized_link, domain) and 
                            self.is_content(normalized_link) and 
                            normalized_link not in visited and 
                            normalized_link not in to_visit):
                            to_visit.append(normalized_link)

                    visited.add(normalized_url)

                    self.root.after(0, lambda text=f"{len(pages)}件目: {normalized_url[:60]}...": self.status_label.configure(text=text))
                    self.root.after(0, lambda: self.progress_bar.set(min(len(pages) / 500, 1.0)))
                    time.sleep(0.1)
                    
                except Exception as e:
                    print(f"エラー: {url} - {e}")
                    continue

            # 第2段階: リンク関係を構築（改良版）
            print(f"リンク関係構築開始: {len(pages)}ページを処理")
            session = requests.Session()
            session.headers.update({'User-Agent': 'Mozilla/5.0'})
            
            for url in list(pages.keys()):
                try:
                    response = session.get(url, timeout=10)
                    if response.status_code != 200:
                        continue
                        
                    soup = BeautifulSoup(response.text, 'html.parser')
                    extracted_links = self.extract_links(soup)  # 詳細情報付きリンク取得
                    
                    # creditcard記事の場合は詳細出力
                    if 'creditcard' in url:
                        print(f"デバッグ: {url} で{len(extracted_links)}個のリンクを検出:")
                        for link in extracted_links:
                            print(f"  - {link}")
                    
                    # このページからの内部リンクを記録（クロールした記事のみ）
                    for link_data in extracted_links:
                        link_url = link_data['url']
                        anchor_text = link_data['anchor_text']
                        normalized_link = self.normalize_url(link_url)

                        # 除外条件1: /site/ を含むリンク
                        if '/site/' in normalized_link:
                            continue

                        # 除外条件2: クロールした記事に含まれていないリンクは除外
                        if normalized_link not in pages:
                            continue

                        # 除外条件3: 同じページへのリンクは除外
                        if normalized_link == url:
                            continue

                        if self.is_internal(normalized_link, domain) and self.is_content(normalized_link):
                            # 重複チェック（同じソース→ターゲットのリンクは1回だけ）
                            link_key = (url, normalized_link)
                            if link_key not in processed_links:
                                processed_links.add(link_key)
                                
                                links.append((url, normalized_link))
                                pages[url]['outbound_links'].append(normalized_link)
                                
                                # 詳細リンク情報を保存
                                detailed_links.append({
                                    'source_url': url,
                                    'source_title': pages[url]['title'],
                                    'target_url': normalized_link,
                                    'anchor_text': anchor_text
                                })
                                
                                print(f"  {url} -> {normalized_link} (アンカー: {anchor_text})")
                            
                except Exception as e:
                    print(f"リンク解析エラー: {url} - {e}")
                    continue

            # 被リンク数を計算
            for url in pages:
                pages[url]['inbound_links'] = len(set([src for src, tgt in links if tgt == url]))
                
            print(f"分析完了: {len(pages)}ページ、{len(links)}リンク（重複除去後）")

            self.pages = pages
            self.links = links
            self.detailed_links = detailed_links
            self.root.after(0, self.show_results)
            
        except Exception as e:
            print(f"分析エラー: {e}")
            self.root.after(0, lambda: self.status_label.configure(text=f"エラーが発生しました: {e}"))
        finally:
            self.root.after(0, lambda: self.analyze_button.configure(state="normal"))
            self.root.after(0, lambda: self.progress_bar.stop())
            if hasattr(self, 'pages') and self.pages:
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
            csv_filename = f"famipay-{date_folder}.csv"
            filename = os.path.join(folder_path, csv_filename)
            
            # 詳細CSVエクスポート実行
            self.export_detailed_csv_to_file(filename)
            
            print(f"=== 自動CSVエクスポート完了: {date_folder}/{csv_filename} ===")
            
        except Exception as e:
            print(f"自動CSVエクスポートエラー: {e}")

    def show_results(self):
        self.result_frame.configure(height=400)
        for widget in self.result_frame.winfo_children():
            widget.destroy()
            
        total_pages = len(self.pages)
        total_links = len(self.links)
        isolated_pages = sum(1 for p in self.pages.values() if p['inbound_links'] == 0)
        popular_pages = sum(1 for p in self.pages.values() if p['inbound_links'] >= 5)
        
        stats_label = ctk.CTkLabel(self.result_frame,
                                   text=f"📊 分析結果: {total_pages}ページ | {total_links}内部リンク（重複除去後） | 孤立記事{isolated_pages}件 | 人気記事{popular_pages}件",
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
                
            label_text = (
                f"{i+1:3d}. {info['title'][:50]}...\n"
                f"     被リンク:{info['inbound_links']:3d} | 発リンク:{len(info['outbound_links']):3d} | {evaluation}\n"
                f"     {url}"
            )

            label = ctk.CTkLabel(self.result_frame, text=label_text, anchor="w", justify="left", font=ctk.CTkFont(size=11))
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