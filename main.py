# main.py （最終・完全バグ修正版）

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import os
import json
import math
import tempfile
from pathlib import Path
from collections import Counter
from datetime import datetime
from urllib.parse import urlparse, urlunparse
import base64
from io import BytesIO, StringIO
import zipfile
import importlib.util
import time

# PyVis（オプション）
try:
    from pyvis.network import Network
    HAS_PYVIS = True
except ImportError:
    HAS_PYVIS = False

# ページ設定
st.set_page_config(
    page_title="🔗 内部リンク構造分析ツール",
    page_icon="🔗",
    layout="wide",
    initial_sidebar_state="expanded"
)

# カスタムCSS
st.markdown("""
<style>
    .main-header { font-size: 2.5rem; font-weight: bold; text-align: center; margin-bottom: 2rem; color: #1f77b4; }
    .success-box { background-color: #d4edda; border: 1px solid #c3e6cb; border-radius: 0.25rem; padding: 0.75rem; margin: 1rem 0; }
    .warning-box { background-color: #fff3cd; border: 1px solid #ffeaa7; border-radius: 0.25rem; padding: 0.75rem; margin: 1rem 0; }
</style>
""", unsafe_allow_html=True)

# --- ユーティリティ関数（変更なし） ---
@st.cache_data
def normalize_url(u, default_scheme="https", base_domain=None):
    if not isinstance(u, str) or not u.strip(): return ""
    u = u.strip()
    try:
        p = urlparse(u)
        if not p.netloc and base_domain:
            path = u if u.startswith("/") else f"/{u}"
            u = f"{default_scheme}://{base_domain}{path}"
            p = urlparse(u)
        elif not p.netloc: return u
        scheme = p.scheme or default_scheme
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
    site_name = "Unknown Site"
    for key, name in site_name_map.items():
        if key in filename:
            site_name = name
            break
    domains = [urlparse(u).netloc.replace("www.","") for u in df['C_URL'].dropna() if isinstance(u, str) and 'http' in u]
    site_domain = Counter(domains).most_common(1)[0][0] if domains else None
    return site_name, site_domain

def generate_html_table(title, columns, rows):
    def esc(x): return str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = f"<!doctype html><meta charset='utf-8'><title>{esc(title)}</title>"
    html += "<style>body{font-family:sans-serif;padding:16px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:8px;font-size:14px}th{position:sticky;top:0;background:#f7f7f7}a{color:#1565c0;text-decoration:none}a:hover{text-decoration:underline}</style>"
    html += f"<h1>{esc(title)}</h1><table><thead><tr>{''.join(f'<th>{esc(c)}</th>' for c in columns)}</tr></thead><tbody>"
    for row in rows:
        html += "<tr>"
        for i, cell in enumerate(row):
            val = esc(cell)
            if "URL" in columns[i].upper() and val.startswith("http"):
                val = f"<a href='{val}' target='_blank'>{val}</a>"
            html += f"<td>{val}</td>"
        html += "</tr>"
    html += "</tbody></table>"
    return html
    
# メイン関数
def main():
    st.markdown('<div class="main-header">🔗 内部リンク構造分析ツール</div>', unsafe_allow_html=True)
    
    if 'analysis_state' not in st.session_state:
        st.session_state.analysis_state = {}

    with st.sidebar:
        st.header("📁 データ設定")
        
        try:
            site_files = sorted([f for f in os.listdir('.') if f.startswith('auto_') and f.endswith('.py')])
            site_names = [os.path.splitext(f)[0] for f in site_files]
        except Exception:
            site_files, site_names = [], []

        source_options = ["CSVファイルをアップロード"]
        if site_names:
            source_options.insert(0, "オンラインで新規分析を実行")
        
        analysis_source = st.radio("データソースを選択", source_options, key="analysis_source", on_change=lambda: st.session_state.pop('analysis_state', None))
        
        # ★★★ ここが最重要修正点 ★★★
        # uploaded_file を if/else の前に初期化します
        uploaded_file = None
        
        if analysis_source == "オンラインで新規分析を実行" and site_names:
            st.subheader("分析対象サイト")
            selected_site_name = st.selectbox("サイトを選択してください", options=site_names)
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🚀 分析開始/再開", key="run_analysis"):
                    if st.session_state.analysis_state.get('site_name') != selected_site_name:
                        st.session_state.analysis_state = {
                            'site_name': selected_site_name, 'phase': 'initializing', 'log': [f"「{selected_site_name}」の分析準備を開始します..."],
                            'to_visit': [], 'visited': set(), 'pages': {}, 'processed_links': set(), 'links': [], 'detailed_links': []
                        }
                    st.session_state.analysis_state['running'] = True
                    st.rerun()
            with col2:
                if st.button("⏹️ 中断/リセット"):
                    st.session_state.analysis_state = {}
                    st.rerun()
        else:
            uploaded_file = st.file_uploader("CSVファイルをアップロード", type=['csv'])

    if st.session_state.analysis_state.get('running'):
        state = st.session_state.analysis_state
        site_name = state['site_name']
        
        st.info(f"「{site_name}」の分析を実行中... (フェーズ: {state.get('phase', 'unknown')})")
        log_placeholder = st.empty()
        progress_placeholder = st.empty()

        try:
            spec = importlib.util.spec_from_file_location(site_name, f"{site_name}.py")
            site_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(site_module)
            
            new_state = site_module.analyze_step(state)
            st.session_state.analysis_state = new_state
            
            log_placeholder.code('\n'.join(new_state.get('log', [])), language="log")
            if 'progress' in new_state:
                progress_placeholder.progress(new_state['progress'], text=new_state.get('progress_text', ''))
            
            if new_state.get('phase') == 'completed':
                st.session_state.analysis_state['running'] = False
                st.success("分析が完了しました。結果を生成します。")
                
                csv_string = site_module.generate_csv(new_state)
                st.session_state['last_analyzed_csv_data'] = csv_string
                st.session_state['last_analyzed_filename'] = f"{site_name}_analysis.csv"
                st.rerun()
            else:
                time.sleep(0.5)
                st.rerun()

        except Exception as e:
            st.error(f"分析中に致命的なエラーが発生しました: {e}")
            st.exception(e)
            st.session_state.analysis_state['running'] = False
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
        st.info("👆 サイドバーからデータソースを選択し、分析を実行するか、CSVファイルをアップロードしてください。")
        return

    try:
        df = pd.read_csv(data_source, encoding="utf-8-sig", header=0).fillna("")
        
        # A_番号の処理をより安全に
        df['A_番号'] = pd.to_numeric(df['A_番号'], errors='coerce')
        # 同じC_URLを持つ行グループに同じ番号を振る
        df['A_番号'] = df.groupby('C_URL').ngroup() + 1
        
        site_name, site_domain = detect_site_info(filename_for_detect, df)
        
        st.markdown(f"### {site_name} の分析結果")
        st.dataframe(df)
        
    except Exception as e:
        st.error(f"❌ データ処理中にエラーが発生しました: {e}")
        st.exception(e)

if __name__ == "__main__":
    main()
