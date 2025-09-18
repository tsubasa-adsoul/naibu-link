#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
内部リンク構造分析ツール - Streamlit版
- ピラーページ / クラスター（アンカー） / 孤立記事を全件出力
- ネットワーク図（静的：plotly、インタラクティブ：pyvis）
- CSVアップロード機能
- HTMLレポート生成・ダウンロード機能
"""

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
from urllib.parse import urlparse
import base64
from io import BytesIO
import zipfile

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

# ユーティリティ関数
@st.cache_data
def safe_str(s):
    return s if isinstance(s, str) else ""

@st.cache_data
def normalize_url(u, default_scheme="https", base_domain=None):
    """URL正規化"""
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
        netloc = p.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        path = p.path or "/"
        return urlunparse((scheme, netloc, path, p.params, p.query, ""))
    except Exception:
        return u

def detect_site_info(filename, df):
    """ファイル名とURLからサイト情報を推測"""
    filename = filename.lower()
    
    # ファイル名からサイト名推測
    if 'kau-ru' in filename:
        site_name = "カウール"
    elif 'kaitori-life' in filename:
        site_name = "買取LIFE"
    elif 'friendpay' in filename:
        site_name = "フレンドペイ"
    elif 'kurekaeru' in filename or 'crecaeru' in filename:
        site_name = "クレかえる"
    else:
        site_name = "Unknown Site"
    
    # URLからドメイン推測
    domains = []
    for u in df['C_URL'].tolist():
        if isinstance(u, str) and u:
            try:
                d = urlparse(u).netloc.lower()
                if d.startswith("www."):
                    d = d[4:]
                if d:
                    domains.append(d)
            except Exception:
                continue
    
    site_domain = Counter(domains).most_common(1)[0][0] if domains else None
    
    return site_name, site_domain

def create_download_link(content, filename, link_text="ダウンロード"):
    """ダウンロードリンクを作成"""
    if isinstance(content, str):
        content = content.encode('utf-8')
    
    b64 = base64.b64encode(content).decode()
    href = f'<a href="data:text/html;base64,{b64}" download="{filename}" style="text-decoration: none; background-color: #1f77b4; color: white; padding: 0.5rem 1rem; border-radius: 0.25rem; display: inline-block;">{link_text}</a>'
    return href

def generate_html_table(title, columns, rows):
    """HTML表を生成"""
    def esc(x):
        return str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    html_parts = [
        "<!doctype html>",
        "<meta charset='utf-8'>",
        f"<title>{esc(title)}</title>",
        """<style>
            body { font-family: Arial, 'Yu Gothic', Meiryo, sans-serif; padding: 16px; }
            table { border-collapse: collapse; width: 100%; }
            th, td { border: 1px solid #ddd; padding: 8px; font-size: 14px; }
            th { position: sticky; top: 0; background: #f7f7f7; font-weight: bold; }
            tr:nth-child(even) { background: #fafafa; }
            a { color: #1565c0; text-decoration: none; }
            a:hover { text-decoration: underline; }
            .header { text-align: center; margin-bottom: 2rem; }
        </style>""",
        f"<div class='header'><h1>{esc(title)}</h1></div>",
        "<table><thead><tr>"
    ]
    
    for col in columns:
        html_parts.append(f"<th>{esc(col)}</th>")
    
    html_parts.append("</tr></thead><tbody>")
    
    for row in rows:
        html_parts.append("<tr>")
        for i, cell in enumerate(row):
            val = esc(cell)
            header = columns[i]
            if "URL" in header.upper() or header.endswith("URL"):
                if val and (val.startswith("http://") or val.startswith("https://")):
                    val = f"<a href='{val}' target='_blank' rel='noopener'>{val}</a>"
            html_parts.append(f"<td>{val}</td>")
        html_parts.append("</tr>")
    
    html_parts.append("</tbody></table>")
    return "".join(html_parts)

# メイン関数
def main():
    # ヘッダー
    st.markdown('<div class="main-header">🔗 内部リンク構造分析ツール</div>', unsafe_allow_html=True)
    
    # サイドバー
    with st.sidebar:
        st.header("📁 データ設定")
        
        # CSVアップロード
        uploaded_file = st.file_uploader(
            "CSVファイルをアップロード",
            type=['csv'],
            help="内部リンクデータのCSVファイルを選択してください"
        )
        
        if uploaded_file is not None:
            st.success("✅ ファイルがアップロードされました")
        
        st.header("🛠️ 分析設定")
        
        # ネットワーク図設定
        network_top_n = st.slider(
            "ネットワーク図：上位N件",
            min_value=10,
            max_value=100,
            value=40,
            step=5,
            help="ネットワーク図に表示する上位ページ数"
        )
        
        show_isolated = st.checkbox(
            "孤立ページも表示",
            value=False,
            help="ネットワーク図に孤立ページも含める"
        )
        
        # レポート設定
        st.header("📊 レポート設定")
        auto_download = st.checkbox(
            "HTMLレポート自動生成",
            value=True,
            help="分析実行時にHTMLレポートを自動生成"
        )

    # メインエリア
    if uploaded_file is None:
        st.info("👆 サイドバーからCSVファイルをアップロードしてください")
        
        # 期待されるCSVフォーマットを表示
        st.subheader("📋 期待されるCSVフォーマット")
        expected_columns = [
            'A_番号',
            'B_ページタイトル', 
            'C_URL',
            'D_被リンク元ページタイトル',
            'E_被リンク元ページURL',
            'F_被リンク元ページアンカーテキスト'
        ]
        
        sample_data = pd.DataFrame({
            'カラム名': expected_columns,
            '説明': [
                '連番',
                'ターゲットページのタイトル',
                'ターゲットページのURL',
                'リンク元ページのタイトル',
                'リンク元ページのURL',
                'アンカーテキスト'
            ]
        })
        st.dataframe(sample_data, use_container_width=True)
        return
    
    # データ読み込み
    try:
        df = pd.read_csv(uploaded_file, encoding="utf-8-sig").fillna("")
        
        # 必要な列の存在確認
        expected_columns = [
            'A_番号', 'B_ページタイトル', 'C_URL',
            'D_被リンク元ページタイトル', 'E_被リンク元ページURL', 'F_被リンク元ページアンカーテキスト'
        ]
        
        missing_columns = [col for col in expected_columns if col not in df.columns]
        if missing_columns:
            st.error(f"❌ 必要な列が不足しています: {missing_columns}")
            st.write("実際の列:", list(df.columns))
            return
        
        # サイト情報検出
        site_name, site_domain = detect_site_info(uploaded_file.name, df)
        
        # URL正規化
        def norm_url(u):
            return normalize_url(u, base_domain=site_domain)
        
        df['C_URL'] = df['C_URL'].apply(norm_url)
        df['E_被リンク元ページURL'] = df['E_被リンク元ページURL'].apply(norm_url)
        
        # データ概要表示
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("📊 総レコード数", len(df))
        
        with col2:
            unique_pages = df[['B_ページタイトル', 'C_URL']].drop_duplicates()
            st.metric("📄 ユニークページ数", len(unique_pages))
        
        with col3:
            has_link = (df['E_被リンク元ページURL'].astype(str) != "") & (df['C_URL'].astype(str) != "")
            st.metric("🔗 内部リンク数", has_link.sum())
        
        with col4:
            unique_anchors = df[df['F_被リンク元ページアンカーテキスト'].astype(str) != '']['F_被リンク元ページアンカーテキスト'].nunique()
            st.metric("🏷️ ユニークアンカー数", unique_anchors)
        
        st.markdown(f"""
        <div class="success-box">
            <strong>📁 読み込み完了:</strong> {uploaded_file.name}<br>
            <strong>🌐 サイト:</strong> {site_name}<br>
            <strong>🔗 ドメイン:</strong> {site_domain or '不明'}
        </div>
        """, unsafe_allow_html=True)
        
        # タブで機能を分割
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "🏛️ ピラーページ", "🧩 クラスター分析", "🧭 孤立記事", 
            "📈 ネットワーク図", "📊 総合レポート"
        ])
        
        # 共通データ準備
        pages_df = df[['B_ページタイトル', 'C_URL']].drop_duplicates().copy()
        
        # 被リンク数計算
        has_source = (df['D_被リンク元ページタイトル'].astype(str) != "") & (df['E_被リンク元ページURL'].astype(str) != "")
        inbound_df = df[has_source & (df['C_URL'].astype(str) != "")]
        inbound_counts = inbound_df.groupby('C_URL').size()
        
        pages_df['被リンク数'] = pages_df['C_URL'].map(inbound_counts).fillna(0).astype(int)
        pages_df = pages_df.sort_values(['被リンク数', 'B_ページタイトル'], ascending=[False, True])
        
        # Tab 1: ピラーページ分析
        with tab1:
            st.header("🏛️ ピラーページ分析")
            st.write("被リンク数の多いページを特定します。")
            
            # 上位表示件数設定
            top_n_pillar = st.slider("表示件数", 5, 50, 20, key="pillar_top_n")
            
            # 上位ページ表示
            top_pages = pages_df.head(top_n_pillar)
            
            # グラフ表示
            fig = px.bar(
                top_pages.head(15), 
                x='被リンク数', 
                y='B_ページタイトル',
                orientation='h',
                title="被リンク数 TOP15",
                labels={'被リンク数': '被リンク数', 'B_ページタイトル': 'ページタイトル'}
            )
            fig.update_layout(yaxis={'categoryorder':'total ascending'}, height=600)
            st.plotly_chart(fig, use_container_width=True)
            
            # データテーブル表示
            st.subheader("📋 ピラーページ一覧")
            display_df = top_pages[['B_ページタイトル', 'C_URL', '被リンク数']].copy()
            display_df.index = range(1, len(display_df) + 1)
            st.dataframe(display_df, use_container_width=True)
            
            # HTMLレポート生成
            if auto_download and st.button("📥 ピラーページレポートをダウンロード", key="download_pillar"):
                rows = [[i, safe_str(row['B_ページタイトル']), safe_str(row['C_URL']), int(row['被リンク数'])]
                        for i, (_, row) in enumerate(pages_df.iterrows(), 1)]
                
                html_content = generate_html_table(
                    f"{site_name} ピラーページ分析レポート",
                    ["#", "ページタイトル", "URL", "被リンク数"],
                    rows
                )
                
                filename = f"pillar_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                download_link = create_download_link(html_content, filename)
                st.markdown(download_link, unsafe_allow_html=True)
        
        # Tab 2: クラスター分析
        with tab2:
            st.header("🧩 クラスター分析（アンカーテキスト）")
            st.write("アンカーテキストの頻度と多様性を分析します。")
            
            # アンカーテキスト分析
            anchor_df = df[df['F_被リンク元ページアンカーテキスト'].astype(str) != '']
            anchor_counts = Counter(anchor_df['F_被リンク元ページアンカーテキスト'])
            
            if anchor_counts:
                total_anchors = sum(anchor_counts.values())
                unique_anchors = len(anchor_counts)
                
                # HHI（ハーフィンダール・ハーシュマン指数）計算
                hhi = sum((count/total_anchors)**2 for count in anchor_counts.values())
                diversity_index = 1 - hhi
                
                # メトリクス表示
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("🔢 総アンカー数", total_anchors)
                with col2:
                    st.metric("🏷️ ユニークアンカー数", unique_anchors)
                with col3:
                    st.metric("📊 多様性指数", f"{diversity_index:.3f}", help="1に近いほど多様")
                
                # 上位アンカーテキストのグラフ
                top_anchors = pd.DataFrame(anchor_counts.most_common(20), columns=['アンカーテキスト', '頻度'])
                
                fig = px.bar(
                    top_anchors.head(15),
                    x='頻度',
                    y='アンカーテキスト',
                    orientation='h',
                    title="アンカーテキスト頻度 TOP15"
                )
                fig.update_layout(yaxis={'categoryorder':'total ascending'}, height=600)
                st.plotly_chart(fig, use_container_width=True)
                
                # データテーブル表示
                st.subheader("📋 アンカーテキスト一覧")
                display_anchors = pd.DataFrame(anchor_counts.most_common(), columns=['アンカーテキスト', '頻度'])
                display_anchors.index = range(1, len(display_anchors) + 1)
                st.dataframe(display_anchors, use_container_width=True)
                
                # HTMLレポート生成
                if auto_download and st.button("📥 アンカーレポートをダウンロード", key="download_anchor"):
                    rows = [[i, anchor, count] for i, (anchor, count) in enumerate(anchor_counts.most_common(), 1)]
                    
                    html_content = generate_html_table(
                        f"{site_name} アンカーテキスト分析レポート",
                        ["#", "アンカーテキスト", "頻度"],
                        rows
                    )
                    
                    filename = f"anchor_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                    download_link = create_download_link(html_content, filename)
                    st.markdown(download_link, unsafe_allow_html=True)
            else:
                st.warning("⚠️ アンカーテキストデータが見つかりません。")
        
        # Tab 3: 孤立記事
        with tab3:
            st.header("🧭 孤立記事分析")
            st.write("内部リンクを受けていないページを特定します。")
            
            # 孤立記事抽出
            isolated_pages = pages_df[pages_df['被リンク数'] == 0].copy()
            
            if not isolated_pages.empty:
                st.metric("🏝️ 孤立記事数", len(isolated_pages))
                
                # データテーブル表示
                st.subheader("📋 孤立記事一覧")
                display_isolated = isolated_pages[['B_ページタイトル', 'C_URL']].copy()
                display_isolated.index = range(1, len(display_isolated) + 1)
                st.dataframe(display_isolated, use_container_width=True)
                
                # HTMLレポート生成
                if auto_download and st.button("📥 孤立記事レポートをダウンロード", key="download_isolated"):
                    rows = [[i, safe_str(row['B_ページタイトル']), safe_str(row['C_URL'])]
                            for i, (_, row) in enumerate(isolated_pages.iterrows(), 1)]
                    
                    html_content = generate_html_table(
                        f"{site_name} 孤立記事分析レポート",
                        ["#", "ページタイトル", "URL"],
                        rows
                    )
                    
                    filename = f"isolated_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                    download_link = create_download_link(html_content, filename)
                    st.markdown(download_link, unsafe_allow_html=True)
            else:
                st.success("🎉 孤立記事は見つかりませんでした！")
        
        # Tab 4: ネットワーク図
        with tab4:
            st.header("📈 ネットワーク図")
            st.write("内部リンクの関係性を可視化します。")
            
            # ネットワークタイプ選択
            network_type = st.radio(
                "表示タイプを選択",
                ["散布図（軽量）", "ネットワーク図（中重量）", "インタラクティブ（重い）"],
                key="network_type"
            )
            
            if network_type == "散布図（軽量）":
                # 簡易散布図
                top_pages_network = pages_df.head(network_top_n)
                
                fig = px.scatter(
                    top_pages_network,
                    x=range(len(top_pages_network)),
                    y='被リンク数',
                    size='被リンク数',
                    hover_data=['B_ページタイトル', 'C_URL'],
                    title=f"被リンク数分布（上位{network_top_n}件）"
                )
                fig.update_layout(
                    xaxis_title="ページ順位",
                    yaxis_title="被リンク数",
                    height=600
                )
                st.plotly_chart(fig, use_container_width=True)
            
            elif network_type == "ネットワーク図（中重量）":
                # Plotlyネットワーク図
                st.info("🔄 ネットワーク図を生成中...")
                
                # エッジデータ準備
                edges_df = df[
                    (df['E_被リンク元ページURL'].astype(str) != "") &
                    (df['C_URL'].astype(str) != "")
                ][['E_被リンク元ページURL', 'C_URL']].copy()
                
                # 上位ページのみ
                top_urls = set(pages_df.head(network_top_n)['C_URL'])
                edges_filtered = edges_df[
                    edges_df['C_URL'].isin(top_urls)
                ]
                
                if not edges_filtered.empty:
                    # ノード準備
                    nodes = set(edges_filtered['E_被リンク元ページURL']).union(set(edges_filtered['C_URL']))
                    node_list = list(nodes)
                    node_indices = {node: i for i, node in enumerate(node_list)}
                    
                    # エッジ準備
                    edge_trace = []
                    for _, row in edges_filtered.iterrows():
                        x0, y0 = divmod(node_indices[row['E_被リンク元ページURL']], 10)
                        x1, y1 = divmod(node_indices[row['C_URL']], 10)
                        edge_trace.extend([x0, x1, None])
                        edge_trace.extend([y0, y1, None])
                    
                    # ノード位置とサイズ
                    node_x = [i // 10 for i in range(len(node_list))]
                    node_y = [i % 10 for i in range(len(node_list))]
                    node_sizes = [max(10, inbound_counts.get(node, 0) * 2) for node in node_list]
                    
                    # グラフ作成
                    fig = go.Figure()
                    
                    # エッジ描画
                    fig.add_trace(go.Scatter(
                        x=edge_trace[::3],
                        y=edge_trace[1::3],
                        mode='lines',
                        line=dict(width=0.5, color='#888'),
                        hoverinfo='none',
                        showlegend=False
                    ))
                    
                    # ノード描画
                    fig.add_trace(go.Scatter(
                        x=node_x,
                        y=node_y,
                        mode='markers',
                        marker=dict(
                            size=node_sizes,
                            color='lightblue',
                            line=dict(width=1, color='darkblue')
                        ),
                        text=[f"被リンク: {inbound_counts.get(node, 0)}" for node in node_list],
                        hoverinfo='text',
                        showlegend=False
                    ))
                    
                    fig.update_layout(
                        title="内部リンクネットワーク",
                        showlegend=False,
                        hovermode='closest',
                        margin=dict(b=20,l=5,r=5,t=40),
                        annotations=[
                            dict(
                                text="ノードサイズ = 被リンク数",
                                showarrow=False,
                                xref="paper", yref="paper",
                                x=0.005, y=-0.002,
                                xanchor='left', yanchor='bottom',
                                font=dict(size=12)
                            )
                        ],
                        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                        height=600
                    )
                    
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("⚠️ 表示できるネットワークデータがありません。")
            
            elif network_type == "インタラクティブ（重い）":
                if not HAS_PYVIS:
                    st.error("❌ pyvisライブラリが必要です。`pip install pyvis`でインストールしてください。")
                else:
                    st.info("🔄 インタラクティブネットワーク図を生成中...")
                    
                    # 元のローカル版のコードをそのまま採用
                    try:
                        edges_df = df[
                            (df['E_被リンク元ページURL'].astype(str) != "") &
                            (df['C_URL'].astype(str) != "")
                        ][['D_被リンク元ページタイトル', 'E_被リンク元ページURL',
                           'B_ページタイトル', 'C_URL']].copy()

                        def in_site(u: str) -> bool:
                            try:
                                d = urlparse(u).netloc.lower()
                                if d.startswith("www."): d = d[4:]
                                return (not site_domain) or (d == site_domain) or d.endswith("." + site_domain)
                            except Exception:
                                return True
                        
                        edges_df = edges_df[edges_df['E_被リンク元ページURL'].apply(in_site) & edges_df['C_URL'].apply(in_site)]
                        
                        if edges_df.empty:
                            st.warning("⚠️ 描画対象エッジがありません。")
                            return

                        in_counts = edges_df.groupby('C_URL').size().sort_values(ascending=False)

                        TOP_N = network_top_n  # サイドバーの設定値を使用
                        top_targets = set(in_counts.head(TOP_N).index)

                        sub = edges_df[edges_df['C_URL'].isin(top_targets)].copy()
                        agg = sub.groupby(['E_被リンク元ページURL', 'C_URL']).size().reset_index(name='weight')

                        url2title = {}
                        for _, r in df[['B_ページタイトル','C_URL']].drop_duplicates().iterrows():
                            if r['C_URL']:
                                url2title[r['C_URL']] = r['B_ページタイトル']
                        for _, r in df[['D_被リンク元ページタイトル','E_被リンク元ページURL']].drop_duplicates().iterrows():
                            if r['E_被リンク元ページURL']:
                                url2title.setdefault(r['E_被リンク元ページURL'], r['D_被リンク元ページタイトル'])

                        def short_label(u: str, n=24) -> str:
                            t = str(url2title.get(u, u))
                            return (t[:n] + "…") if len(t) > n else t

                        net = Network(height="800px", width="100%", directed=True, bgcolor="#ffffff")
                        options = {
                            "physics": {
                                "enabled": True,
                                "solver": "barnesHut",
                                "barnesHut": {
                                    "gravitationalConstant": -8000,
                                    "centralGravity": 0.3,
                                    "springLength": 160,
                                    "springConstant": 0.03,
                                    "damping": 0.12,
                                    "avoidOverlap": 0.1
                                },
                                "stabilization": {"enabled": True, "iterations": 120, "updateInterval": 25},
                                "minVelocity": 1,
                                "timestep": 0.6
                            },
                            "interaction": {
                                "hover": True, "zoomView": True, "dragView": True,
                                "dragNodes": True, "navigationButtons": True, "keyboard": True
                            },
                            "nodes": {"shape": "dot", "font": {"size": 12}},
                            "edges": {"smooth": {"enabled": True, "type": "dynamic"},
                                      "scaling": {"min": 1, "max": 8}}
                        }
                        net.set_options(json.dumps(options))

                        nodes = set(agg['E_被リンク元ページURL']).union(set(agg['C_URL']))
                        
                        def node_size(u: str) -> int:
                            s = int(in_counts.get(u, 0))
                            return max(12, min(48, int(12 + math.log2(s + 1) * 8)))

                        for u in nodes:
                            net.add_node(
                                u,
                                label=short_label(u),
                                title=f"{url2title.get(u, u)}<br>{u}",
                                size=node_size(u)
                            )

                        for _, r in agg.iterrows():
                            src = r['E_被リンク元ページURL']
                            dst = r['C_URL']
                            w   = int(r['weight'])
                            net.add_edge(src, dst, value=w, arrows="to")

                        # 一時ファイルに保存してからStreamlitで表示
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as tmp_file:
                            net.write_html(tmp_file.name, open_browser=False)
                            
                            with open(tmp_file.name, 'r', encoding='utf-8') as f:
                                html_content = f.read()
                            
                            # Streamlit用にHTMLを調整
                            html_content = html_content.replace(
                                '<div id="mynetworkid"',
                                '<div id="mynetworkid" style="border: 1px solid #ddd;"'
                            )
                            
                            # Streamlitで表示
                            st.components.v1.html(html_content, height=850)
                            
                            # 統計表示
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                st.metric("ノード数", len(nodes))
                            with col2:
                                st.metric("エッジ数", len(agg))
                            with col3:
                                st.metric("上位ターゲット数", len(top_targets))
                            
                            # ダウンロードリンク
                            filename = f"interactive_network_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                            download_link = create_download_link(html_content, filename, "📥 ネットワーク図をダウンロード")
                            st.markdown(download_link, unsafe_allow_html=True)
                            
                            # 一時ファイル削除
                            os.unlink(tmp_file.name)

                    except Exception as e:
                        st.error(f"❌ ネットワーク図の生成に失敗しました: {e}")
                        st.write("エラー詳細:", str(e))
        
        # Tab 5: 総合レポート
        with tab5:
            st.header("📊 総合レポート")
            st.write("全ての分析結果をまとめたレポートです。")
            
            # サマリー統計
            st.subheader("📈 サイト統計サマリー")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("### 🎯 基本統計")
                basic_stats = {
                    "総ページ数": len(pages_df),
                    "総内部リンク数": has_source.sum(),
                    "孤立ページ数": len(pages_df[pages_df['被リンク数'] == 0]),
                    "平均被リンク数": f"{pages_df['被リンク数'].mean():.2f}",
                    "最大被リンク数": int(pages_df['被リンク数'].max()),
                    "ユニークアンカー数": unique_anchors
                }
                
                for key, value in basic_stats.items():
                    st.metric(key, value)
            
            with col2:
                st.markdown("### 📊 被リンク数分布")
                # ヒストグラム
                fig = px.histogram(
                    pages_df,
                    x='被リンク数',
                    nbins=20,
                    title="被リンク数の分布"
                )
                fig.update_layout(height=400)
                st.plotly_chart(fig, use_container_width=True)
            
            # 上位/下位ページ
            st.subheader("🏆 トップ＆ボトム")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### 🥇 被リンク数 TOP10")
                top10 = pages_df.head(10)[['B_ページタイトル', '被リンク数']]
                top10.index = range(1, 11)
                st.dataframe(top10, use_container_width=True)
            
            with col2:
                st.markdown("#### 🥉 被リンク数 BOTTOM10")
                bottom10 = pages_df[pages_df['被リンク数'] > 0].tail(10)[['B_ページタイトル', '被リンク数']]
                bottom10.index = range(1, len(bottom10) + 1)
                st.dataframe(bottom10, use_container_width=True)
            
            # アンカーテキスト分析
            if anchor_counts:
                st.subheader("🏷️ アンカーテキスト分析")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("#### 🔝 頻出アンカー TOP10")
                    top_anchors = pd.DataFrame(
                        anchor_counts.most_common(10),
                        columns=['アンカーテキスト', '頻度']
                    )
                    top_anchors.index = range(1, len(top_anchors) + 1)
                    st.dataframe(top_anchors, use_container_width=True)
                
                with col2:
                    st.markdown("#### 📊 アンカー多様性")
                    total_anchors = sum(anchor_counts.values())
                    hhi = sum((count/total_anchors)**2 for count in anchor_counts.values())
                    diversity_index = 1 - hhi
                    
                    st.metric("多様性指数", f"{diversity_index:.3f}")
                    st.metric("集中度（HHI）", f"{hhi:.3f}")
                    
                    # 解釈
                    if diversity_index > 0.8:
                        interpretation = "🟢 非常に多様"
                    elif diversity_index > 0.6:
                        interpretation = "🟡 やや多様"
                    else:
                        interpretation = "🔴 集中している"
                    
                    st.write(f"**解釈:** {interpretation}")
            
            # 問題の検出
            st.subheader("⚠️ 問題検出")
            
            issues = []
            
            # 孤立ページが多い
            isolated_count = len(pages_df[pages_df['被リンク数'] == 0])
            isolated_ratio = isolated_count / len(pages_df)
            if isolated_ratio > 0.3:
                issues.append(f"🏝️ 孤立ページが多すぎます（{isolated_count}件, {isolated_ratio:.1%}）")
            
            # 被リンクが極端に偏っている
            top1_ratio = pages_df.iloc[0]['被リンク数'] / pages_df['被リンク数'].sum() if pages_df['被リンク数'].sum() > 0 else 0
            if top1_ratio > 0.5:
                issues.append(f"🎯 被リンクが1ページに集中しすぎています（{top1_ratio:.1%}）")
            
            # アンカーテキストの多様性が低い
            if anchor_counts and diversity_index < 0.3:
                issues.append(f"🏷️ アンカーテキストの多様性が低いです（{diversity_index:.3f}）")
            
            if issues:
                for issue in issues:
                    st.warning(issue)
            else:
                st.success("🎉 特に大きな問題は検出されませんでした！")
            
            # 推奨事項
            st.subheader("💡 推奨事項")
            
            recommendations = []
            
            if isolated_count > 0:
                recommendations.append("🔗 孤立ページに内部リンクを追加してください")
            
            if top1_ratio > 0.3:
                recommendations.append("⚖️ 内部リンクをより均等に分散させてください")
            
            if anchor_counts and diversity_index < 0.5:
                recommendations.append("🏷️ アンカーテキストのバリエーションを増やしてください")
            
            if len(pages_df) > 100 and pages_df['被リンク数'].mean() < 2:
                recommendations.append("📈 全体的な内部リンク密度を高めてください")
            
            if recommendations:
                for rec in recommendations:
                    st.info(rec)
            else:
                st.success("✅ 現在の内部リンク構造は良好です！")
            
            # 全体レポートダウンロード
            if st.button("📥 総合レポートをダウンロード", key="download_summary"):
                # ZIPファイルで全レポートをまとめる
                zip_buffer = BytesIO()
                
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                    # ピラーページレポート
                    pillar_rows = [[i, safe_str(row['B_ページタイトル']), safe_str(row['C_URL']), int(row['被リンク数'])]
                                  for i, (_, row) in enumerate(pages_df.iterrows(), 1)]
                    pillar_html = generate_html_table(
                        f"{site_name} ピラーページ分析レポート",
                        ["#", "ページタイトル", "URL", "被リンク数"],
                        pillar_rows
                    )
                    zip_file.writestr("pillar_report.html", pillar_html.encode('utf-8'))
                    
                    # アンカーレポート
                    if anchor_counts:
                        anchor_rows = [[i, anchor, count] for i, (anchor, count) in enumerate(anchor_counts.most_common(), 1)]
                        anchor_html = generate_html_table(
                            f"{site_name} アンカーテキスト分析レポート",
                            ["#", "アンカーテキスト", "頻度"],
                            anchor_rows
                        )
                        zip_file.writestr("anchor_report.html", anchor_html.encode('utf-8'))
                    
                    # 孤立記事レポート
                    if isolated_count > 0:
                        isolated_pages = pages_df[pages_df['被リンク数'] == 0]
                        isolated_rows = [[i, safe_str(row['B_ページタイトル']), safe_str(row['C_URL'])]
                                        for i, (_, row) in enumerate(isolated_pages.iterrows(), 1)]
                        isolated_html = generate_html_table(
                            f"{site_name} 孤立記事分析レポート",
                            ["#", "ページタイトル", "URL"],
                            isolated_rows
                        )
                        zip_file.writestr("isolated_report.html", isolated_html.encode('utf-8'))
                    
                    # サマリーレポート
                    summary_content = f"""
                    <!doctype html>
                    <meta charset='utf-8'>
                    <title>{site_name} 総合分析レポート</title>
                    <style>
                        body {{ font-family: Arial, 'Yu Gothic', Meiryo, sans-serif; padding: 20px; }}
                        .header {{ text-align: center; margin-bottom: 2rem; }}
                        .section {{ margin: 2rem 0; padding: 1rem; border-left: 4px solid #1f77b4; background: #f8f9fa; }}
                        .metric {{ display: inline-block; margin: 0.5rem 1rem; padding: 0.5rem; background: white; border-radius: 4px; }}
                        .issue {{ color: #dc3545; margin: 0.5rem 0; }}
                        .recommendation {{ color: #28a745; margin: 0.5rem 0; }}
                    </style>
                    <div class='header'>
                        <h1>{site_name} 内部リンク構造分析 総合レポート</h1>
                        <p>生成日時: {datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}</p>
                    </div>
                    
                    <div class='section'>
                        <h2>📊 基本統計</h2>
                        <div class='metric'>総ページ数: {len(pages_df)}</div>
                        <div class='metric'>総内部リンク数: {has_source.sum()}</div>
                        <div class='metric'>孤立ページ数: {isolated_count}</div>
                        <div class='metric'>平均被リンク数: {pages_df['被リンク数'].mean():.2f}</div>
                        <div class='metric'>最大被リンク数: {int(pages_df['被リンク数'].max())}</div>
                        <div class='metric'>ユニークアンカー数: {unique_anchors}</div>
                    </div>
                    
                    <div class='section'>
                        <h2>⚠️ 検出された問題</h2>
                        {('<br>'.join([f'<div class="issue">{issue}</div>' for issue in issues]) if issues else '<p>問題は検出されませんでした。</p>')}
                    </div>
                    
                    <div class='section'>
                        <h2>💡 推奨事項</h2>
                        {('<br>'.join([f'<div class="recommendation">{rec}</div>' for rec in recommendations]) if recommendations else '<p>現在の構造は良好です。</p>')}
                    </div>
                    """
                    zip_file.writestr("summary_report.html", summary_content.encode('utf-8'))
                
                zip_buffer.seek(0)
                
                # ダウンロードリンク作成
                b64 = base64.b64encode(zip_buffer.getvalue()).decode()
                filename = f"link_analysis_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
                href = f'<a href="data:application/zip;base64,{b64}" download="{filename}" style="text-decoration: none; background-color: #1f77b4; color: white; padding: 0.75rem 1.5rem; border-radius: 0.25rem; display: inline-block; font-weight: bold;">📦 総合レポート（ZIP）をダウンロード</a>'
                st.markdown(href, unsafe_allow_html=True)
    
    except Exception as e:
        st.error(f"❌ データ処理中にエラーが発生しました: {e}")
        st.write("エラーの詳細:")
        st.exception(e)

if __name__ == "__main__":
    main()
