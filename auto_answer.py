# auto_answer.py （クラウド完全対応・分割実行型）

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import re
import csv
from io import StringIO

# ★★★ このファイルが呼び出されたときに実行される本体です ★★★
# main.pyから現在の分析状態(state)を受け取り、次のステップの処理を行い、新しい状態を返します。
def analyze_step(state):
    
    # --- 内部で使う関数群（主のロジックをそのまま使用） ---
    # これらは一切変更いたしません。
    
    def log(message):
        # ログの先頭に時間を追加し、ログリストが長くなりすぎないように調整
        state['log'].append(f"[{time.strftime('%H:%M:%S')}] {message}")
        if len(state['log']) > 50:
            state['log'] = state['log'][-50:]

    def normalize_url(url):
        if not url: return ""
        try:
            parsed = urlparse(url)
            return f"https://{parsed.netloc.replace('www.', '')}{parsed.path.rstrip('/')}"
        except: return url

    def is_article_page(url):
        path = urlparse(normalize_url(url)).path.lower()
        exclude_words = ['/site/', '/blog/', '/page/', '/feed', '/wp-', '.']
        if any(word in path for word in exclude_words): return False
        if path.startswith('/') and len(path) > 1:
            clean_path = path[1:].rstrip('/')
            if clean_path and '/' not in clean_path: return True
        return False

    def is_crawlable_page(url):
        path = urlparse(normalize_url(url)).path.lower()
        exclude_words = ['/site/', '/wp-admin', '/feed', '.jpg', '.png', '.css', '.js']
        if any(word in path for word in exclude_words): return False
        return (path.startswith('/blog') or is_article_page(url))

    def extract_links_for_crawling(soup, current_url):
        links_set = set()
        for a in soup.find_all('a', href=True):
            href = a.get('href', '').strip()
            if href and not href.startswith('#'):
                absolute = urljoin(current_url, href)
                if 'answer-genkinka.jp' in absolute and is_crawlable_page(absolute):
                    links_set.add(normalize_url(absolute))
        return list(links_set)

    def extract_content_links(soup, current_url):
        content = soup.select_one('.entry-content, .post-content, main, article')
        if not content: return []
        links = []
        for a in content.find_all('a', href=True):
            href = a.get('href', '').strip()
            text = a.get_text(strip=True) or ''
            if href and not href.startswith('#') and text and '/site/' not in href:
                absolute = urljoin(current_url, href)
                if 'answer-genkinka.jp' in absolute and is_article_page(absolute):
                    links.append({'url': normalize_url(absolute), 'anchor_text': text[:100]})
        return links

    # --- フェーズ管理 ---
    
    # フェーズ1：初期化
    if state['phase'] == 'initializing':
        log("フェーズ1: ページ収集中...")
        try:
            start_url = "https://answer-genkinka.jp/blog/"
            to_visit = [normalize_url(start_url), 'https://answer-genkinka.jp/blog/page/2/']
            
            state['to_visit'] = list(set(to_visit))
            state['visited'] = set()
            state['session'] = requests.Session()
            state['session'].headers.update({'User-Agent': 'Mozilla/5.0'})
            state['phase'] = 'crawling_pages'
            state['crawl_limit'] = 100 # クロール上限
            log(f"シードURLを{len(to_visit)}件設定。ページ収集を開始します。")
        except Exception as e:
            log(f"初期化エラー: {e}")
            state['phase'] = 'error'
        return state

    # フェーズ2：記事ページのURLを収集
    if state['phase'] == 'crawling_pages':
        crawl_batch_size = 5 # 一度に5ページ処理
        session = state['session']
        
        crawled_in_this_step = 0
        while state['to_visit'] and len(state['pages']) < state['crawl_limit'] and crawled_in_this_step < crawl_batch_size:
            url = state['to_visit'].pop(0)
            if url in state['visited']: continue

            try:
                log(f"収集中: {url}")
                response = session.get(url, timeout=20)
                state['visited'].add(url)
                if response.status_code != 200: continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                robots = soup.find('meta', attrs={'name': 'robots'})
                if robots and 'noindex' in robots.get('content', '').lower(): continue
                
                if '/blog' in url: # 記事一覧ページの場合
                    page_links = extract_links_for_crawling(soup, url)
                    new_links = [l for l in page_links if l not in state['visited'] and l not in state['to_visit']]
                    state['to_visit'].extend(new_links)
                
                if is_article_page(url):
                    title = (soup.find('h1') or soup.find('title')).get_text(strip=True) if (soup.find('h1') or soup.find('title')) else url
                    title = re.sub(r'\s*[|\-]\s*.*(answer-genkinka|アンサー).*$', '', title, flags=re.IGNORECASE).strip()
                    state['pages'][url] = {'title': title, 'outbound_links': []}
                
                crawled_in_this_step += 1
                time.sleep(0.3)
            except Exception as e:
                log(f"収集エラー: {url} - {e}")
                continue
        
        # プログレスバー更新
        progress = len(state['pages']) / state['crawl_limit'] if state['crawl_limit'] > 0 else 0
        state['progress'] = progress * 0.5 # 全体の50%
        state['progress_text'] = f"ページ収集: {len(state['pages'])} / {state['crawl_limit']}"
        
        if not state['to_visit'] or len(state['pages']) >= state['crawl_limit']:
            log(f"ページ収集完了。{len(state['pages'])}記事を発見。リンク関係の構築に移ります。")
            state['phase'] = 'linking'
            state['link_analysis_keys'] = list(state['pages'].keys()) # これから処理する記事リスト
        
        return state

    # フェーズ3：リンク関係を構築
    if state['phase'] == 'linking':
        link_batch_size = 10 # 一度に10ページ処理
        session = state['session']
        
        processed_count = len(state['pages']) - len(state['link_analysis_keys'])
        total_pages = len(state['pages'])

        linked_in_this_step = 0
        while state['link_analysis_keys'] and linked_in_this_step < link_batch_size:
            url = state['link_analysis_keys'].pop(0)
            
            try:
                log(f"リンク解析中 ({processed_count + linked_in_this_step + 1}/{total_pages}): {url}")
                response = session.get(url, timeout=20)
                if response.status_code != 200: continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                content_links = extract_content_links(soup, url)
                
                for link_data in content_links:
                    target = link_data['url']
                    if target in state['pages'] and target != url:
                        link_key = (url, target)
                        if link_key not in state['processed_links']:
                            state['processed_links'].add(link_key)
                            state['links'].append((url, target))
                            state['pages'][url]['outbound_links'].append(target)
                            state['detailed_links'].append({
                                'source_url': url, 'source_title': state['pages'][url]['title'],
                                'target_url': target, 'anchor_text': link_data['anchor_text']
                            })
                
                linked_in_this_step += 1
                time.sleep(0.2)
            except Exception as e:
                log(f"リンク解析エラー: {url} - {e}")
                continue
        
        # プログレスバー更新
        progress = (processed_count + linked_in_this_step) / total_pages if total_pages > 0 else 0
        state['progress'] = 0.5 + (progress * 0.5) # 全体の50%〜100%
        state['progress_text'] = f"リンク解析: {processed_count + linked_in_this_step} / {total_pages}"

        if not state['link_analysis_keys']:
            log("リンク関係構築完了。最終処理に入ります。")
            state['phase'] = 'completed'
            # 被リンク数を計算
            for url in state['pages']:
                state['pages'][url]['inbound_links'] = sum(1 for s, t in state['links'] if t == url)
        
        return state

    return state


# ★★★ CSV生成用の関数 ★★★
def generate_csv(state):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['A_番号', 'B_ページタイトル', 'C_URL', 'D_被リンク元ページタイトル', 'E_被リンク元ページURL', 'F_被リンク元ページアンカーテキスト'])
    
    pages = state['pages']
    detailed_links = state['detailed_links']
    
    # ターゲット別にグループ化
    targets = {}
    for link in detailed_links:
        target = link['target_url']
        targets.setdefault(target, []).append(link)
    
    # 被リンク数でソート
    sorted_targets = sorted(targets.items(), key=lambda x: len(x[1]), reverse=True)
    
    # 番号付け
    page_numbers = {}
    current_page_number = 1
    for target_url, _ in sorted_targets:
        page_numbers[target_url] = current_page_number
        current_page_number += 1
    for url in pages:
        if url not in page_numbers:
            page_numbers[url] = current_page_number
            current_page_number += 1
            
    # CSV書き出し
    for target_url, links_list in sorted_targets:
        page_num = page_numbers.get(target_url)
        title = pages.get(target_url, {}).get('title', target_url)
        for link in links_list:
            writer.writerow([page_num, title, target_url, link['source_title'], link['source_url'], link['anchor_text']])
    
    for url, info in pages.items():
        if info.get('inbound_links', 0) == 0:
            page_num = page_numbers.get(url)
            writer.writerow([page_num, info['title'], url, '', '', ''])
            
    return output.getvalue()
