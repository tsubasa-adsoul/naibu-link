# main.py （真の最終完成版・全機能統合 v2）

import streamlit as st
import pandas as pd
import plotly.express as px
import importlib.util
import time
from io import StringIO
from urllib.parse import urlparse, urlunparse
from collections import Counter
import numpy as np
import os
import math
import tempfile

# PyVis（オプション）
try:
    from pyvis.network import Network
    HAS_PYVIS = True
except ImportError:
    HAS_PYVIS = False

# ページ設定とCSS
st.set_page_config(page_title="🔗 内部リンク構造分析ツール", layout="wide")
st.markdown("""<style>.main-header { font-size: 2.5rem; font-weight: bold; text-align: center; margin-bottom: 2rem; color: #1f77b4; }</style>""", unsafe_allow_html=True)
st.markdown("""<style>.success-box { background-color: #d4edda; border: 1px solid #c3e6cb; border-radius: 0.25rem; padding: 0.75rem; margin: 1rem 0; }</style>""", unsafe_allow_html=True)

# --- ユーティリティ関数 ---
@st.cache_data
def normalize_url_for_display(u, base_domain=None):
    if not isinstance(u, str) or not u.strip(): return ""
    try:
        p = urlparse(u)
        if not p.netloc and base_domain:
            u = f"https://{base_domain}{'/' if not u.startswith('/') else ''}{u}"
            p = urlparse(u)
        scheme = p.scheme or 'https'
        netloc = p.netloc.lower().replace("www.", "")
        path = p.path or "/"
        return urlunparse((scheme, netloc, path, p.params, p.query, ""))
    except Exception: return u

def detect_site_info(filename, df):
    filename = filename.lower()
    site_name_map = {
        'auto_answer': "Answer現金化", 'auto_arigataya': "ありがたや", 'auto_bicgift': "ビックギフト",
        'auto_crecaeru': "クレかえる", 'auto_flashpay_famipay': "ファミペイ", 
        'auto_flashpay_media': "メディア", 'auto_friendpay': "フレンドペイ",
        'auto_fuyouhin': "不用品回収隊", 'auto_kaitori_life': "買取LIFE", 'auto_kau_ru': "カウール",
        'auto_morepay': "MorePay", 'auto_payful': "ペイフル", 'auto_smart': "スマートペイ", 'auto_xgift': "XGIFT"
    }
    site_name = next((name for key, name in site_name_map.items() if key in filename), "Unknown Site")
    domains = [urlparse(u).netloc.replace("www.","") for u in df['C_URL'].dropna() if isinstance(u, str) and 'http' in u]
    site_domain = Counter(domains).most_common(1)[0][0] if domains else None
    return site_name, site_domain

# --- 分析実行ループ ---
def run_analysis_loop():
    # (この関数は変更なし)
    state = st.session_state.analysis_state
    site_name = state['site_name']
    
    st.info(f"「{site_name}」の分析を実行中... (フェーズ: {state.get('phase', 'unknown')})")
    log_placeholder = st.empty()
    progress_placeholder = st.empty()
    
    while state.get('running') and state.get('phase') != 'completed' and state.get('phase') != 'error':
        try:
            spec = importlib.util.spec_from_file_location(site_name, f"{site_name}.py")
            site_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(site_module)
            
            state = site_module.analyze_step(state)
            
            log_placeholder.code('\n'.join(state.get('log', [])), language="log")
            if 'progress' in state:
                progress_placeholder.progress(state['progress'], text=state.get('progress_text', ''))
            
            st.session_state.analysis_state = state
            time.sleep(1)
        except Exception as e:
            st.error(f"分析中に致命的なエラーが発生しました: {e}")
            st.exception(e)
            state['running'] = False
            state['phase'] = 'error'
            st.session_state.analysis_state = state
            break

    if st.session_state.analysis_state.get('phase') == 'completed':
        st.session_state.analysis_state['running'] = False
        st.success("分析が完了しました。結果を生成します。")
        
        spec = importlib.util.spec_from_file_location(site_name, f"{site_name}.py")
        site_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(site_module)
        csv_string = site_module.generate_csv(st.session_state.analysis_state)
        
        st.session_state['last_analyzed_csv_data'] = csv_string
        st.session_state['last_analyzed_filename'] = f"{site_name}_analysis.csv"
        st.rerun()

# --- メイン関数 ---
def main():
    st.markdown('<div class="main-header">🔗 内部リンク構造分析ツール</div>', unsafe_allow_html=True)
    
    if 'analysis_state' not in st.session_state:
        st.session_state.analysis_state = {}

    with st.sidebar:
        st.header("📁 データ設定")
        try:
            site_files = sorted([f for f in os.listdir('.') if f.startswith('auto_') and f.endswith('.py')])
            site_names = [os.path.splitext(f)[0] for f in site_files]
        except: site_files, site_names = [], []

        source_options = ["CSVファイルをアップロード"]
        if site_names: source_options.insert(0, "オンラインで新規分析を実行")
        
        analysis_source = st.radio("データソースを選択", source_options, key="analysis_source", on_change=lambda: st.session_state.pop('analysis_state', None))
        
        uploaded_file = None
        if analysis_source == "オンラインで新規分析を実行" and site_names:
            selected_site_name = st.selectbox("サイトを選択してください", options=site_names)
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🚀 分析開始/再開"):
                    if st.session_state.analysis_state.get('site_name') != selected_site_name:
                        st.session_state.analysis_state = {'site_name': selected_site_name, 'phase': 'initializing'}
                    st.session_state.analysis_state['running'] = True
                    st.rerun()
            with col2:
                if st.button("⏹️ 中断/リセット"):
                    st.session_state.analysis_state = {}
                    st.rerun()
        else:
            uploaded_file = st.file_uploader("CSVファイルをアップロード", type=['csv'])
        
        st.header("🛠️ 分析設定")
        network_top_n = st.slider("ネットワーク図：上位N件", 10, 100, 40, 5, help="ネットワーク図に表示する上位ページ数")

    if st.session_state.analysis_state.get('running'):
        run_analysis_loop()
        return

    data_source = None
    filename_for_detect = "analysis"
    if uploaded_file:
        data_source = uploaded_file
        filename_for_detect = uploaded_file.name
    elif 'last_analyzed_csv_data' in st.session_state:
        data_source = StringIO(st.session_state['last_analyzed_csv_data'])
        filename_for_detect = st.session_state['last_analyzed_filename']
    
    if data_source is None:
        st.info("👆 サイドバーからデータソースを選択するか、CSVファイルをアップロードしてください。")
        return

    try:
        df = pd.read_csv(data_source, encoding="utf-8-sig", header=0)
        if df.empty:
            st.warning("分析結果が0件でした。クロールが正常に行われなかったか、対象ページが存在しない可能性があります。")
            return

        df.columns = ['A_番号', 'B_ページタイトル', 'C_URL', 'D_被リンク元ページタイトル', 'E_被リンク元ページURL', 'F_被リンク元ページアンカーテキスト']
        df = df.fillna('')
        df['A_番号'] = df.groupby('C_URL')['A_番号'].transform('first')
        df['A_番号'] = pd.to_numeric(df['A_番号'], errors='coerce').fillna(0).astype(int)
        
        site_name, site_domain = detect_site_info(filename_for_detect, df)
        df['C_URL'] = df['C_URL'].apply(lambda u: normalize_url_for_display(u, base_domain=site_domain))
        df['E_被リンク元ページURL'] = df['E_被リンク元ページURL'].apply(lambda u: normalize_url_for_display(u, base_domain=site_domain))
        
        st.markdown(f"### {site_name} の分析結果")
        
        # ★★★ タブ構成を完全に復元 ★★★
        tab1, tab2, tab3, tab4 = st.tabs(["📊 データ一覧", "🏛️ ピラーページ", "🧩 クラスター分析", "📈 ネットワーク図"])
        
        pages_df = df[['B_ページタイトル', 'C_URL']].drop_duplicates().copy()
        inbound_counts = df[df['D_被リンク元ページタイトル'] != ''].groupby('C_URL').size()
        pages_df['被リンク数'] = pages_df['C_URL'].map(inbound_counts).fillna(0).astype(int)
        pages_df = pages_df.sort_values('被リンク数', ascending=False).reset_index(drop=True)

        with tab1:
            st.dataframe(df)

        with tab2:
            st.header("🏛️ ピラーページ分析")
            st.dataframe(pages_df[['B_ページタイトル', 'C_URL', '被リンク数']], use_container_width=True)
            fig = px.bar(pages_df.head(20).sort_values('被リンク数'), x='被リンク数', y='B_ページタイトル', orientation='h', title="被リンク数 TOP20")
            st.plotly_chart(fig, use_container_width=True)

        with tab3:
            st.header("🧩 クラスター分析（アンカーテキスト）")
            anchor_counts = Counter(df[df['F_被リンク元ページアンカーテキスト'] != '']['F_被リンク元ページアンカーテキスト'])
            if anchor_counts:
                st.dataframe(pd.DataFrame(anchor_counts.most_common(), columns=['アンカーテキスト', '頻度']), use_container_width=True)
            else:
                st.warning("アンカーテキストデータがありません。")

        # ★★★ ネットワーク図機能を完全に復元 ★★★
        with tab4:
            st.header("📈 ネットワーク図")
            if not HAS_PYVIS:
                st.error("❌ pyvisライブラリが必要です。`pip install pyvis`でインストールしてください。")
            else:
                st.info("🔄 インタラクティブネットワーク図を生成中...")
                try:
                    edges_df = df[(df['E_被リンク元ページURL'] != "") & (df['C_URL'] != "")].copy()
                    top_n_urls = set(pages_df.head(network_top_n)['C_URL'])
                    relevant_urls = top_n_urls.union(set(edges_df[edges_df['C_URL'].isin(top_n_urls)]['E_被リンク元ページURL']))
                    sub_edges = edges_df[edges_df['C_URL'].isin(relevant_urls) & edges_df['E_被リンク元ページURL'].isin(relevant_urls)]
                    
                    if not sub_edges.empty:
                        agg = sub_edges.groupby(['E_被リンク元ページURL', 'C_URL']).size().reset_index(name='weight')
                        url_map = pd.concat([df[['C_URL', 'B_ページタイトル']].rename(columns={'C_URL':'url', 'B_ページタイトル':'title'}), df[['E_被リンク元ページURL', 'D_被リンク元ページタイトル']].rename(columns={'E_被リンク元ページURL':'url', 'D_被リンク元ページタイトル':'title'})]).drop_duplicates('url').set_index('url')['title'].to_dict()
                        
                        net = Network(height="800px", width="100%", directed=True, notebook=True, cdn_resources='in_line')
                        net.set_options('{"physics":{"barnesHut":{"gravitationalConstant":-8000,"springLength":150,"avoidOverlap":0.1}}}')

                        nodes = set(agg['E_被リンク元ページURL']).union(set(agg['C_URL']))
                        for u in nodes:
                            net.add_node(u, label=str(url_map.get(u, u))[:20], title=url_map.get(u, u), size=10 + math.log2(inbound_counts.get(u, 0) + 1) * 4)
                        for _, r in agg.iterrows():
                            net.add_edge(r['E_被リンク元ページURL'], r['C_URL'], value=r['weight'])
                        
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as tmp:
                            net.save_graph(tmp.name)
                            with open(tmp.name, 'r', encoding='utf-8') as f:
                                st.components.v1.html(f.read(), height=820, scrolling=True)
                        os.unlink(tmp.name)
                    else:
                        st.warning("ネットワークを描画するためのリンクデータが不足しています。")
                except Exception as e:
                    st.error(f"❌ ネットワーク図の生成に失敗しました: {e}")

    except Exception as e:
        st.error(f"❌ データ処理中にエラーが発生しました: {e}")
        st.exception(e)

if __name__ == "__main__":
    main()
