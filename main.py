#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
内部リンク構造分析ツール（Streamlit版）
- CSVファイルアップロード
- ピラーページ分析
- クラスター（アンカーテキスト）分析
- 孤立記事分析
- インタラクティブネットワーク図（PyVis）
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from collections import Counter
from urllib.parse import urlparse
import tempfile
import os
from pathlib import Path
import logging

# PyVis（任意）
try:
    from pyvis.network import Network
    HAS_PYVIS = True
except ImportError:
    HAS_PYVIS = False
    st.error("PyVisライブラリがインストールされていません。`pip install pyvis`を実行してください。")

# ページ設定
st.set_page_config(
    page_title="内部リンク構造分析ツール",
    page_icon="🔗",
    layout="wide"
)

EXPECTED_COLUMNS = [
    'A_番号',
    'B_ページタイトル', 
    'C_URL',
    'D_被リンク元ページタイトル',
    'E_被リンク元ページURL',
    'F_被リンク元ページアンカーテキスト'
]

def safe_str(s):
    return s if isinstance(s, str) else ""

def normalize_url(u, default_scheme="https", base_domain=None):
    if not isinstance(u, str) or not u.strip():
        return ""
    u = u.strip()
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

def detect_site_info(filename, df):
    filename = filename.lower() if filename else ""
    
    if 'kau-ru' in filename or 'kauru' in filename:
        site_name = "カウール"
    elif 'kaitori-life' in filename:
        site_name = "買取LIFE"  
    elif 'friendpay' in filename:
        site_name = "フレンドペイ"
    elif 'kurekaeru' in filename or 'crecaeru' in filename:
        site_name = "クレかえる"
    elif 'bicgift' in filename or 'bic-gift' in filename:
        site_name = "ビックギフト"
    else:
        site_name = "Unknown Site"

    # ドメインを特定
    domains = []
    for u in df['C_URL'].tolist():
        if isinstance(u, str) and u:
            d = urlparse(u).netloc.lower()
            if d.startswith("www."): 
                d = d[4:]
            if d: 
                domains.append(d)
    
    site_domain = Counter(domains).most_common(1)[0][0] if domains else None
    return site_name, site_domain

def create_network_visualization(df, site_name, top_n=40):
    """PyVisを使用してネットワーク図を作成"""
    if not HAS_PYVIS:
        st.error("PyVisが利用できません")
        return None
    
    try:
        # エッジデータを準備
        edges_df = df[
            (df['E_被リンク元ページURL'].astype(str) != "") &
            (df['C_URL'].astype(str) != "")
        ][['D_被リンク元ページタイトル', 'E_被リンク元ページURL',
           'B_ページタイトル', 'C_URL']].copy()

        if edges_df.empty:
            st.warning("描画対象のエッジがありません")
            return None

        # 被リンク数を計算
        in_counts = edges_df.groupby('C_URL').size().sort_values(ascending=False)
        
        # 上位N件を選択
        top_targets = set(in_counts.head(top_n).index)
        sub = edges_df[edges_df['C_URL'].isin(top_targets)].copy()
        
        # エッジを集約
        agg = sub.groupby(['E_被リンク元ページURL', 'C_URL']).size().reset_index(name='weight')
        
        # URLとタイトルのマッピングを作成
        url2title = {}
        for _, r in df[['B_ページタイトル','C_URL']].drop_duplicates().iterrows():
            if r['C_URL']:
                url2title[r['C_URL']] = r['B_ページタイトル']
        for _, r in df[['D_被リンク元ページタイトル','E_被リンク元ページURL']].drop_duplicates().iterrows():
            if r['E_被リンク元ページURL']:
                url2title.setdefault(r['E_被リンク元ページURL'], r['D_被リンク元ページタイトル'])

        def short_label(u: str, n=20) -> str:
            t = str(url2title.get(u, u))
            return (t[:n] + "...") if len(t) > n else t

        # PyVisネットワークを作成
        net = Network(
            height="800px", 
            width="100%", 
            directed=True, 
            bgcolor="#ffffff"
        )
        
        # 物理設定
        net.barnes_hut(
            gravity=-8000,
            central_gravity=0.3,
            spring_length=200,
            spring_strength=0.05,
            damping=0.15
        )

        # ノードとエッジを追加
        nodes = set(agg['E_被リンク元ページURL']).union(set(agg['C_URL']))
        
        for u in nodes:
            size = max(15, min(50, int(15 + (in_counts.get(u, 0) * 2))))
            net.add_node(
                u,
                label=short_label(u),
                title=f"{url2title.get(u, u)}<br>{u}",
                size=size
            )

        for _, r in agg.iterrows():
            net.add_edge(
                r['E_被リンク元ページURL'], 
                r['C_URL'], 
                width=min(int(r['weight']), 10)
            )

        # 一時ファイルに保存
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as tmp:
            net.save_graph(tmp.name)
            with open(tmp.name, 'r', encoding='utf-8') as f:
                html_content = f.read()
            os.unlink(tmp.name)
            
        return html_content
        
    except Exception as e:
        st.error(f"ネットワーク図の生成に失敗しました: {e}")
        return None

def main():
    st.title("🔗 内部リンク構造分析ツール")
    st.markdown("CSVファイルをアップロードして、内部リンク構造を分析します。")

    # サイドバーでファイルアップロード
    with st.sidebar:
        st.header("📂 ファイル設定")
        uploaded_file = st.file_uploader("CSVファイルをアップロード", type=['csv'])
        
        if uploaded_file:
            st.success(f"アップロード完了: {uploaded_file.name}")
            
        st.header("🛠️ 表示設定")
        network_top_n = st.slider("ネットワーク図：上位N件", 10, 100, 40, 5)

    if uploaded_file is None:
        st.info("👈 サイドバーからCSVファイルをアップロードしてください")
        return

    # CSVファイルの読み込み
    try:
        df = pd.read_csv(uploaded_file, encoding="utf-8-sig").fillna("")
        
        # 列の確認
        if not all(col in df.columns for col in EXPECTED_COLUMNS):
            st.error(f"CSV列が不足しています\n必要: {EXPECTED_COLUMNS}\n実際: {list(df.columns)}")
            return
            
        # サイト情報の検出
        site_name, site_domain = detect_site_info(uploaded_file.name, df)
        
        # URL正規化
        def _norm(u): 
            return normalize_url(u, base_domain=site_domain)
        df['C_URL'] = df['C_URL'].apply(_norm)
        df['E_被リンク元ページURL'] = df['E_被リンク元ページURL'].apply(_norm)
        
        st.success(f"データ読み込み完了: {site_name} ({len(df)}行)")
        
    except Exception as e:
        st.error(f"CSVファイルの読み込みに失敗しました: {e}")
        return

    # タブで機能を分割
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 データ一覧", 
        "🏛️ ピラーページ", 
        "🧩 クラスター分析", 
        "🧭 孤立記事",
        "📈 ネットワーク図"
    ])

    # データ集計
    pages_df = df[['B_ページタイトル', 'C_URL']].drop_duplicates().copy()
    has_src = (df['D_被リンク元ページタイトル'].astype(str) != "") & (df['E_被リンク元ページURL'].astype(str) != "")
    inbound_df = df[has_src & (df['C_URL'].astype(str) != "")]
    inbound_counts = inbound_df.groupby('C_URL').size()
    pages_df['被リンク数'] = pages_df['C_URL'].map(inbound_counts).fillna(0).astype(int)
    pages_df = pages_df.sort_values('被リンク数', ascending=False).reset_index(drop=True)

    with tab1:
        st.header("📊 全データ")
        st.dataframe(df, use_container_width=True)

    with tab2:
        st.header("🏛️ ピラーページ分析")
        st.dataframe(pages_df, use_container_width=True)
        
        # 上位20件の棒グラフ
        if len(pages_df) > 0:
            top20 = pages_df.head(20)
            fig = px.bar(
                top20.sort_values('被リンク数'), 
                x='被リンク数', 
                y='B_ページタイトル',
                orientation='h',
                title="被リンク数 TOP20",
                height=600
            )
            fig.update_layout(yaxis={'categoryorder': 'total ascending'})
            st.plotly_chart(fig, use_container_width=True)

    with tab3:
        st.header("🧩 クラスター分析（アンカーテキスト）")
        
        anchors = df[df['F_被リンク元ページアンカーテキスト'].astype(str) != '']
        if not anchors.empty:
            anchor_counts = Counter(anchors['F_被リンク元ページアンカーテキスト'])
            anchor_df = pd.DataFrame(anchor_counts.most_common(), columns=['アンカーテキスト', '頻度'])
            
            # 多様性指標の計算
            total = sum(anchor_counts.values())
            hhi = sum((c/total)**2 for c in anchor_counts.values()) if total else 0.0
            diversity = 1 - hhi
            
            st.metric("アンカーテキスト多様性", f"{diversity:.3f}", help="1に近いほど多様")
            st.dataframe(anchor_df, use_container_width=True)
        else:
            st.warning("アンカーテキストデータがありません")

    with tab4:
        st.header("🧭 孤立記事")
        
        isolated = pages_df[pages_df['被リンク数'] == 0].copy()
        if not isolated.empty:
            st.warning(f"孤立記事が {len(isolated)} 件見つかりました")
            st.dataframe(isolated[['B_ページタイトル', 'C_URL']], use_container_width=True)
        else:
            st.success("孤立記事はありません")

    with tab5:
        st.header("📈 ネットワーク図")
        
        if HAS_PYVIS:
            with st.spinner("ネットワーク図を生成中..."):
                html_content = create_network_visualization(df, site_name, network_top_n)
                
                if html_content:
                    st.components.v1.html(html_content, height=820, scrolling=False)
                    st.success(f"ネットワーク図を表示しました（上位{network_top_n}件）")
                else:
                    st.error("ネットワーク図の生成に失敗しました")
        else:
            st.error("PyVisライブラリがインストールされていません")

if __name__ == "__main__":
    main()
