import streamlit as st
import requests
import json
from datetime import datetime
import pandas as pd
from urllib.parse import urlparse
import time

# 各サイトの設定情報
ANALYZER_CONFIGS = {
    "answer-genkinka.jp": {
        "name": "Answer現金化",
        "url": "https://answer-genkinka.jp/blog/",
        "status": "active",
        "last_analysis": None,
        "description": "現金化サービス専門サイト",
        "features": ["ブログ記事分析", "全自動CSV出力"],
        "streamlit_url": "https://answer-analyzer.streamlit.app",  # 後で設定
        "color": "#FF6B6B"
    },
    "arigataya.co.jp": {
        "name": "ありがたや", 
        "url": "https://arigataya.co.jp",
        "status": "planned",
        "last_analysis": None,
        "description": "onclick対応・全自動版",
        "features": ["onclick対応", "自動リンク検出"],
        "streamlit_url": None,
        "color": "#4ECDC4"
    },
    "kau-ru.co.jp": {
        "name": "カウール",
        "url": "https://kau-ru.co.jp", 
        "status": "planned",
        "last_analysis": None,
        "description": "複数サイト対応版",
        "features": ["WordPress API", "添付ファイル除外"],
        "streamlit_url": None,
        "color": "#45B7D1"
    },
    "crecaeru.co.jp": {
        "name": "クレかえる",
        "url": "https://crecaeru.co.jp",
        "status": "planned", 
        "last_analysis": None,
        "description": "gnav除外対応・onclick対応版",
        "features": ["gnav除外", "onclick対応"],
        "streamlit_url": None,
        "color": "#96CEB4"
    },
    "friendpay.jp": {
        "name": "フレンドペイ",
        "url": "https://friendpay.jp",
        "status": "planned",
        "last_analysis": None, 
        "description": "サイト別除外セレクター対応",
        "features": ["サイト別除外", "最適化分析"],
        "streamlit_url": None,
        "color": "#FFEAA7"
    },
    "kaitori-life.co.jp": {
        "name": "買取LIFE",
        "url": "https://kaitori-life.co.jp",
        "status": "planned",
        "last_analysis": None,
        "description": "JINテーマ専用最適化",
        "features": ["JINテーマ対応", "専用セレクター"],
        "streamlit_url": None,
        "color": "#FD79A8"
    },
    "wallet-sos.jp": {
        "name": "ウォレットSOS",
        "url": "https://wallet-sos.jp",
        "status": "planned",
        "last_analysis": None,
        "description": "Selenium版（Cloudflare対策）",
        "features": ["Selenium対応", "Cloudflare対策"],
        "streamlit_url": None,
        "color": "#A29BFE"
    },
    "wonderwall-invest.co.jp": {
        "name": "ワンダーウォール",
        "url": "https://wonderwall-invest.co.jp",
        "status": "planned",
        "last_analysis": None,
        "description": "secure-technology専用",
        "features": ["専用最適化", "高精度分析"],
        "streamlit_url": None,
        "color": "#6C5CE7"
    },
    "fuyohin-kaishu.co.jp": {
        "name": "不用品回収",
        "url": "https://fuyohin-kaishu.co.jp",
        "status": "planned",
        "last_analysis": None,
        "description": "カテゴリ別分析・修正版",
        "features": ["カテゴリ別分析", "包括的収集"],
        "streamlit_url": None,
        "color": "#00B894"
    },
    "bic-gift.co.jp": {
        "name": "ビックギフト",
        "url": "https://bic-gift.co.jp",
        "status": "planned",
        "last_analysis": None,
        "description": "SANGOテーマ専用・全自動版",
        "features": ["SANGOテーマ対応", "専用抽出"],
        "streamlit_url": None,
        "color": "#E17055"
    },
    "flashpay.jp/famipay": {
        "name": "ファミペイ",
        "url": "https://flashpay.jp/famipay/",
        "status": "planned",
        "last_analysis": None,
        "description": "/famipay/配下専用",
        "features": ["配下限定分析", "高精度抽出"],
        "streamlit_url": None,
        "color": "#00CEC9"
    },
    "flashpay.jp/media": {
        "name": "フラッシュペイ",
        "url": "https://flashpay.jp/media/",
        "status": "planned",
        "last_analysis": None,
        "description": "/media/配下専用",
        "features": ["メディア特化", "効率分析"],
        "streamlit_url": None,
        "color": "#74B9FF"
    },
    "more-pay.jp": {
        "name": "モアペイ",
        "url": "https://more-pay.jp",
        "status": "planned",
        "last_analysis": None,
        "description": "改善版・包括的分析",
        "features": ["包括分析", "改善版エンジン"],
        "streamlit_url": None,
        "color": "#FD79A8"
    },
    "pay-ful.jp": {
        "name": "ペイフル",
        "url": "https://pay-ful.jp/media/",
        "status": "planned", 
        "last_analysis": None,
        "description": "個別記事ページ重視",
        "features": ["記事重視", "精密分析"],
        "streamlit_url": None,
        "color": "#FDCB6E"
    },
    "smart-pay.website": {
        "name": "スマートペイ",
        "url": "https://smart-pay.website/media/",
        "status": "planned",
        "last_analysis": None,
        "description": "大規模サイト対応",
        "features": ["大規模対応", "効率化エンジン"],
        "streamlit_url": None,
        "color": "#E84393"
    },
    "xgift.jp": {
        "name": "エックスギフト",
        "url": "https://xgift.jp/blog/",
        "status": "planned",
        "last_analysis": None,
        "description": "AFFINGER対応",
        "features": ["AFFINGER対応", "テーマ最適化"],
        "streamlit_url": None,
        "color": "#00B894"
    }
}

def main():
    st.set_page_config(
        page_title="内部リンク分析 統括管理システム",
        page_icon="🎛️",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # ヘッダー
    st.title("🎛️ 内部リンク分析 統括管理システム")
    st.markdown("**16サイト対応 - 一元管理ダッシュボード**")
    
    # サイドバー - メニュー
    with st.sidebar:
        st.header("📋 メニュー")
        menu = st.radio(
            "機能を選択",
            ["🏠 ダッシュボード", "🔗 個別分析", "📊 統計・比較", "⚙️ 設定管理"],
            index=0
        )
        
        st.divider()
        st.markdown("**📈 システム状況**")
        active_count = sum(1 for config in ANALYZER_CONFIGS.values() if config['status'] == 'active')
        st.metric("稼働中", f"{active_count}/16サイト")
        
        st.divider()
        st.markdown("**🕐 最終更新**")
        st.text(datetime.now().strftime("%Y-%m-%d %H:%M"))
    
    # メイン画面
    if menu == "🏠 ダッシュボード":
        show_dashboard()
    elif menu == "🔗 個別分析":
        show_individual_analysis()
    elif menu == "📊 統計・比較":
        show_statistics()
    elif menu == "⚙️ 設定管理":
        show_settings()

def show_dashboard():
    """ダッシュボード表示"""
    st.header("📊 システム全体概要")
    
    # 統計情報
    col1, col2, col3, col4 = st.columns(4)
    
    active_sites = [k for k, v in ANALYZER_CONFIGS.items() if v['status'] == 'active']
    planned_sites = [k for k, v in ANALYZER_CONFIGS.items() if v['status'] == 'planned']
    
    with col1:
        st.metric("総サイト数", len(ANALYZER_CONFIGS), delta="16サイト")
    with col2:
        st.metric("稼働中", len(active_sites), delta=f"+{len(active_sites)}")
    with col3:
        st.metric("準備中", len(planned_sites), delta=f"{len(planned_sites)}サイト")
    with col4:
        st.metric("本日の分析", 0, delta="0回")
    
    st.divider()
    
    # サイト一覧カード表示
    st.subheader("🔗 分析対象サイト一覧")
    
    # 3列レイアウトでカード表示
    cols = st.columns(3)
    
    for i, (site_key, config) in enumerate(ANALYZER_CONFIGS.items()):
        col_idx = i % 3
        
        with cols[col_idx]:
            # ステータスに応じた色分け
            if config['status'] == 'active':
                status_color = "🟢"
                status_text = "稼働中"
            elif config['status'] == 'planned':
                status_color = "🟡" 
                status_text = "準備中"
            else:
                status_color = "🔴"
                status_text = "停止中"
            
            with st.container():
                st.markdown(f"""
                <div style="
                    border: 2px solid {config['color']};
                    border-radius: 10px;
                    padding: 15px;
                    margin: 10px 0;
                    background: linear-gradient(135deg, {config['color']}15, {config['color']}05);
                ">
                    <h4 style="color: {config['color']}; margin: 0 0 10px 0;">
                        {status_color} {config['name']}
                    </h4>
                    <p style="margin: 5px 0; font-size: 0.9em;">
                        <strong>URL:</strong> {config['url'][:30]}...
                    </p>
                    <p style="margin: 5px 0; font-size: 0.9em;">
                        <strong>ステータス:</strong> {status_text}
                    </p>
                    <p style="margin: 5px 0; font-size: 0.8em; color: #666;">
                        {config['description']}
                    </p>
                </div>
                """, unsafe_allow_html=True)
                
                # アクションボタン
                if config['status'] == 'active' and config.get('streamlit_url'):
                    if st.button(f"🚀 {config['name']} 分析実行", key=f"analyze_{site_key}"):
                        st.success(f"{config['name']} の分析を開始します...")
                        st.balloons()
                else:
                    st.button(f"⏳ 準備中", disabled=True, key=f"disabled_{site_key}")

def show_individual_analysis():
    """個別分析画面"""
    st.header("🔗 個別サイト分析")
    
    # サイト選択
    col1, col2 = st.columns([2, 1])
    
    with col1:
        selected_site = st.selectbox(
            "分析対象サイトを選択",
            options=list(ANALYZER_CONFIGS.keys()),
            format_func=lambda x: f"{ANALYZER_CONFIGS[x]['name']} ({x})"
        )
    
    with col2:
        st.markdown("**選択サイト情報**")
        config = ANALYZER_CONFIGS[selected_site]
        st.info(f"""
        **名称:** {config['name']}  
        **URL:** {config['url']}  
        **ステータス:** {config['status']}  
        **説明:** {config['description']}
        """)
    
    # 機能説明
    st.subheader(f"🎯 {config['name']} の専用機能")
    
    feature_cols = st.columns(len(config['features']))
    for i, feature in enumerate(config['features']):
        with feature_cols[i]:
            st.markdown(f"""
            <div style="
                background: {config['color']}20;
                border: 1px solid {config['color']};
                border-radius: 5px;
                padding: 10px;
                text-align: center;
                margin: 5px;
            ">
                <strong>{feature}</strong>
            </div>
            """, unsafe_allow_html=True)
    
    st.divider()
    
    # 分析実行セクション
    st.subheader("🚀 分析実行")
    
    if config['status'] == 'active':
        url_input = st.text_input(
            "分析URL（カスタマイズ可能）",
            value=config['url'],
            help="デフォルトURL以外も分析可能です"
        )
        
        col1, col2, col3 = st.columns([2, 1, 1])
        
        with col1:
            if st.button(f"🔍 {config['name']} 分析開始", type="primary"):
                # 実際の分析処理
                with st.spinner(f"{config['name']} を分析中..."):
                    time.sleep(2)  # デモ用
                    
                st.success("✅ 分析完了！")
                show_demo_results(config['name'])
        
        with col2:
            if st.button("📊 履歴表示"):
                st.info("分析履歴機能は準備中です")
        
        with col3:
            if st.button("⚙️ 設定"):
                st.info("個別設定機能は準備中です")
    
    else:
        st.warning(f"{config['name']} はまだ準備中です。Streamlit版への移行作業を進めています。")
        
        st.markdown("**移行状況:**")
        progress = st.progress(0)
        st.text("CustomTkinter → Streamlit 変換作業中...")

def show_demo_results(site_name):
    """デモ用結果表示（plotly不使用版）"""
    st.subheader(f"📊 {site_name} 分析結果")
    
    # ダミー統計
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("総ページ数", "127", delta="12")
    with col2:
        st.metric("内部リンク数", "342", delta="45")
    with col3:
        st.metric("孤立ページ", "23", delta="-5")
    with col4:
        st.metric("人気ページ", "18", delta="3")
    
    # Streamlit標準のチャート機能を使用
    import numpy as np
    chart_data = pd.DataFrame({
        'ページ': [f'ページ{i}' for i in range(1, 11)],
        '被リンク数': np.random.randint(1, 20, 10)
    })
    
    st.subheader("被リンク数ランキング（上位10件）")
    st.bar_chart(chart_data.set_index('ページ'))
    
    # 詳細テーブル表示
    st.subheader("詳細データ")
    sample_data = pd.DataFrame({
        'ページタイトル': [f'サンプル記事{i}' for i in range(1, 6)],
        'URL': [f'https://example.com/article{i}' for i in range(1, 6)],
        '被リンク数': np.random.randint(1, 15, 5),
        '発リンク数': np.random.randint(2, 8, 5)
    })
    st.dataframe(sample_data, use_container_width=True)
    
    # CSVダウンロード
    csv_data = sample_data.to_csv(index=False)
    st.download_button(
        "📥 CSVダウンロード",
        csv_data,
        f"{site_name}-{datetime.now().strftime('%Y%m%d')}.csv",
        "text/csv"
    )

def show_statistics():
    """統計・比較画面"""
    st.header("📊 統計・比較分析")
    
    st.info("統計・比較機能は各サイトのStreamlit化完了後に実装予定です")
    
    # 将来の機能プレビュー
    st.subheader("🔮 実装予定機能")
    
    features = [
        "📈 全サイト横断統計",
        "🔄 サイト間比較分析", 
        "📅 時系列トレンド",
        "🎯 SEO改善提案",
        "📊 統合レポート生成",
        "⚡ リアルタイム監視"
    ]
    
    cols = st.columns(2)
    for i, feature in enumerate(features):
        with cols[i % 2]:
            st.markdown(f"- {feature}")

def show_settings():
    """設定管理画面"""
    st.header("⚙️ 設定管理")
    
    st.subheader("🔧 システム設定")
    
    # 全般設定
    with st.expander("全般設定", expanded=True):
        auto_analysis = st.checkbox("自動分析を有効化", value=False)
        analysis_interval = st.selectbox("分析間隔", ["1時間", "6時間", "12時間", "24時間"])
        max_concurrent = st.slider("同時実行数", 1, 5, 2)
    
    # 通知設定
    with st.expander("通知設定"):
        email_notify = st.checkbox("メール通知", value=False)
        slack_notify = st.checkbox("Slack通知", value=False)
        if email_notify:
            email = st.text_input("通知先メールアドレス")
        if slack_notify:
            webhook = st.text_input("Slack Webhook URL")
    
    # サイト別設定
    with st.expander("サイト別設定"):
        for site_key, config in ANALYZER_CONFIGS.items():
            st.markdown(f"**{config['name']} ({site_key})**")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                enabled = st.checkbox("有効", value=config['status']=='active', key=f"enable_{site_key}")
            with col2:
                priority = st.selectbox("優先度", ["高", "中", "低"], key=f"priority_{site_key}")
            with col3:
                timeout = st.number_input("タイムアウト(秒)", 10, 300, 60, key=f"timeout_{site_key}")
            
            st.divider()
    
    # 保存ボタン
    if st.button("💾 設定を保存", type="primary"):
        st.success("設定を保存しました！")
        st.balloons()

if __name__ == "__main__":
    main()
