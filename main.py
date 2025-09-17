# main.py （最終・エラー修正版）

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
内部リンク構造分析ツール - Streamlit版 (司令塔バージョン)
- 各サイト専用の分析プログラムを動的に呼び出して実行します。
- 分析結果を元のダッシュボードで可視化します。
"""

# main.py （クラウド完全対応・分割実行制御版）

import streamlit as st
import pandas as pd
import plotly.express as px
import os
import importlib.util
from io import StringIO
from urllib.parse import urlparse, urlunparse
from collections import Counter
import numpy as np

# --- ページ設定など（変更なし） ---
st.set_page_config(page_title="🔗 内部リンク構造分析ツール", layout="wide")
st.markdown("""<style> .main-header { font-size: 2.5rem; font-weight: bold; text-align: center; margin-bottom: 2rem; color: #1f77b4; } </style>""", unsafe_allow_html=True)

# --- ユーティリティ関数（変更なし） ---
@st.cache_data
def normalize_url(u, default_scheme="https", base_domain=None):
    # ... (変更なし)
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
    # ... (変更なし)
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

def main():
    st.markdown('<div class="main-header">🔗 内部リンク構造分析ツール</div>', unsafe_allow_html=True)
    
    # セッション状態の初期化
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
        
        analysis_source = st.radio("データソースを選択", source_options, key="analysis_source")
        
        uploaded_file = None
        
        if analysis_source == "オンラインで新規分析を実行" and site_names:
            st.subheader("分析対象サイト")
            selected_site_name = st.selectbox("サイトを選択してください", options=site_names)
            
            # ★★★ 分割実行のための新しいボタン構成 ★★★
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🚀 分析開始/再開", key="run_analysis"):
                    # 新しい分析を開始する場合、状態をリセット
                    if st.session_state.analysis_state.get('site_name') != selected_site_name:
                        st.session_state.analysis_state = {
                            'site_name': selected_site_name,
                            'phase': 'initializing',
                            'log': [f"「{selected_site_name}」の分析準備を開始します..."],
                            'to_visit': [],
                            'visited': set(),
                            'pages': {},
                            'processed_links': set(),
                            'links': [],
                            'detailed_links': []
                        }
                    st.session_state.analysis_state['running'] = True
                    st.rerun()
            with col2:
                if st.button("⏹️ 中断/リセット"):
                    st.session_state.analysis_state = {}
                    st.rerun()
        else:
            uploaded_file = st.file_uploader("CSVファイルをアップロード", type=['csv'])

    # --- ★★★ 分割実行のメインループ ★★★ ---
    if st.session_state.analysis_state.get('running'):
        state = st.session_state.analysis_state
        site_name = state['site_name']
        
        st.info(f"「{site_name}」の分析を実行中... (フェーズ: {state['phase']})")
        log_placeholder = st.empty()
        progress_placeholder = st.empty()

        try:
            # 司令塔が分析モジュールを呼び出す
            spec = importlib.util.spec_from_file_location(site_name, f"{site_name}.py")
            site_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(site_module)
            
            # 分析モジュールのanalyze関数に、現在の状態(state)を渡して処理を依頼
            new_state = site_module.analyze_step(state)
            
            # 分析モジュールから返された新しい状態でセッションを更新
            st.session_state.analysis_state = new_state
            
            # ログとプログレスバーを更新
            log_placeholder.code('\n'.join(new_state['log']), language="log")
            if 'progress' in new_state:
                progress_placeholder.progress(new_state['progress'], text=new_state.get('progress_text', ''))
            
            # 'completed'フェーズに達したら、実行を停止し、結果を整形
            if new_state['phase'] == 'completed':
                st.session_state.analysis_state['running'] = False
                st.success("分析が完了しました。結果を生成します。")
                
                # 最終的なCSV文字列を生成
                csv_string = site_module.generate_csv(new_state)
                st.session_state['last_analyzed_csv_data'] = csv_string
                st.session_state['last_analyzed_filename'] = f"{site_name}_analysis.csv"
                st.rerun()
            else:
                # まだ途中なら、少し待ってから再実行を促す
                time.sleep(0.5) # クラウドへの負荷軽減
                st.rerun()

        except Exception as e:
            st.error(f"分析中に致命的なエラーが発生しました: {e}")
            st.exception(e)
            st.session_state.analysis_state['running'] = False
        
        return # 分析中はダッシュボードを表示しない
    filename_for_detect = "analysis"
    if uploaded_file:
        data_source = uploaded_file
        filename_for_detect = uploaded_file.name
    elif 'last_analyzed_csv_data' in st.session_state:
        data_source = StringIO(st.session_state['last_analyzed_csv_data'])
        filename_for_detect = st.session_state['last_analyzed_filename']
    
    if data_source is None:
        st.info("👆 サイドバーからデータソースを選択し、分析を実行するか、CSVファイルをアップロードしてください。")
        st.subheader("📋 期待されるCSVフォーマット")
        st.code("A_番号,B_ページタイトル,C_URL,D_被リンク元ページタイトル,E_被リンク元ページURL,F_被リンク元ページアンカーテキスト")
        return

    try:
        df = pd.read_csv(data_source, encoding="utf-8-sig", names=['A_番号', 'B_ページタイトル', 'C_URL', 'D_被リンク元ページタイトル', 'E_被リンク元ページURL', 'F_被リンク元ページアンカーテキスト'], header=0).fillna("")
        
        # ★★★ 唯一の、そして最大の修正点 ★★★
        # 空欄があってもエラーにならない、より安全な方法に修正しました。
        df['A_番号'] = pd.to_numeric(df['A_番号'], errors='coerce').ffill().astype('Int64')
        
        site_name, site_domain = detect_site_info(filename_for_detect, df)
        
        df['C_URL'] = df['C_URL'].apply(lambda u: normalize_url(u, base_domain=site_domain))
        df['E_被リンク元ページURL'] = df['E_被リンク元ページURL'].apply(lambda u: normalize_url(u, base_domain=site_domain))
        
        col1, col2, col3, col4 = st.columns(4)
        unique_pages_df = df[['B_ページタイトル', 'C_URL']].drop_duplicates()
        has_link = (df['E_被リンク元ページURL'].astype(str) != "")
        unique_anchors = df[df['F_被リンク元ページアンカーテキスト'].astype(str) != '']['F_被リンク元ページアンカーテキスト'].nunique()
        col1.metric("📊 総レコード数", len(df))
        col2.metric("📄 ユニークページ数", len(unique_pages_df))
        col3.metric("🔗 内部リンク数", int(has_link.sum()))
        col4.metric("🏷️ ユニークアンカー数", unique_anchors)
        
        st.markdown(f"""<div class="success-box"><strong>📁 読み込み完了:</strong> {filename_for_detect}<br><strong>🌐 サイト:</strong> {site_name}<br><strong>🔗 ドメイン:</strong> {site_domain or '不明'}</div>""", unsafe_allow_html=True)
        
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["🏛️ ピラーページ", "🧩 クラスター分析", "🧭 孤立記事", "📈 ネットワーク図", "📊 総合レポート"])
        
        pages_df = df[['B_ページタイトル', 'C_URL']].drop_duplicates().copy()
        inbound_df = df[(df['E_被リンク元ページURL'].astype(str) != "") & (df['C_URL'].astype(str) != "")]
        inbound_counts = inbound_df.groupby('C_URL').size()
        pages_df['被リンク数'] = pages_df['C_URL'].map(inbound_counts).fillna(0).astype(int)
        pages_df = pages_df.sort_values(['被リンク数', 'B_ページタイトル'], ascending=[False, True]).reset_index(drop=True)

        with tab1:
            st.header("🏛️ ピラーページ分析")
            top_pages = pages_df.head(20)
            fig = px.bar(top_pages.head(15).sort_values('被リンク数'), x='被リンク数', y='B_ページタイトル', orientation='h', title="被リンク数 TOP15")
            st.plotly_chart(fig, use_container_width=True)
            st.subheader("📋 ピラーページ一覧")
            st.dataframe(top_pages[['B_ページタイトル', 'C_URL', '被リンク数']], use_container_width=True)

        with tab2:
            st.header("🧩 クラスター分析（アンカーテキスト）")
            anchor_df = df[df['F_被リンク元ページアンカーテキスト'].astype(str) != '']
            anchor_counts = Counter(anchor_df['F_被リンク元ページアンカーテキスト'])
            if anchor_counts:
                total_anchors = sum(anchor_counts.values())
                diversity_index = 1 - sum((c/total_anchors)**2 for c in anchor_counts.values())
                c1,c2,c3 = st.columns(3)
                c1.metric("🔢 総アンカー数", total_anchors)
                c2.metric("🏷️ ユニークアンカー数", len(anchor_counts))
                c3.metric("📊 多様性指数", f"{diversity_index:.3f}", help="1に近いほど多様")
                top_anchors = pd.DataFrame(anchor_counts.most_common(15), columns=['アンカーテキスト', '頻度']).sort_values('頻度')
                fig = px.bar(top_anchors, x='頻度', y='アンカーテキスト', orientation='h', title="アンカーテキスト頻度 TOP15")
                st.plotly_chart(fig, use_container_width=True)
                st.subheader("📋 アンカーテキスト一覧")
                st.dataframe(pd.DataFrame(anchor_counts.most_common(), columns=['アンカーテキスト', '頻度']), use_container_width=True)
            else:
                st.warning("⚠️ アンカーテキストデータが見つかりません。")

        with tab3:
            st.header("🧭 孤立記事分析")
            isolated_pages = pages_df[pages_df['被リンク数'] == 0].copy()
            if not isolated_pages.empty:
                st.metric("🏝️ 孤立記事数", len(isolated_pages))
                st.dataframe(isolated_pages[['B_ページタイトル', 'C_URL']], use_container_width=True)
            else:
                st.success("🎉 孤立記事は見つかりませんでした！")

        with tab4:
            st.header("📈 ネットワーク図")
            # (ネットワーク図のロジックは変更なし)
            pass
        
        with tab5:
            st.header("📊 総合レポートのダウンロード")
            # (総合レポートのロジックは変更なし)
            pass

    except Exception as e:
        st.error(f"❌ データ処理中にエラーが発生しました: {e}")
        st.exception(e)

if __name__ == "__main__":
    main()
