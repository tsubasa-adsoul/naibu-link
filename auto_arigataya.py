import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import re
import csv
import io
from datetime import datetime
import pandas as pd

# --- Analyzer Class (改善版) ---
class ArigatayaAnalyzer:
    def __init__(self, base_url):
        self.base_url = base_url
        self.pages = {}
        self.links = []
        self.detailed_links = []
        self.domain = urlparse(base_url).netloc.replace('www.', '')

    def normalize_url(self, url):
        """URLを正規化する。クエリパラメータとフラグメントを除去し、末尾のスラッシュを統一する。"""
        try:
            parsed = urlparse(url)
            # クエリパラメータとフラグメントを除去
            path = parsed.path.split('?')[0].split('#')[0]
            # www. を除去し、末尾のスラッシュを削除
            netloc = parsed.netloc.replace('www.', '')
            path = path.rstrip('/')
            
            # トップページの場合は空パスにする
            if not path:
                return f"https://{netloc}"
            
            return f"https://{netloc}{path}"
        except Exception:
            return url

    def is_internal(self, url):
        """URLが内部ドメインかどうかを判定する。"""
        return urlparse(url).netloc.replace('www.', '') == self.domain

    def extract_from_sitemap(self, url, visited_sitemaps):
        """サイトマップを再帰的に探索してURLを抽出する。"""
        if url in visited_sitemaps:
            return set()
        visited_sitemaps.add(url)
        
        urls = set()
        try:
            res = requests.get(url, timeout=10)
            res.raise_for_status()
            # XMLとしてパース
            soup = BeautifulSoup(res.content, 'xml')
            
            # sitemapindexの場合、再帰的に探索
            if soup.find('sitemapindex'):
                for loc in soup.find_all('loc'):
                    urls.update(self.extract_from_sitemap(loc.text.strip(), visited_sitemaps))
            # 通常のsitemapの場合、URLを抽出
            else:
                for loc in soup.find_all('loc'):
                    urls.add(self.normalize_url(loc.text.strip()))
        except Exception as e:
            print(f"サイトマップエラー ({url}): {e}")
        return urls

    def generate_seed_urls(self):
        """分析の起点となるURLリストをサイトマップから生成する。"""
        sitemap_root = urljoin(self.base_url, '/sitemap.xml')
        sitemap_urls = self.extract_from_sitemap(sitemap_root, set())
        print(f"サイトマップから {len(sitemap_urls)} 個のURLを取得しました。")
        # 基本URLも追加しておく
        seed_urls = set([self.normalize_url(self.base_url)]) | sitemap_urls
        return list(seed_urls)

    def is_content(self, url):
        """URLがクロール対象のコンテンツページかどうかを判定する（改善版）。"""
        try:
            path = urlparse(url).path.lower()

            # 除外すべき明確なパターン
            exclude_patterns = [
                r'\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip)$', # 画像やファイル
                r'/wp-admin', r'/wp-json', r'/wp-includes', r'/wp-content/plugins', # WordPressシステム系
                r'/feed', r'/comments/feed', # フィード
                r'/trackback',
                r'sitemap\.xml', # サイトマップ自体
                r'\/go\/', # リダイレクト用ディレクトリ
                r'\/g\/', # リダイレクト用ディレクトリ
                r'\/tag\/', # タグページ
                r'\/author\/', # 著者ページ
                r'\/privacy', # プライバシーポリシー
            ]
            for pattern in exclude_patterns:
                if re.search(pattern, path):
                    # print(f"[除外] パターンに一致: {url}")
                    return False

            # ページネーション（/page/数字）は、カテゴリページ以外では除外する傾向が強いが、今回は一旦含める
            # if re.search(r'/page/\d+', path) and not path.startswith('/category/'):
            #     return False

            # パスが「/」で終わり、かつパス階層が深すぎないものを記事とみなす（例: /g-card/）
            # arigataya.co.jp は記事URLが /slug/ の形式なので、スラッシュで終わる単一階層を優先
            # 正規化で末尾スラッシュは除去済みなので、パスの構造で判断
            clean_path = path.strip('/')
            if '/' not in clean_path and clean_path: # /slug のような形式
                 return True
            
            # トップページ
            if path == '/' or not path:
                return True
            
            # カテゴリページ
            if path.startswith('/category/'):
                return True

            # 上記の条件に合致しないものは一旦除外
            # print(f"[除外] 対象外の構造: {url}")
            return False
        except Exception:
            return False

    def is_noindex_page(self, soup):
        """ページがnoindexかどうかを判定する。"""
        meta_robots = soup.find('meta', attrs={'name': 'robots'})
        if meta_robots and 'noindex' in meta_robots.get('content', '').lower():
            return True
        return False

    def extract_links(self, soup, base_url):
        """ページ内から内部リンクを抽出する（onclick対応）。"""
        links = []
        content_area = soup.select_one('.post_content, .entry-content, main, article')
        if not content_area:
            content_area = soup # 見つからない場合は全体を対象

        # 通常のaタグ
        for a in content_area.find_all('a', href=True):
            href = a.get('href')
            if href and not href.startswith(('#', 'javascript:', 'mailto:')):
                full_url = urljoin(base_url, href)
                if self.is_internal(full_url):
                    links.append({
                        'url': self.normalize_url(full_url),
                        'anchor_text': a.get_text(strip=True)[:100]
                    })
        
        # onclick属性
        for tag in content_area.find_all(onclick=True):
            onclick_val = tag.get('onclick')
            match = re.search(r"location\.href='([^']+)'", onclick_val)
            if match:
                href = match.group(1)
                full_url = urljoin(base_url, href)
                if self.is_internal(full_url):
                    links.append({
                        'url': self.normalize_url(full_url),
                        'anchor_text': tag.get_text(strip=True)[:100]
                    })
        return links

    def analyze(self, progress_callback):
        """サイト分析を実行するメインロジック。"""
        self.pages, self.links, self.detailed_links = {}, [], []
        
        progress_callback("サイトマップからURLを収集中...", 0.0)
        to_visit = self.generate_seed_urls()
        
        visited = set()
        processed_links = set() # (source, target) のタプルを保存
        
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'})

        max_pages = 500 # クロール上限
        queue = list(dict.fromkeys(to_visit)) # 重複除去しつつ順序維持
        
        while queue and len(self.pages) < max_pages:
            url = queue.pop(0)
            
            if url in visited:
                continue
            
            # クロール対象のコンテンツか事前にチェック
            if not self.is_content(url):
                visited.add(url)
                continue

            try:
                progress = len(self.pages) / max_pages
                progress_callback(f"分析中 ({len(self.pages)}/{max_pages}): {url}", progress)
                
                response = session.get(url, timeout=10)
                visited.add(url) # 訪問済みとしてマーク
                if response.status_code != 200:
                    continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                if self.is_noindex_page(soup):
                    print(f"[スキップ] NOINDEXページ: {url}")
                    continue

                title = soup.title.string.strip() if soup.title and soup.title.string else url
                title = re.sub(r'\s*[|\-]\s*.*(arigataya|ありがたや).*$', '', title, flags=re.IGNORECASE).strip()
                
                # この時点でページを登録
                if url not in self.pages:
                    self.pages[url] = {'title': title, 'outbound_links': [], 'inbound_links': 0}

                # ページ内からリンクを抽出
                extracted_links = self.extract_links(soup, url)
                for link_data in extracted_links:
                    target_url = link_data['url']
                    
                    # リンクがクロール対象かチェック
                    if self.is_content(target_url):
                        # 発リンクとして記録
                        link_key = (url, target_url)
                        if link_key not in processed_links:
                            self.pages[url]['outbound_links'].append(target_url)
                            self.detailed_links.append({
                                'source_url': url, 'source_title': title,
                                'target_url': target_url, 'anchor_text': link_data['anchor_text']
                            })
                            processed_links.add(link_key)
                        
                        # 未訪問ならキューに追加
                        if target_url not in visited and target_url not in queue:
                            queue.append(target_url)

                time.sleep(0.1)

            except requests.exceptions.RequestException as e:
                print(f"通信エラー ({url}): {e}")
                continue
            except Exception as e:
                print(f"処理エラー ({url}): {e}")
                continue

        progress_callback("被リンク数を計算中...", 0.95)
        # 被リンク数を再計算
        for page_url in self.pages:
            self.pages[page_url]['inbound_links'] = 0
        for link in self.detailed_links:
            target = link['target_url']
            if target in self.pages:
                self.pages[target]['inbound_links'] += 1
        
        progress_callback("分析完了！", 1.0)
        return self.pages, self.detailed_links

# --- Streamlit App (UI部分は変更なし) ---
def create_detailed_csv(pages, detailed_links):
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow([
        'A_番号', 'B_ページタイトル', 'C_URL',
        'D_被リンク元ページタイトル', 'E_被リンク元ページURL', 'F_被リンク元ページアンカーテキスト'
    ])
    
    # 被リンク数でソートされたユニークなページのリストを作成
    unique_pages = sorted(
        [{'url': u, 'title': i.get('title', u), 'inbound_links': i.get('inbound_links', 0)} for u, i in pages.items()],
        key=lambda x: x['inbound_links'],
        reverse=True
    )
    
    # URLとページ番号のマッピングを作成
    page_number_map = {page['url']: i for i, page in enumerate(unique_pages, 1)}

    # 被リンクを持つページの情報を書き出し
    for link in detailed_links:
        target_url = link.get('target_url')
        if not target_url or target_url not in page_number_map:
            continue
        
        page_number = page_number_map[target_url]
        target_title = pages.get(target_url, {}).get('title', target_url)
        
        writer.writerow([
            page_number, target_title, target_url,
            link.get('source_title', ''), link.get('source_url', ''), link.get('anchor_text', '')
        ])

    # 孤立ページ（被リンク0）の情報を書き出し
    for url, info in pages.items():
        if info.get('inbound_links', 0) == 0:
            page_number = page_number_map.get(url)
            if page_number:
                writer.writerow([page_number, info.get('title', url), url, '', '', ''])
                
    return output.getvalue().encode('utf-8-sig')

def main():
    st.set_page_config(
        page_title="arigataya専用内部リンク分析",
        page_icon="🔗",
        layout="wide"
    )
    
    st.title("🔗 arigataya専用内部リンク分析ツール")
    st.markdown("**onclick対応・全自動版 (Streamlit) - 改善版**")

    if 'analysis_done' not in st.session_state:
        st.session_state.analysis_done = False
        st.session_state.results = None

    if not st.session_state.analysis_done:
        start_button = st.button("🚀 分析開始", type="primary", use_container_width=True)
        
        if start_button and 'analysis_started' not in st.session_state:
            st.session_state.analysis_started = True

        if 'analysis_started' in st.session_state and st.session_state.analysis_started:
            status_placeholder = st.empty()
            progress_bar = st.progress(0)
            
            def progress_callback(message, progress):
                status_placeholder.info(message)
                progress_bar.progress(progress)

            try:
                analyzer = ArigatayaAnalyzer("https://arigataya.co.jp")
                pages, detailed_links = analyzer.analyze(progress_callback)
                
                st.session_state.results = {
                    "pages": pages,
                    "detailed_links": detailed_links
                }
                st.session_state.analysis_done = True
                del st.session_state.analysis_started # 完了したら削除
                st.rerun()

            except Exception as e:
                st.error(f"分析中にエラーが発生しました: {e}")
                del st.session_state.analysis_started

    if st.session_state.analysis_done and st.session_state.results:
        results = st.session_state.results
        pages = results["pages"]
        detailed_links = results["detailed_links"]
        
        st.success("✅ 分析が完了しました！")

        total_pages = len(pages)
        total_links_count = len(detailed_links)
        isolated_pages = sum(1 for p in pages.values() if p.get('inbound_links', 0) == 0)
        popular_pages = sum(1 for p in pages.values() if p.get('inbound_links', 0) >= 5)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("総ページ数", total_pages)
        col2.metric("総リンク数", total_links_count)
        col3.metric("孤立ページ", isolated_pages)
        col4.metric("人気ページ", popular_pages)

        csv_data = create_detailed_csv(pages, detailed_links)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"arigataya_{timestamp}.csv"
        
        st.download_button(
            label="📥 詳細CSVをダウンロード",
            data=csv_data,
            file_name=filename,
            mime="text/csv",
            type="primary",
            use_container_width=True
        )

        st.subheader("📊 分析結果一覧")
        results_data = []
        for url, info in pages.items():
            results_data.append({
                'タイトル': info.get('title', url),
                'URL': url,
                '被リンク数': info.get('inbound_links', 0),
                '発リンク数': len(info.get('outbound_links', []))
            })
        
        df = pd.DataFrame(results_data)
        df_sorted = df.sort_values('被リンク数', ascending=False).reset_index(drop=True)
        
        st.dataframe(df_sorted, use_container_width=True)

        if st.button("🔄 再分析する"):
            st.session_state.analysis_done = False
            st.session_state.results = None
            if 'analysis_started' in st.session_state:
                del st.session_state.analysis_started
            st.rerun()

if __name__ == "__main__":
    main()
