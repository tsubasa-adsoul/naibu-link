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

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

class XGiftAnalyzer:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("🔗 xgift.jp専用内部リンク分析ツール（AFFINGER対応）")
        self.root.geometry("1200x800")
        
        self.pages = {}
        self.links = []
        self.detailed_links = []
        
        self.setup_ui()
        
        # 自動分析開始（EXE化対応）
        self.root.after(1000, self.auto_start_analysis)  # 1秒後に自動開始

    def setup_ui(self):
        main_frame = ctk.CTkScrollableFrame(self.root)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # タイトル
        ctk.CTkLabel(main_frame, text="🔗 xgift.jp専用内部リンク分析ツール", 
                    font=ctk.CTkFont(size=28, weight="bold")).pack(pady=10)
        ctk.CTkLabel(main_frame, text="AFFINGER テーマ対応版", 
                    font=ctk.CTkFont(size=16), text_color="gray").pack(pady=5)

        # URL入力
        self.url_entry = ctk.CTkEntry(main_frame, placeholder_text="https://xgift.jp/blog/", width=500)
        self.url_entry.pack(pady=10)
        self.url_entry.insert(0, "https://xgift.jp/blog/")

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

        # エクスポートボタン（詳細のみ）
        ctk.CTkButton(main_frame, text="詳細CSVエクスポート", command=self.export_detailed).pack(pady=10)

    def normalize_url(self, url):
        """URL正規化"""
        if not url: return ""
        try:
            parsed = urlparse(url)
            normalized = f"https://{parsed.netloc.replace('www.', '')}{parsed.path.rstrip('/')}"
            return normalized
        except:
            return url

    def is_article_page(self, url):
        """個別記事ページかどうか判定（AFFINGER対応・デバッグ付き）"""
        path = urlparse(self.normalize_url(url)).path.lower()
        
        print(f"        記事判定: {url}")
        print(f"          パス: {path}")
        
        # 除外：明らかに記事ではないもの
        exclude_patterns = [
            '/site/', '/wp-admin', '/wp-content', '/wp-json', '/feed', '/rss',
            '.', '/page/', '/category/', '/tag/', '/author/', '/search',
            '/privacy', '/terms', '/contact', '/about'
        ]
        for pattern in exclude_patterns:
            if pattern in path:
                print(f"          ✗ 除外パターン: {pattern}")
                return False
        
        # xgift.jp の構造を柔軟に判定
        
        # パターン1: /blog/記事スラッグ/ の形式（AFFINGER典型パターン）
        if path.startswith('/blog/') and path != '/blog':
            article_path = path[6:]  # '/blog/' を除去
            if article_path and '/' not in article_path.rstrip('/'):
                clean_path = article_path.rstrip('/')
                if clean_path and len(clean_path) > 2:  # 短すぎるスラッグは除外
                    print(f"          ✓ パターン1: /blog/記事スラッグ/")
                    return True
        
        # パターン2: ルート直下の記事スラッグ（他サイトと同様）
        if (path.startswith('/') and len(path) > 1 and 
            '/' not in path[1:].rstrip('/') and
            not path.startswith('/blog')):
            clean_path = path[1:].rstrip('/')
            if clean_path and len(clean_path) > 3:  # 短すぎるスラッグは除外
                # 英数字・ハイフン・アンダースコアのみ許可
                if all(c.isalnum() or c in '-_' for c in clean_path):
                    print(f"          ✓ パターン2: ルート直下記事")
                    return True
        
        print(f"          ✗ 記事ページではない")
        return False

    def is_crawlable(self, url):
        """クロール対象かどうか判定（AFFINGER最適化）"""
        path = urlparse(self.normalize_url(url)).path.lower()
        
        # 除外：明らかに不要なもの
        exclude_words = ['/site/', '/wp-admin', '/wp-content', '/wp-json', '/feed', '/rss',
                        '.jpg', '.png', '.css', '.js', '.pdf', '.zip', '.svg', '.ico']
        if any(word in path for word in exclude_words):
            return False
        
        # 許可：ブログ関連 + 記事ページ + ルートページ
        return (path.startswith('/blog') or self.is_article_page(url) or path in ['/', ''])

    def extract_links(self, soup, current_url):
        """リンク抽出（AFFINGER最適化・デバッグ強化版）"""
        all_links = soup.find_all('a', href=True)
        print(f"    全aタグ数: {len(all_links)}")
        
        links = []
        crawlable_count = 0
        article_count = 0
        
        for a in all_links:
            href = a.get('href', '').strip()
            if href and not href.startswith('#'):
                absolute = urljoin(current_url, href)
                if 'xgift.jp' in absolute:
                    is_crawl = self.is_crawlable(absolute)
                    is_article = self.is_article_page(absolute)
                    
                    if is_crawl:
                        crawlable_count += 1
                        links.append(self.normalize_url(absolute))
                    if is_article:
                        article_count += 1
                    
                    # 詳細デバッグは最初の10リンクのみ表示
                    if len([l for l in [is_crawl, is_article] if l]) > 0 and article_count <= 10:
                        print(f"      リンク: {href}")
                        print(f"        絶対URL: {absolute}")
                        print(f"        クロール可能: {is_crawl}")
                        print(f"        記事ページ: {is_article}")
        
        print(f"    結果: 全{len(all_links)}→クロール可能{crawlable_count}→記事{article_count}→採用{len(set(links))}")
        return list(set(links))

    def extract_content_links(self, soup, current_url):
        """コンテンツエリアからリンク抽出（AFFINGER最適化）"""
        # AFFINGER特有のセレクタを優先
        content_selectors = [
            '.entry-content',       # AFFINGER標準
            '.post-content',        # 投稿コンテンツ
            '.main-content',        # メインコンテンツ
            'main',                 # HTML5セマンティック
            'article',              # 記事要素
            '.content',             # 汎用コンテンツ
            '.single-content',      # 単一記事コンテンツ
            '[class*="content"]'    # コンテンツ系クラス
        ]
        
        content = None
        for selector in content_selectors:
            content = soup.select_one(selector)
            if content:
                print(f"        コンテンツエリア検出: {selector}")
                break
        
        if not content:
            # フォールバック：body全体（ただし除外エリアを削除）
            content = soup.find('body')
            if content:
                # AFFINGER特有の除外エリア
                for remove_sel in ['nav', 'header', 'footer', '.navigation', '.menu', 
                                 '.sidebar', '.widget', '.ads', '.related', '.author-info']:
                    for elem in content.select(remove_sel):
                        elem.decompose()
                print(f"        フォールバック: body使用（除外エリア削除済み）")
        
        if not content:
            return []

        links = []
        for a in content.find_all('a', href=True):
            href = a.get('href', '').strip()
            text = a.get_text(strip=True) or ''
            if href and not href.startswith('#') and text:
                absolute = urljoin(current_url, href)
                if 'xgift.jp' in absolute and self.is_article_page(absolute):
                    links.append({
                        'url': self.normalize_url(absolute), 
                        'anchor_text': text[:100]
                    })
        return links

    def auto_start_analysis(self):
        """EXE化対応：自動で分析開始"""
        print("=== 自動分析開始 ===")
        self.status_label.configure(text="自動分析を開始します...")
        self.start_analysis()

    def start_analysis(self):
        self.analyze_btn.configure(state="disabled")
        threading.Thread(target=self.analyze, daemon=True).start()

    def analyze(self):
        try:
            self.pages, self.links, self.detailed_links = {}, [], []
            visited, to_visit = set(), [self.normalize_url(self.url_entry.get())]
            
            # AFFINGER対応の追加URL
            additional_urls = [
                'https://xgift.jp/blog/page/2/',
                'https://xgift.jp/blog/page/3/',
                'https://xgift.jp/blog/category/',
                'https://xgift.jp/',  # ルートページも確認
            ]
            to_visit.extend(additional_urls)

            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })

            print("=== xgift.jp (AFFINGER) 分析開始 ===")

            # フェーズ1: ページ収集
            max_pages = 600  # AFTINGERサイトは記事数が多い可能性
            while to_visit and len(self.pages) < max_pages:
                url = to_visit.pop(0)
                if url in visited: continue
                
                try:
                    print(f"処理中: {url}")
                    response = session.get(url, timeout=15)
                    if response.status_code != 200: 
                        print(f"  HTTPエラー: {response.status_code}")
                        continue
                    
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    # NOINDEXチェック
                    robots = soup.find('meta', attrs={'name': 'robots'})
                    if robots and 'noindex' in robots.get('content', '').lower():
                        print(f"  NOINDEXをスキップ")
                        continue
                    
                    # ブログ一覧ページ・ページネーションは収集のみ
                    if (('/blog' in url and not self.is_article_page(url)) or 
                        '/page/' in url or '/category/' in url):
                        page_links = self.extract_links(soup, url)
                        new_links = [l for l in page_links if l not in visited and l not in to_visit]
                        to_visit.extend(new_links)
                        visited.add(url)
                        print(f"  一覧ページ: {len(new_links)}件の新規リンク")
                        continue
                    
                    # 個別記事ページを保存
                    if self.is_article_page(url):
                        # AFFINGER対応のタイトル抽出
                        title = None
                        for selector in ['h1.entry-title', 'h1', '.post-title', '.entry-title']:
                            title_elem = soup.select_one(selector)
                            if title_elem:
                                title = title_elem.get_text(strip=True)
                                break
                        
                        if not title:
                            title = soup.title.get_text(strip=True) if soup.title else url
                        
                        # サイト名除去（XGIFT用）
                        title = re.sub(r'\s*[|\-]\s*.*(xgift|XGIFT|エックスギフト).*$', '', title, flags=re.IGNORECASE)
                        title = title.strip()
                        
                        self.pages[url] = {'title': title, 'outbound_links': []}
                        
                        # 新しいリンクを発見
                        page_links = self.extract_links(soup, url)
                        new_links = [l for l in page_links if l not in visited and l not in to_visit]
                        to_visit.extend(new_links)
                        
                        print(f"  記事: {title}")
                        print(f"  新規: {len(new_links)}件")
                    
                    visited.add(url)
                    
                    self.root.after(0, lambda: self.status_label.configure(text=f"収集中: {len(self.pages)}記事"))
                    self.root.after(0, lambda: self.progress.set(len(self.pages) / max_pages))
                    time.sleep(0.2)  # レート制限
                    
                except Exception as e:
                    print(f"  エラー: {e}")
                    continue

            print(f"=== フェーズ1完了: {len(self.pages)}記事 ===")

            # フェーズ2: リンク関係構築
            print("=== フェーズ2: リンク関係構築 ===")
            processed = set()
            
            for i, url in enumerate(list(self.pages.keys())):
                try:
                    if i % 25 == 0:
                        print(f"リンク解析進捗: {i}/{len(self.pages)}")
                        self.root.after(0, lambda: self.status_label.configure(text=f"リンク解析中: {i}/{len(self.pages)}"))
                    
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
            
            # 全自動化：分析完了後に自動CSVエクスポート
            if self.pages:  # データがある場合のみ
                self.root.after(2000, self.auto_export_csv)  # 2秒後に自動エクスポート
            
        except Exception as e:
            print(f"分析エラー: {e}")
            self.root.after(0, lambda: messagebox.showerror("エラー", str(e)))
        finally:
            self.root.after(0, lambda: self.analyze_btn.configure(state="normal"))

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

    def export_csv(self):
        if not self.pages: return messagebox.showerror("エラー", "データなし")
        filename = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not filename: return
        
        with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['順位', 'タイトル', 'URL', '被リンク数', '発リンク数', '評価'])
            
            sorted_pages = sorted(self.pages.items(), key=lambda x: x[1]['inbound_links'], reverse=True)
            
            for i, (url, info) in enumerate(sorted_pages, 1):
                inbound = info['inbound_links']
                
                if inbound == 0:
                    evaluation = "要改善"
                elif inbound >= 10:
                    evaluation = "超人気"
                elif inbound >= 5:
                    evaluation = "人気"
                else:
                    evaluation = "普通"
                
                writer.writerow([i, info['title'], url, inbound, len(info['outbound_links']), evaluation])
        
        messagebox.showinfo("完了", "CSV保存完了")

    def auto_export_csv(self):
        """全自動化：自動CSVエクスポート（EXE化対応）"""
        import os
        from datetime import datetime
        
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
            csv_filename = f"xgift-{date_folder}.csv"
            filename = os.path.join(folder_path, csv_filename)
            
            if not self.detailed_links:
                print("詳細データなし - CSVエクスポートをスキップ")
                return
            
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
            
            print(f"=== 自動CSVエクスポート完了: {filename} ===")
            self.status_label.configure(text=f"分析完了！CSVファイル保存: {os.path.basename(filename)}")
            
        except Exception as e:
            print(f"自動CSVエクスポートエラー: {e}")
            self.status_label.configure(text="分析完了（CSV保存エラー）")

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

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    XGiftAnalyzer().run()