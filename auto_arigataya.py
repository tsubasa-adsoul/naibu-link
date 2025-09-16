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
import os
import sys

# --- Analyzer Class (ロジック部分はほぼそのまま使用) ---
class ArigatayaAnalyzer:
    def __init__(self, base_url):
        self.base_url = base_url
        self.pages = {}
        self.links = []
        self.detailed_links = []
        self.domain = urlparse(base_url).netloc.replace('www.', '')

    def normalize_url(self, url):
        parsed = urlparse(url)
        scheme = 'https'
        netloc = parsed.netloc.replace('www.', '')
        path = parsed.path.rstrip('/')

        if '/wp/' in path:
            path = path.replace('/wp/', '/')

        path = re.sub(r'/+', '/', path)

        if path and not path.endswith('/'):
            path += '/'

        return f"{scheme}://{netloc}{path}"

    def is_internal(self, url):
        return urlparse(url).netloc.replace('www.', '') == self.domain

    def extract_from_sitemap(self, url, visited_sitemaps):
        if url in visited_sitemaps:
            return set()
        visited_sitemaps.add(url)
        
        urls = set()
        try:
            res = requests.get(url, timeout=10)
            res.raise_for_status()
            soup = BeautifulSoup(res.content, 'xml')
            
            if soup.find('sitemapindex'):
                for loc in soup.find_all('loc'):
                    urls.update(self.extract_from_sitemap(loc.text.strip(), visited_sitemaps))
            else:
                for loc in soup.find_all('loc'):
                    loc_url = loc.text.strip()
                    if not re.search(r'sitemap.*\.(xml|html)$', loc_url.lower()):
                        urls.add(self.normalize_url(loc_url))
        except Exception as e:
            print(f"Sitemap Error at {url}: {e}")
            pass
        return urls

    def generate_seed_urls(self):
        sitemap_root = urljoin(self.base_url, '/sitemap.xml')
        sitemap_urls = self.extract_from_sitemap(sitemap_root, set())
        print(f"サイトマップから {len(sitemap_urls)} 個のURLを取得")
        return list(set([self.normalize_url(self.base_url)] + list(sitemap_urls)))

    def is_content(self, url):
        normalized_url = self.normalize_url(url)
        path = urlparse(normalized_url).path.lower().split('?')[0].rstrip('/')
        
        if any(re.search(pattern, path) for pattern in [
            r'^/category/[a-z0-9\-]+/?$',
            r'^/category/[a-z0-9\-]+/page/\d+/?$',
            r'^/[a-z0-9\-]+/?$',
            r'^/?$'
        ]):
            return True
        
        if any(re.search(e, path) for e in [
            r'/sitemap', r'sitemap.*\.(xml|html)$', r'/page/\d+/?$', r'-mg',
            r'/site/', r'/wp-', r'/tag/', r'/wp-content', r'/wp-admin', r'/wp-json',
            r'#', r'\?utm_', r'/feed/', r'mailto:', r'tel:', r'/privacy', r'/terms',
            r'/contact', r'/go-', r'/redirect', r'/exit', r'/out',
            r'\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|rar|doc|docx|xls|xlsx)$'
        ]):
            return False
        
        return True

    def is_noindex_page(self, soup):
        try:
            meta_robots = soup.find('meta', attrs={'name': 'robots'})
            if meta_robots and meta_robots.get('content') and 'noindex' in meta_robots.get('content').lower():
                return True
            
            noindex_meta = soup.find('meta', attrs={'name': 'googlebot', 'content': lambda x: x and 'noindex' in x.lower()})
            if noindex_meta:
                return True
                
            title = soup.find('title')
            if title and title.get_text():
                title_text = title.get_text().lower()
                if any(keyword in title_text for keyword in ['外部サイト', 'リダイレクト', '移動中', '外部リンク', 'cushion']):
                    return True
            
            body_text = soup.get_text().lower()
            if any(phrase in body_text for phrase in [
                '外部サイトに移動します', 'リダイレクトしています', '外部リンクです',
                '別サイトに移動', 'このリンクは外部サイト'
            ]):
                return True
                
            return False
        except Exception as e:
            print(f"NOINDEXチェック中にエラー: {e}")
            return False

    def extract_links(self, soup):
        selectors = [
            '.post_content', '.entry-content', '.article-content', 'main .content',
            '[class*="content"]', 'main', 'article'
        ]
        
        for selector in selectors:
            areas = soup.select(selector)
            if areas:
                links = []
                for area in areas:
                    for exclude in area.select('header, footer, nav, aside, .sidebar, .widget, .share, .related, .popular-posts, .breadcrumb, .author-box, .navigation'):
                        exclude.decompose()
                    
                    found_links = area.find_all('a', href=True)
                    for link in found_links:
                        anchor_text = link.get_text(strip=True) or link.get('title', '') or '[リンク]'
                        links.append({'url': link['href'], 'anchor_text': anchor_text[:100]})
                    
                    onclick_elements = area.find_all(attrs={'onclick': True})
                    for element in onclick_elements:
                        onclick_attr = element.get('onclick', '')
                        url_match = re.search(r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]", onclick_attr)
                        if url_match:
                            extracted_url = url_match.group(1)
                            anchor_text = element.get_text(strip=True) or element.get('title', '') or '[onclick リンク]'
                            links.append({'url': extracted_url, 'anchor_text': anchor_text[:100]})
                if links:
                    return links
        
        return []

    def analyze(self, progress_callback):
        self.pages, self.links, self.detailed_links = {}, [], []
        
        progress_callback("サイトマップからURLを収集中...", 0.0)
        to_visit_raw = self.generate_seed_urls()
        
        to_visit = []
        seen = set()
        for url in to_visit_raw:
            normalized = self.normalize_url(url)
            if normalized not in seen:
                seen.add(normalized)
                to_visit.append(normalized)

        visited = set()
        processed_links = set()
        
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})

        max_pages = 500
        total_urls_to_process = len(to_visit)
        
        while to_visit and len(self.pages) < max_pages:
            url = to_visit.pop(0)
            if url in visited:
                continue

            try:
                progress = len(self.pages) / max_pages
                progress_callback(f"分析中 ({len(self.pages)}/{max_pages}): {url}", progress)
                
                response = session.get(url, timeout=10)
                if response.status_code != 200:
                    continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                if self.is_noindex_page(soup):
                    visited.add(url)
                    continue

                title = soup.title.string.strip() if soup.title and soup.title.string else url
                title = re.sub(r'\s*[|\-]\s*.*(arigataya|ありがたや).*$', '', title, flags=re.IGNORECASE)
                
                self.pages[url] = {'title': title, 'outbound_links': []}

                extracted_links = self.extract_links(soup)
                for link_data in extracted_links:
                    link_url = urljoin(url, link_data['url'])
                    anchor_text = link_data['anchor_text']
                    normalized_link = self.normalize_url(link_url)
                    
                    if self.is_internal(normalized_link) and self.is_content(normalized_link):
                        link_key = (url, normalized_link)
                        if link_key not in processed_links:
                            processed_links.add(link_key)
                            self.links.append((url, normalized_link))
                            self.pages[url]['outbound_links'].append(normalized_link)
                            self.detailed_links.append({
                                'source_url': url, 'source_title': title,
                                'target_url': normalized_link, 'anchor_text': anchor_text
                            })
                        
                        if normalized_link not in visited and normalized_link not in to_visit:
                            to_visit.append(normalized_link)

                visited.add(url)
                time.sleep(0.1)

            except Exception as e:
                print(f"Error processing {url}: {e}")
                continue

        progress_callback("被リンク数を計算中...", 0.95)
        for url in self.pages:
            self.pages[url]['inbound_links'] = sum(1 for _, tgt in self.links if tgt == url)
        
        progress_callback("分析完了！", 1.0)
        return self.pages, self.links, self.detailed_links

# --- Streamlit App ---
def create_detailed_csv(pages, detailed_links):
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow([
        'A_番号', 'B_ページタイトル', 'C_URL',
        'D_被リンク元ページタイトル', 'E_被リンク元ページURL', 'F_被リンク元ページアンカーテキスト'
    ])
    
    unique_pages = sorted(
        [{'url': u, 'title': i.get('title', u), 'inbound_links': i.get('inbound_links', 0)} for u, i in pages.items()],
        key=lambda x: x['inbound_links'],
        reverse=True
    )
    
    page_number_map = {page['url']: i for i, page in enumerate(unique_pages, 1)}

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
    st.markdown("**onclick対応・全自動版 (Streamlit)**")

    if 'analysis_done' not in st.session_state:
        st.session_state.analysis_done = False
        st.session_state.results = None

    # 自動分析開始のトリガー
    if not st.session_state.analysis_done:
        
        start_button = st.button("🚀 分析開始", type="primary", use_container_width=True)
        
        if start_button:
            st.session_state.analysis_started = True

        if 'analysis_started' in st.session_state and st.session_state.analysis_started:
            
            status_placeholder = st.empty()
            progress_bar = st.progress(0)
            
            def progress_callback(message, progress):
                status_placeholder.info(message)
                progress_bar.progress(progress)

            try:
                analyzer = ArigatayaAnalyzer("https://arigataya.co.jp")
                pages, links, detailed_links = analyzer.analyze(progress_callback)
                
                st.session_state.results = {
                    "pages": pages,
                    "links": links,
                    "detailed_links": detailed_links
                }
                st.session_state.analysis_done = True
                st.session_state.analysis_started = False # リセット
                st.rerun() # 結果表示のために再実行

            except Exception as e:
                st.error(f"分析中にエラーが発生しました: {e}")
                st.session_state.analysis_started = False # リセット

    # 分析完了後の結果表示
    if st.session_state.analysis_done and st.session_state.results:
        results = st.session_state.results
        pages = results["pages"]
        links = results["links"]
        detailed_links = results["detailed_links"]
        
        st.success("✅ 分析が完了しました！")

        # --- 統計情報 ---
        total_pages = len(pages)
        total_links_count = len(links)
        isolated_pages = sum(1 for p in pages.values() if p.get('inbound_links', 0) == 0)
        popular_pages = sum(1 for p in pages.values() if p.get('inbound_links', 0) >= 5)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("総ページ数", total_pages)
        col2.metric("総リンク数", total_links_count)
        col3.metric("孤立ページ", isolated_pages)
        col4.metric("人気ページ", popular_pages)

        # --- CSVダウンロード ---
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

        # --- 結果データフレーム ---
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
