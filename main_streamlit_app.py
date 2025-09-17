#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
内部リンク構造分析ツール - Streamlit版 (ローカル分析機能統合)
- ピラーページ / クラスター（アンカー） / 孤立記事を全件出力
- ネットワーク図（静的：plotly、インタラクティブ：pyvis）
- ローカル分析実行機能 or CSVアップロード機能
- HTMLレポート生成・ダウンロード機能
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import os
import sys
import json
import math
import tempfile
from pathlib import Path
from collections import Counter
from datetime import datetime
from urllib.parse import urlparse
import base64
from io import BytesIO
import zipfile
import subprocess

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
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        text-align: center;
        margin-bottom: 2rem;
        color: #1f77b4;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #1f77b4;
    }
    .success-box {
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        border-radius: 0.25rem;
        padding: 0.75rem;
        margin: 1rem 0;
    }
    .warning-box {
        background-color: #fff3cd;
        border: 1px solid #ffeaa7;
        border-radius: 0.25rem;
        padding: 0.75rem;
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)

# ユーティリティ関数 (変更なし)
@st.cache_data
def safe_str(s):
    return s if isinstance(s, str) else ""

@st.cache_data
def normalize_url(u, default_scheme="https", base_domain=None):
    if not isinstance(u, str) or not u.strip():
        return ""
    u = u.strip()
    try:
        from urllib.parse import urlparse, urlunparse
        p = urlparse(u)
        if not p.netloc and base_domain:
            path = u if u.startswith("/") else f"/{u}"
            u = f"{default_scheme}://{base_domain}{path}"
            p = urlparse(u)
        elif not p.netloc:
            return u
        scheme = p.scheme or default_scheme
        netloc = p.netloc.lower().replace("www.", "")
        path = p.path or "/"
        return urlunparse((scheme, netloc, path, p.params, p.query, ""))
    except Exception:
        return u

def detect_site_info(filename, df):
    site_map = {
        'arigataya': 'ありがたや',
        'kau-ru': 'カウール',
        'kaitori-life': '買取LIFE',
        'friendpay': 'フレンドペイ',
        'crecaeru': 'クレかえる',
    }
    site_name = "Unknown Site"
    for key, name in site_map.items():
        if key in filename.lower():
            site_name = name
            break
    
    domains = [urlparse(u).netloc.replace("www.","") for u in df['C_URL'].dropna() if isinstance(u, str) and 'http' in u]
    site_domain = Counter(domains).most_common(1)[0][0] if domains else None
    
    return site_name, site_domain

def create_download_link(content, filename, link_text="ダウンロード"):
    if isinstance(content, str):
        content = content.encode('utf-8')
    b64 = base64.b64encode(content).decode()
    href = f'<a href="data:application/octet-stream;base64,{b64}" download="{filename}" style="text-decoration: none; background-color: #1f77b4; color: white; padding: 0.5rem 1rem; border-radius: 0.25rem; display: inline-block;">{link_text}</a>'
    return href

def generate_html_table(title, columns, rows):
    def esc(x): return str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = f"<!doctype html><meta charset='utf-8'><title>{esc(title)}</title>"
    html += "<style>body{font-family:sans-serif;padding:16px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:8px;font-size:14px}th{background:#f7f7f7;font-weight:bold}a{color:#1565c0;text-decoration:none}a:hover{text-decoration:underline}</style>"
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
    
    # --- サイドバー ---
    with st.sidebar:
        st.header("📁 データソース設定")
        
        analysis_source = st.radio(
            "どちらの方法で分析しますか？",
            ("ローカルで新規分析を実行", "既存のCSVファイルをアップロード"),
            key="analysis_source"
        )
        
        uploaded_file_obj = None
        
        if analysis_source == "ローカルで新規分析を実行":
            st.subheader("分析対象サイト")
            
            # 主の管理サイトリスト
            available_sites = [
                "arigataya", "kau-ru", "kaitori-life", "friendpay", "crecaeru",
                # "site6", "site7", "site8", "site9", "site10" # 必要に応じて追加
            ]
            
            selected_site = st.selectbox(
                "サイトを選択してください",
                options=available_sites
            )
            
            # ローカル分析スクリプトのパス
            # このStreamlitアプリと同じ階層にあることを想定
            analyzer_script_path = "local_analyzer_cli.py"

            if st.button("🚀 分析を実行する", key="run_local_analysis"):
                if not os.path.exists(analyzer_script_path):
                    st.error(f"分析スクリプトが見つかりません: {analyzer_script_path}\nこのファイルと同じ階層に配置してください。")
                else:
                    with st.spinner(f"「{selected_site}」の内部リンクを分析中です...しばらくお待ちください。"):
                        try:
                            output_csv_path = os.path.join(tempfile.gettempdir(), f"{selected_site}_links_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv")
                            
                            python_executable = sys.executable
                            command = [python_executable, analyzer_script_path, selected_site, output_csv_path]
                            
                            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
                            
                            log_placeholder = st.empty()
                            logs = ""
                            while True:
                                output = process.stdout.readline()
                                if output == '' and process.poll() is not None:
                                    break
                                if output:
                                    logs += output
                                    log_placeholder.code(logs, language="log")
                            
                            stderr = process.communicate()[1]

                            if process.returncode == 0:
                                st.success(f"「{selected_site}」の分析が完了しました。")
                                st.session_state['last_analyzed_csv'] = output_csv_path
                                # 成功したらページを再読み込みして結果を表示
                                st.experimental_rerun()
                            else:
                                st.error("分析スクリプトの実行中にエラーが発生しました。")
                                st.error("エラーログ:")
                                st.code(stderr, language="log")

                        except Exception as e:
                            st.error(f"予期せぬエラーが発生しました: {e}")

        else: # CSVアップロードの場合
            uploaded_file_obj = st.file_uploader(
                "CSVファイルをアップロード",
                type=['csv'],
                help="内部リンクデータのCSVファイルを選択してください"
            )

        st.header("🛠️ 分析設定")
        network_top_n = st.slider("ネットワーク図：上位N件", 10, 100, 40, 5)
        st.header("📊 レポート設定")
        auto_download = st.checkbox("HTMLレポート自動生成", value=True)

    # --- メインエリア ---
    
    # 分析に使用するファイルを決定
    target_file = None
    if uploaded_file_obj:
        target_file = uploaded_file_obj
    elif 'last_analyzed_csv' in st.session_state and os.path.exists(st.session_state['last_analyzed_csv']):
        target_file = st.session_state['last_analyzed_csv']
        st.info(f"ローカルで分析したファイル「{os.path.basename(target_file)}」を読み込んでいます。")

    if target_file is None:
        st.info("👆 サイドバーからデータソースを選択し、分析を実行するか、CSVファイルをアップロードしてください。")
        st.subheader("📋 期待されるCSVフォーマット")
        st.code("""A_番号,B_ページタイトル,C_URL,D_被リンク元ページタイトル,E_被リンク元ページURL,F_被リンク元ページアンカーテキスト""")
        return

    # データ読み込み
    try:
        if isinstance(target_file, str):
            df = pd.read_csv(target_file, encoding="utf-8-sig").fillna("")
            filename_for_detect = os.path.basename(target_file)
        else:
            df = pd.read_csv(target_file, encoding="utf-8-sig").fillna("")
            filename_for_detect = target_file.name

        expected_columns = ['A_番号', 'B_ページタイトル', 'C_URL', 'D_被リンク元ページタイトル', 'E_被リンク元ページURL', 'F_被リンク元ページアンカーテキスト']
        if not all(col in df.columns for col in expected_columns):
            st.error(f"❌ 必要な列が不足しています。期待される列: {expected_columns}")
            return
        
        site_name, site_domain = detect_site_info(filename_for_detect, df)
        
        df['C_URL'] = df['C_URL'].apply(lambda u: normalize_url(u, base_domain=site_domain))
        df['E_被リンク元ページURL'] = df['E_被リンク元ページURL'].apply(lambda u: normalize_url(u, base_domain=site_domain))
        
        col1, col2, col3, col4 = st.columns(4)
        unique_pages = df[['B_ページタイトル', 'C_URL']].drop_duplicates()
        has_link = (df['E_被リンク元ページURL'].astype(str) != "")
        unique_anchors = df[df['F_被リンク元ページアンカーテキスト'].astype(str) != '']['F_被リンク元ページアンカーテキスト'].nunique()
        col1.metric("📊 総レコード数", len(df))
        col2.metric("📄 ユニークページ数", len(unique_pages))
        col3.metric("🔗 内部リンク数", int(has_link.sum()))
        col4.metric("🏷️ ユニークアンカー数", unique_anchors)
        
        st.markdown(f"""<div class="success-box">
            <strong>📁 読み込み完了:</strong> {filename_for_detect}<br>
            <strong>🌐 サイト:</strong> {site_name}<br>
            <strong>🔗 ドメイン:</strong> {site_domain or '不明'}
        </div>""", unsafe_allow_html=True)

        # ---------------------------------------------------------------------
        # 以降、主からいただいた元の `main.py` の分析・表示ロジックをそのまま流用します
        # ---------------------------------------------------------------------

        tab1, tab2, tab3, tab4, tab5 = st.tabs(["🏛️ ピラーページ", "🧩 クラスター分析", "🧭 孤立記事", "📈 ネットワーク図", "📊 総合レポート"])
        
        pages_df = df[['B_ページタイトル', 'C_URL']].drop_duplicates().copy()
        inbound_df = df[(df['E_被リンク元ページURL'].astype(str) != "") & (df['C_URL'].astype(str) != "")]
        inbound_counts = inbound_df.groupby('C_URL').size()
        pages_df['被リンク数'] = pages_df['C_URL'].map(inbound_counts).fillna(0).astype(int)
        pages_df = pages_df.sort_values(['被リンク数', 'B_ページタイトル'], ascending=[False, True]).reset_index(drop=True)

        # Tab 1: ピラーページ分析
        with tab1:
            st.header("🏛️ ピラーページ分析")
            top_n_pillar = st.slider("表示件数", 5, 50, 20, key="pillar_top_n")
            top_pages = pages_df.head(top_n_pillar)
            fig = px.bar(top_pages.head(15).sort_values('被リンク数'), x='被リンク数', y='B_ページタイトル', orientation='h', title="被リンク数 TOP15")
            st.plotly_chart(fig, use_container_width=True)
            st.subheader("📋 ピラーページ一覧")
            st.dataframe(top_pages[['B_ページタイトル', 'C_URL', '被リンク数']], use_container_width=True)

        # Tab 2: クラスター分析
        with tab2:
            st.header("🧩 クラスター分析（アンカーテキスト）")
            anchor_df = df[df['F_被リンク元ページアンカーテキスト'].astype(str) != '']
            anchor_counts = Counter(anchor_df['F_被リンク元ページアンカーテキスト'])
            if anchor_counts:
                total_anchors = sum(anchor_counts.values())
                diversity_index = 1 - sum((c/total_anchors)**2 for c in anchor_counts.values())
                col1, col2, col3 = st.columns(3)
                col1.metric("🔢 総アンカー数", total_anchors)
                col2.metric("🏷️ ユニークアンカー数", len(anchor_counts))
                col3.metric("📊 多様性指数", f"{diversity_index:.3f}", help="1に近いほど多様")
                
                top_anchors = pd.DataFrame(anchor_counts.most_common(15), columns=['アンカーテキスト', '頻度']).sort_values('頻度')
                fig = px.bar(top_anchors, x='頻度', y='アンカーテキスト', orientation='h', title="アンカーテキスト頻度 TOP15")
                st.plotly_chart(fig, use_container_width=True)

                st.subheader("📋 アンカーテキスト一覧")
                st.dataframe(pd.DataFrame(anchor_counts.most_common(), columns=['アンカーテキスト', '頻度']), use_container_width=True)
            else:
                st.warning("⚠️ アンカーテキストデータが見つかりません。")

        # Tab 3: 孤立記事
        with tab3:
            st.header("🧭 孤立記事分析")
            isolated_pages = pages_df[pages_df['被リンク数'] == 0].copy()
            if not isolated_pages.empty:
                st.metric("🏝️ 孤立記事数", len(isolated_pages))
                st.dataframe(isolated_pages[['B_ページタイトル', 'C_URL']], use_container_width=True)
            else:
                st.success("🎉 孤立記事は見つかりませんでした！")

        # Tab 4: ネットワーク図
        with tab4:
            st.header("📈 ネットワーク図")
            if HAS_PYVIS:
                st.info("🔄 インタラクティブネットワーク図を生成中...")
                try:
                    edges_df = df[(df['E_被リンク元ページURL'] != "") & (df['C_URL'] != "")].copy()
                    top_urls = set(pages_df.head(network_top_n)['C_URL'])
                    sub_edges = edges_df[edges_df['C_URL'].isin(top_urls) & edges_df['E_被リンク元ページURL'].isin(top_urls)]
                    
                    if not sub_edges.empty:
                        agg = sub_edges.groupby(['E_被リンク元ページURL', 'C_URL']).size().reset_index(name='weight')
                        
                        url_map = pd.concat([
                            df[['C_URL', 'B_ページタイトル']].rename(columns={'C_URL':'url', 'B_ページタイトル':'title'}),
                            df[['E_被リンク元ページURL', 'D_被リンク元ページタイトル']].rename(columns={'E_被リンク元ページURL':'url', 'D_被リンク元ページタイトル':'title'})
                        ]).drop_duplicates('url').set_index('url')['title'].to_dict()

                        net = Network(height="800px", width="100%", directed=True, notebook=True)
                        net.set_options('{"physics":{"barnesHut":{"gravitationalConstant":-8000,"springLength":150,"avoidOverlap":0.1}}}')

                        nodes = set(agg['E_被リンク元ページURL']).union(set(agg['C_URL']))
                        for u in nodes:
                            net.add_node(u, label=str(url_map.get(u, u))[:20], title=url_map.get(u, u), size=10 + math.log2(inbound_counts.get(u, 0) + 1) * 5)
                        
                        for _, r in agg.iterrows():
                            net.add_edge(r['E_被リンク元ページURL'], r['C_URL'], value=r['weight'])
                        
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as tmp:
                            net.save_graph(tmp.name)
                            with open(tmp.name, 'r') as f:
                                st.components.v1.html(f.read(), height=820)
                        os.unlink(tmp.name)
                    else:
                        st.warning("ネットワークを描画するためのリンクデータが不足しています。")

                except Exception as e:
                    st.error(f"❌ ネットワーク図の生成に失敗しました: {e}")
            else:
                st.error("❌ pyvisライブラリが必要です。`pip install pyvis`でインストールしてください。")
        
        # Tab 5: 総合レポート
        with tab5:
            st.header("📊 総合レポート")
            st.write("全ての分析結果をまとめたレポートです。")
            if st.button("📥 総合レポートをダウンロード", key="download_summary"):
                zip_buffer = BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                    # ピラーページ
                    rows = [[i, r['B_ページタイトル'], r['C_URL'], r['被リンク数']] for i, r in pages_df.iterrows()]
                    zf.writestr("1_pillar_report.html", generate_html_table(f"{site_name} ピラーページ", ["#", "タイトル", "URL", "被リンク数"], rows))
                    # アンカー
                    if anchor_counts:
                        rows = [[i, a, c] for i, (a,c) in enumerate(anchor_counts.most_common())]
                        zf.writestr("2_anchor_report.html", generate_html_table(f"{site_name} アンカーテキスト", ["#", "アンカー", "頻度"], rows))
                    # 孤立記事
                    if not isolated_pages.empty:
                        rows = [[i, r['B_ページタイトル'], r['C_URL']] for i, r in isolated_pages.iterrows()]
                        zf.writestr("3_isolated_report.html", generate_html_table(f"{site_name} 孤立記事", ["#", "タイトル", "URL"], rows))
                
                zip_buffer.seek(0)
                b64 = base64.b64encode(zip_buffer.getvalue()).decode()
                filename = f"report_{site_name}_{datetime.now().strftime('%Y%m%d')}.zip"
                href = f'<a href="data:application/zip;base64,{b64}" download="{filename}" style="text-decoration: none; background-color: #28a745; color: white; padding: 0.75rem 1.5rem; border-radius: 0.25rem; display: inline-block; font-weight: bold;">📦 総合レポート(ZIP)をダウンロード</a>'
                st.markdown(href, unsafe_allow_html=True)
    
    except Exception as e:
        st.error(f"❌ データ処理中にエラーが発生しました: {e}")
        st.exception(e)

if __name__ == "__main__":
    main()
