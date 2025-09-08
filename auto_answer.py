import tkinter as tk
from tkinter import messagebox, filedialog
import customtkinter as ctk
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import time
import re
import threading
import csv
import sys
import os
from datetime import datetime

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

class AnswerAnalyzer:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("🔗 answer-genkinka.jp専用内部リンク分析ツール（全自動版）")
        self.root.geometry("1200x800")
        
        self.pages = {}
        self.links = []
        self.detailed_links = []
        
        self.setup_ui()
        
        # 全自動化：起動1秒後に自動で分析開始
        self.root.after(1000, self.auto_start_analysis)

    def setup_ui(self):
        main_frame = ctk.CTkScrollableFrame(self.root)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # タイトル
        ctk.CTkLabel(main_frame, text="🔗 answer-genkinka.jp専用内部リンク分析ツール（全自動版）", 
                    font=ctk.CTkFont(size=28, weight="bold")).pack(pady=20)

        # URL入力
        self.url_entry = ctk.CTkEntry(main_frame, placeholder_text="https://answer-genkinka.jp/blog/", width=500)
        self.url_entry.pack(pady=10)
        self.url_entry.insert(0, "https://answer-genkinka.jp/blog/")

        # 分析ボタン
        self.analyze_btn = ctk.CTkButton(main_frame, text="分析開始", command=self.start_analysis)
        self.analyze_btn.pack(pady=10)

        # ステータス
        self.status_label = ctk.CTkLabel(main_frame, text="")
        self.status_label.pack(pady=10)

        # プログレスバー
        self.progress = ctk.CTkProgressBar(main_frame, width=400)
        self.progress.pack(pady=5)

        # 結果エリア
        self.result_frame = ctk.CTkScrollableFrame(main_frame, height=400)
        self.result_frame.pack(fill="both", expand=True, pady=20)

        # 詳細CSVエクスポートボタンのみ（従来CSVエクスポートは削除）
        btn_frame = ctk.CTkFrame(main_frame)
        btn_frame.pack(pady=10)
        ctk.CTkButton(btn_frame, text="詳細CSVエクスポート", command=self.export_detailed).pack(side="left", padx=5)

    def auto_start_analysis(self):
        """全自動化：自動分析開始"""
        print("=== answer-genkinka.jp 自動分析開始 ===")
        self.start_analysis()

    def normalize_url(self, url):
        if not url: return ""
        try:
            parsed = urlparse(url)
            return f"https://{parsed.netloc.replace('www.', '')}{parsed.path.rstrip('/')}"
        except:
            return url

    def is_article_page(self, url):
        """個別記事ページかどうか判定（シンプル版）"""
        path = urlparse(self.normalize_url(url)).path.lower()
        
        # 除外：明らかに記事ではないもの
        exclude_words = ['/site/', '/blog/', '/page/', '/feed', '/wp-', '.']
        if any(word in path for word in exclude_words):
            return False
        
        # 許可：ルート直下のスラッグ（/記事名）
        if path.startswith('/') and len(path) > 1:
            # パスからスラッシュを除去
            clean_path = path[1:].rstrip('/')
            # スラッシュが含まれていなくて、文字がある
            if clean_path and '/' not in clean_path:
                return True
        
        return False

    def is_crawlable(self, url):
        """クロール対象かどうか判定"""
        path = urlparse(self.normalize_url(url)).path.lower()
        
        # 除外：明らかに不要なもの
        exclude_words = ['/site/', '/wp-admin', '/feed', '.jpg', '.png', '.css', '.js']
        if any(word in path for word in exclude_words):
            return False
        
        # 許可：ブログ関連 + 記事ページ
        return (path.startswith('/blog') or self.is_article_page(url))

    def extract_links(self, soup, current_url):
        """リンク抽出"""
        links = []
        for a in soup.find_all('a', href=True):
            href = a.get('href', '').strip()
            if href and not href.startswith('#'):
                absolute = urljoin(current_url, href)
                if 'answer-genkinka.jp' in absolute and self.is_crawlable(absolute):
                    links.append(self.normalize_url(absolute))
        return list(set(links))

    def extract_content_links(self, soup, current_url):
        """コンテンツエリアからリンク抽出"""
        content = soup.select_one('.entry-content, .post-content, main, article')
        if not content:
            return []
        
        links = []
        for a in content.find_all('a', href=True):
            href = a.get('href', '').strip()
            text = a.get_text(strip=True) or ''
            if href and not href.startswith('#') and text:
                absolute = urljoin(current_url, href)
                if 'answer-genkinka.jp' in absolute and self.is_article_page(absolute):
                    links.append({'url': self.normalize_url(absolute), 'anchor_text': text[:100]})
        return links

    def start_analysis(self):
        self.analyze_btn.configure(state="disabled")
        threading.Thread(target=self.analyze, daemon=True).start()

    def analyze(self):
        try:
            self.pages, self.links, self.detailed_links = {}, [], []
            visited, to_visit = set(), [self.normalize_url(self.url_entry.get())]
            
            # ページネーションを追加
            to_visit.append('https://answer-genkinka.jp/blog/page/2/')

            session = requests.Session()
            session.headers.update({'User-Agent': 'Mozilla/5.0'})

            print("=== answer-genkinka.jp 分析開始 ===")

            # フェーズ1: ページ収集
            while to_visit and len(self.pages) < 500:
                url = to_visit.pop(0)
                if url in visited: continue
                
                try:
                    print(f"処理中: {url}")
                    response = session.get(url, timeout=10)
                    if response.status_code != 200: 
                        print(f"  HTTPエラー: {response.status_code}")
                        continue
                    
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    # NOINDEXチェック
                    robots = soup.find('meta', attrs={'name': 'robots'})
                    if robots and 'noindex' in robots.get('content', '').lower():
                        print(f"  NOINDEXをスキップ")
                        continue
                    
                    # 記事一覧ページは収集のみ
                    if '/blog' in url:
                        page_links = self.extract_links(soup, url)
                        new_links = [l for l in page_links if l not in visited and l not in to_visit]
                        to_visit.extend(new_links)
                        visited.add(url)
                        print(f"  一覧ページ: {len(new_links)}件の新規リンク")
                        continue
                    
                    # 個別記事ページを保存
                    if self.is_article_page(url):
                        title = soup.find('h1')
                        title = title.get_text(strip=True) if title else url
                        
                        # answer-genkinka | アンサー などのサイト名を除去
                        title = re.sub(r'\s*[|\-]\s*.*(answer-genkinka|アンサー).*$', '', title, flags=re.IGNORECASE)
                        
                        self.pages[url] = {'title': title, 'outbound_links': []}
                        
                        # 新しいリンクを発見
                        page_links = self.extract_links(soup, url)
                        new_links = [l for l in page_links if l not in visited and l not in to_visit]
                        to_visit.extend(new_links)
                        
                        print(f"  記事: {title}")
                        print(f"  新規: {len(new_links)}件")
                    
                    visited.add(url)
                    
                    self.root.after(0, lambda: self.status_label.configure(text=f"収集中: {len(self.pages)}記事"))
                    self.root.after(0, lambda: self.progress.set(len(self.pages) / 500))
                    time.sleep(0.1)
                    
                except Exception as e:
                    print(f"  エラー: {e}")
                    continue

            print(f"=== フェーズ1完了: {len(self.pages)}記事 ===")

            # フェーズ2: リンク関係構築
            print("=== フェーズ2: リンク関係構築 ===")
            processed = set()
            for url in list(self.pages.keys()):
                try:
                    response = session.get(url, timeout=10)
                    if response.status_code != 200: continue
                    
                    soup = BeautifulSoup(response.text, 'html.parser')
                    content_links = self.extract_content_links(soup, url)
                    
                    for link_data in content_links:
                        target = link_data['url']
                        if target in self.pages and target != url:
                            link_key = (url, target)
                            if link_key not in processed:
                                processed.add(link_key)
                                self.links.append((url, target))
                                self.pages[url]['outbound_links'].append(target)
                                self.detailed_links.append({
                                    'source_url': url, 'source_title': self.pages[url]['title'],
                                    'target_url': target, 'anchor_text': link_data['anchor_text']
                                })
                except Exception as e:
                    print(f"リンク解析エラー: {e}")
                    continue

            # 被リンク数計算
            for url in self.pages:
                self.pages[url]['inbound_links'] = sum(1 for s, t in self.links if t == url)

            print(f"=== 分析完了: {len(self.pages)}記事, {len(self.links)}リンク ===")
            self.root.after(0, self.show_results)
            
        except Exception as e:
            print(f"分析エラー: {e}")
            self.root.after(0, lambda: messagebox.showerror("エラー", str(e)))
        finally:
            self.root.after(0, lambda: self.analyze_btn.configure(state="normal"))
            
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
            csv_filename = f"answer-genkinka-{date_folder}.csv"
            filename = os.path.join(folder_path, csv_filename)
            
            # 詳細CSVエクスポート実行
            self.export_detailed_to_file(filename)
            
            print(f"=== 自動CSVエクスポート完了: {date_folder}/{csv_filename} ===")
            
        except Exception as e:
            print(f"自動CSVエクスポートエラー: {e}")

    def show_results(self):
        for w in self.result_frame.winfo_children(): w.destroy()
        
        if not self.pages:
            ctk.CTkLabel(self.result_frame, text="データなし").pack()
            return

        total = len(self.pages)
        isolated = sum(1 for p in self.pages.values() if p['inbound_links'] == 0)
        popular = sum(1 for p in self.pages.values() if p['inbound_links'] >= 5)
        
        ctk.CTkLabel(self.result_frame, 
                    text=f"📊 {total}記事 | {len(self.links)}リンク | 孤立{isolated}件 | 人気{popular}件", 
                    font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)

        sorted_pages = sorted(self.pages.items(), key=lambda x: x[1]['inbound_links'], reverse=True)
        
        for i, (url, info) in enumerate(sorted_pages):
            inbound = info['inbound_links']
            outbound = len(info['outbound_links'])
            
            if inbound == 0:
                eval_text = "🚨要改善"
            elif inbound >= 10:
                eval_text = "🏆超人気"
            elif inbound >= 5:
                eval_text = "✅人気"
            else:
                eval_text = "⚠️普通"
                
            text = f"{i+1}. {info['title'][:50]}...\n   被リンク:{inbound} | 発リンク:{outbound} | {eval_text}\n   {url}"
            ctk.CTkLabel(self.result_frame, text=text, anchor="w", font=ctk.CTkFont(size=10)).pack(fill="x", padx=10, pady=1)

    def export_detailed(self):
        if not self.detailed_links: return messagebox.showerror("エラー", "詳細データなし")
        filename = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not filename: return
        
        self.export_detailed_to_file(filename)

    def export_detailed_to_file(self, filename):
        try:
            with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(['番号', 'ページタイトル', 'URL', '被リンク元タイトル', '被リンク元URL', 'アンカーテキスト'])
                
                # ターゲット別にグループ化
                targets = {}
                for link in self.detailed_links:
                    target = link['target_url']
                    targets.setdefault(target, []).append(link)
                
                # 被リンク数でソート
                sorted_targets = sorted(targets.items(), key=lambda x: len(x[1]), reverse=True)
                
                row = 1
                for target, links_list in sorted_targets:
                    title = self.pages.get(target, {}).get('title', target)
                    for link in links_list:
                        writer.writerow([row, title, target, link['source_title'], link['source_url'], link['anchor_text']])
                        row += 1
                
                # 孤立ページも追加
                for url, info in self.pages.items():
                    if info['inbound_links'] == 0:
                        writer.writerow([row, info['title'], url, '', '', ''])
                        row += 1
            
            messagebox.showinfo("完了", "詳細CSV保存完了")
        except Exception as e:
            messagebox.showerror("エラー", f"保存に失敗: {e}")

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    AnswerAnalyzer().run()