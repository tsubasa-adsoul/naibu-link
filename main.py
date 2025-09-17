#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
内部リンク構造分析ツール（CSV読込専用・完全版）
- ピラーページ / クラスター（アンカー） / 孤立記事を全件出力（HTML表 & 画面テキスト）
- ネットワーク図（静的：散布・短縮ラベル、インタラクティブ：pyvis）
- インタラクティブは上位ターゲット抽出＋エッジ集約＋軽量物理 → 速い
- 既定でブラウザ自動起動 OFF（画面のスイッチでONに切替可）
- ログは ./logs/ に保存、HTMLは ./reports/ と ./network_exports/ に保存
"""

import os
import sys
import csv
import math
import json
import webbrowser
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from collections import Counter
from datetime import datetime
from urllib.parse import urlparse

# ---------------- ログ ----------------
LOG_DIR = Path.cwd() / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"link_tool_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logger = logging.getLogger("link_tool")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    fh = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(ch)
    logger.addHandler(fh)

def install_global_exception_hooks(root=None):
    def excepthook(exctype, value, tb):
        logger.exception("UNCAUGHT", exc_info=(exctype, value, tb))
    sys.excepthook = excepthook
    if root is not None:
        def _tk_err(exc, val, tb):
            logger.exception("TK CALLBACK", exc_info=(exc, val, tb))
        root.report_callback_exception = _tk_err  # type: ignore

# ---------------- Matplotlib（日本語フォント） ----------------
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
for f in ['Yu Gothic', 'Meiryo', 'Noto Sans CJK JP', 'MS Gothic', 'DejaVu Sans']:
    try:
        plt.rcParams['font.family'] = f
        logger.info(f"Using font family: {f}")
        break
    except Exception:
        pass
plt.rcParams['axes.unicode_minus'] = False
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ---------------- GUI/Data ----------------
import customtkinter as ctk
import pandas as pd

# ---------------- PyVis（任意） ----------------
try:
    from pyvis.network import Network
    HAS_PYVIS = True
    logger.info("PyVis imported successfully")
except Exception as e:
    logger.warning(f"pyvis import failed: {e}")
    HAS_PYVIS = False
    Network = None

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

EXPECTED_COLUMNS = [
    'A_番号',
    'B_ページタイトル',
    'C_URL',
    'D_被リンク元ページタイトル',
    'E_被リンク元ページURL',
    'F_被リンク元ページアンカーテキスト'
]

def safe_str(s): return s if isinstance(s, str) else ""

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
    if netloc.startswith("www."): netloc = netloc[4:]
    path = p.path or "/"
    return urlunparse((scheme, netloc, path, p.params, p.query, ""))

class App:
    def __init__(self):
        self.root = ctk.CTk()
        install_global_exception_hooks(self.root)

        self.root.title("🔗 内部リンク構造分析ツール（CSV読込専用・完全版）")
        self.root.geometry("1400x900")

        self.df = None
        self.site_name = "Unknown Site"
        self.site_domain = None

        self.last_html = None
        self.auto_open = ctk.BooleanVar(value=False)  # ★ 既定で自動ブラウザOFF

        self._build_ui()

    def _build_ui(self):
        top = ctk.CTkFrame(self.root)
        top.pack(fill="x", padx=8, pady=8)

        ctk.CTkButton(top, text="📂 CSVを開く", command=self.load_csv).pack(side="left", padx=6)
        self.btn_pillar = ctk.CTkButton(top, text="🏛️ ピラーページ", command=self.do_pillar, state="disabled")
        self.btn_pillar.pack(side="left", padx=6)
        self.btn_cluster = ctk.CTkButton(top, text="🧩 クラスター", command=self.do_cluster, state="disabled")
        self.btn_cluster.pack(side="left", padx=6)
        self.btn_isolated = ctk.CTkButton(top, text="🧭 孤立記事", command=self.do_isolated, state="disabled")
        self.btn_isolated.pack(side="left", padx=6)
        self.btn_static = ctk.CTkButton(top, text="📈 ネットワーク（静的）", command=self.show_static_network, state="disabled")
        self.btn_static.pack(side="left", padx=6)
        self.btn_inter = ctk.CTkButton(top, text="🌐 ネットワーク（ブラウザ）", command=self.show_interactive_network, state="disabled")
        self.btn_inter.pack(side="left", padx=6)

        self.chk_open = ctk.CTkSwitch(top, text="自動でブラウザを開く", variable=self.auto_open)
        self.chk_open.pack(side="left", padx=12)

        ctk.CTkButton(top, text="🌐 最後のレポートを開く", command=self.open_last_html).pack(side="left", padx=6)
        ctk.CTkButton(top, text="📝 最後のレポートを別名保存", command=self.save_last_html).pack(side="left", padx=6)
        ctk.CTkButton(top, text="📜 ログフォルダ", command=self.open_logs).pack(side="left", padx=6)

        self.lbl_status = ctk.CTkLabel(top, text=f"ログ: {LOG_FILE.name}")
        self.lbl_status.pack(side="right", padx=8)

        main = ctk.CTkFrame(self.root)
        main.pack(fill="both", expand=True, padx=8, pady=4)

        left = ctk.CTkFrame(main, width=300)
        left.pack(side="left", fill="y", padx=6, pady=6)
        left.pack_propagate(False)
        self.lbl_file = ctk.CTkLabel(left, text="CSV未読込", anchor="w", justify="left")
        self.lbl_file.pack(fill="x", padx=8, pady=8)

        right = ctk.CTkFrame(main)
        right.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        self.txt = ctk.CTkTextbox(right, wrap="none")
        self.txt.pack(fill="both", expand=True)
        xbar = ctk.CTkScrollbar(right, orientation="horizontal", command=self.txt.xview)
        xbar.pack(side="bottom", fill="x")
        ybar = ctk.CTkScrollbar(right, orientation="vertical", command=self.txt.yview)
        ybar.pack(side="right", fill="y")
        self.txt.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)

    def _enable_analysis(self, on=True):
        for b in [self.btn_pillar, self.btn_cluster, self.btn_isolated, self.btn_static, self.btn_inter]:
            b.configure(state="normal" if on else "disabled")

    def _print(self, s: str, clear=False):
        if clear:
            self.txt.delete("1.0", "end")
        self.txt.insert("end", s)
        self.txt.see("end")

    def open_logs(self):
        try:
            if os.name == "nt": os.startfile(LOG_DIR)
            else: webbrowser.open(LOG_DIR.as_posix())
        except Exception:
            logger.exception("open_logs failed")

    # ------------ CSV ------------
    def load_csv(self):
        from tkinter import filedialog, messagebox
        path = filedialog.askopenfilename(
            title="CSVファイルを選択",
            filetypes=[("CSV files", "*.csv")],
            initialdir=os.getcwd()
        )
        if not path:
            return
        try:
            logger.info(f"Loading CSV: {path}")
            df = pd.read_csv(path, encoding="utf-8-sig").fillna("")
            if not all(col in df.columns for col in EXPECTED_COLUMNS):
                messagebox.showerror("エラー", f"CSV列が不足：\n必要: {EXPECTED_COLUMNS}\n実際: {list(df.columns)}")
                return
            self.df = df

            fname = os.path.basename(path)
            if   'kau-ru'       in fname: self.site_name = "カウール"
            elif 'kaitori-life' in fname: self.site_name = "買取LIFE"
            elif 'friendpay'    in fname: self.site_name = "フレンドペイ"
            elif 'kurekaeru' in fname or 'crecaeru' in fname: self.site_name = "クレかえる"
            else: self.site_name = "Unknown Site"

            domains = []
            for u in self.df['C_URL'].tolist():
                if isinstance(u, str) and u:
                    d = urlparse(u).netloc.lower()
                    if d.startswith("www."): d = d[4:]
                    if d: domains.append(d)
            self.site_domain = Counter(domains).most_common(1)[0][0] if domains else None

            def _norm(u): return normalize_url(u, base_domain=self.site_domain)
            self.df['C_URL'] = self.df['C_URL'].apply(_norm)
            self.df['E_被リンク元ページURL'] = self.df['E_被リンク元ページURL'].apply(_norm)

            self.lbl_file.configure(text=f"読込: {fname}（{len(self.df)}行）\nドメイン: {self.site_domain or '不明'}")
            self._enable_analysis(True)
            self._print(f"CSV読込完了: {fname}\nサイト: {self.site_name}\n\n", clear=True)
        except Exception as e:
            logger.exception("load_csv failed")
            from tkinter import messagebox
            messagebox.showerror("読み込みエラー", f"{e}")

    # ------------ 集計ユーティリティ ------------
    def _pages_set(self):
        if self.df is None:
            return pd.DataFrame(columns=['B_ページタイトル', 'C_URL']).drop_duplicates()
        return self.df[['B_ページタイトル', 'C_URL']].drop_duplicates()

    def _inbound_counts(self):
        if self.df is None:
            return pd.Series(dtype=int)
        has_src = (self.df['D_被リンク元ページタイトル'].astype(str) != "") & (self.df['E_被リンク元ページURL'].astype(str) != "")
        inbound = self.df[has_src & (self.df['C_URL'].astype(str) != "")]
        return inbound.groupby('C_URL').size()

    # ------------ HTML出力 ------------
    def _write_html_table(self, title: str, columns, rows, out_path: Path):
        out_path.parent.mkdir(exist_ok=True, parents=True)
        def esc(x):
            return (str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        html = [
            "<!doctype html><meta charset='utf-8'>",
            f"<title>{esc(title)}</title>",
            "<style>body{font-family: Arial, 'Yu Gothic', Meiryo, sans-serif; padding:16px;} table{border-collapse:collapse; width:100%;} th,td{border:1px solid #ddd; padding:6px; font-size:14px;} th{position:sticky;top:0;background:#f7f7f7;} tr:nth-child(even){background:#fafafa;} a{color:#1565c0; text-decoration:none;} a:hover{text-decoration:underline;}</style>",
            f"<h2>{esc(title)}</h2>",
            "<table><thead><tr>"
        ]
        for c in columns:
            html.append(f"<th>{esc(c)}</th>")
        html.append("</tr></thead><tbody>")
        for row in rows:
            html.append("<tr>")
            for i, cell in enumerate(row):
                val = esc(cell)
                header = columns[i]
                if "URL" in header.upper() or header.endswith("URL"):
                    if val and (val.startswith("http://") or val.startswith("https://")):
                        val = f"<a href='{val}' target='_blank' rel='noopener'>{val}</a>"
                html.append(f"<td>{val}</td>")
            html.append("</tr>")
        html.append("</tbody></table>")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("".join(html))
        return out_path

    def _maybe_open(self, path: Path):
        if not self.auto_open.get():
            return
        try:
            if os.name == "nt": os.startfile(path)
            else: webbrowser.open(path.as_posix())
        except Exception:
            webbrowser.open(path.as_posix())

    # ------------ ピラーページ ------------
    def do_pillar(self):
        if self.df is None: return
        self._print("▶ ピラーページ分析を開始…\n", clear=True)
        try:
            pages = self._pages_set().copy()
            inbound = self._inbound_counts()
            pages['被リンク数'] = pages['C_URL'].map(inbound).fillna(0).astype(int)
            pages.sort_values(['被リンク数','B_ページタイトル'], ascending=[False, True], inplace=True)

            lines = [f"[{i}] {safe_str(r['B_ページタイトル'])}  ({int(r['被リンク数'])})\n    {safe_str(r['C_URL'])}\n"
                     for i, (_, r) in enumerate(pages.iterrows(), 1)]
            self._print("".join(lines))

            out_dir = Path.cwd()/ "reports"
            out = out_dir / f"pillar_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            rows = [[i, safe_str(r['B_ページタイトル']), safe_str(r['C_URL']), int(r['被リンク数'])]
                    for i, (_, r) in enumerate(pages.iterrows(), 1)]
            self.last_html = self._write_html_table(f"{self.site_name} ピラーページ（全件）",
                                                    ["#", "ページタイトル", "URL", "被リンク数"],
                                                    rows, out)
            self._print(f"\nHTMLレポートを生成しました: {self.last_html}\n（自動オープン: { 'ON' if self.auto_open.get() else 'OFF' }）\n")
            self._maybe_open(self.last_html)
        except Exception as e:
            logger.exception("do_pillar failed")
            self._print(f"\n[エラー] {e}\n")

    # ------------ クラスター（アンカー） ------------
    def do_cluster(self):
        if self.df is None: return
        self._print("▶ クラスター（アンカーテキスト）分析を開始…\n", clear=True)
        try:
            anchors = self.df[(self.df['F_被リンク元ページアンカーテキスト'].astype(str) != "")]
            ac = Counter(anchors['F_被リンク元ページアンカーテキスト']) if len(anchors) else Counter()
            total = sum(ac.values())
            hhi = sum((c/total)**2 for c in ac.values()) if total else 0.0
            diversity = 1 - hhi
            self._print(f"ユニークアンカー: {len(ac)} / 多様性(1=高): {diversity:.3f}\n\n")
            for i, (a, c) in enumerate(ac.most_common(), 1):
                self._print(f"[{i}] {safe_str(a)}  ({c})\n")

            out_dir = Path.cwd()/ "reports"
            out = out_dir / f"anchors_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            rows = [[i, a, c] for i, (a, c) in enumerate(ac.most_common(), 1)]
            self.last_html = self._write_html_table(f"{self.site_name} アンカーテキスト頻度（全件）",
                                                    ["#", "アンカーテキスト", "回数"], rows, out)
            self._print(f"\nHTMLレポートを生成しました: {self.last_html}\n（自動オープン: { 'ON' if self.auto_open.get() else 'OFF' }）\n")
            self._maybe_open(self.last_html)
        except Exception as e:
            logger.exception("do_cluster failed")
            self._print(f"\n[エラー] {e}\n")

    # ------------ 孤立記事 ------------
    def do_isolated(self):
        if self.df is None: return
        self._print("▶ 孤立記事分析を開始…\n", clear=True)
        try:
            pages = self._pages_set().copy()
            inbound = self._inbound_counts()
            pages['被リンク数'] = pages['C_URL'].map(inbound).fillna(0).astype(int)
            isolated = pages[pages['被リンク数'] == 0].copy()
            isolated.sort_values('B_ページタイトル', inplace=True)

            if isolated.empty:
                self._print("孤立記事は 0 件でした。\n")
            else:
                self._print(f"孤立記事: {len(isolated)} 件\n\n")
                for i, (_, r) in enumerate(isolated.iterrows(), 1):
                    self._print(f"[{i}] {safe_str(r['B_ページタイトル'])}\n    {safe_str(r['C_URL'])}\n")

                out_dir = Path.cwd()/ "reports"
                out = out_dir / f"isolated_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                rows = [[i, safe_str(r['B_ページタイトル']), safe_str(r['C_URL'])]
                        for i, (_, r) in enumerate(isolated.iterrows(), 1)]
                self.last_html = self._write_html_table(f"{self.site_name} 孤立記事（全件）",
                                                        ["#", "ページタイトル", "URL"], rows, out)
                self._print(f"\nHTMLレポートを生成しました: {self.last_html}\n（自動オープン: { 'ON' if self.auto_open.get() else 'OFF' }）\n")
                self._maybe_open(self.last_html)
        except Exception as e:
            logger.exception("do_isolated failed")
            self._print(f"\n[エラー] {e}\n")

    # ------------ 静的ネットワーク（別ウィンドウ） ------------
    def show_static_network(self):
        if self.df is None: return
        try:
            import tkinter as tk
            pages = self._pages_set().copy()
            inbound = self._inbound_counts()
            pages['被リンク数'] = pages['C_URL'].map(inbound).fillna(0).astype(int)
            pages.sort_values('被リンク数', ascending=False, inplace=True)
            top = pages.head(20)

            win = tk.Toplevel(self.root)
            win.title("ネットワーク簡易図（散布・静的）")
            win.geometry("980x720")

            fig, ax = plt.subplots(figsize=(9.8, 7.2))
            xs = list(range(len(top)))
            ys = top['被リンク数'].tolist()
            sizes = [max(80, v*28) for v in ys]
            ax.scatter(xs, ys, s=sizes, alpha=0.75)

            def short(s, n=24):
                s = safe_str(s)
                return (s[:n] + "…") if len(s) > n else s

            for i, (_, r) in enumerate(top.iterrows()):
                ax.annotate(
                    short(r['B_ページタイトル']),
                    (xs[i], ys[i]),
                    xytext=(0, 12), textcoords="offset points",
                    ha='center', va='bottom', fontsize=9, clip_on=True,
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="0.8", alpha=0.85)
                )

            ax.set_title('被リンク上位（散布図・短縮ラベル）')
            ax.set_xlabel('ページ（上位順）'); ax.set_ylabel('被リンク数')
            ax.grid(True, alpha=0.25); fig.tight_layout()

            canv = FigureCanvasTkAgg(fig, master=win)
            canv.draw()
            canv.get_tk_widget().pack(fill="both", expand=True)
        except Exception as e:
            logger.exception("show_static_network failed")
            self._print(f"\n[描画エラー] {e}\n")

    # ------------ インタラクティブ（pyvis） ★修正部分 ------------
    def show_interactive_network(self):
        from tkinter import messagebox
        if self.df is None:
            messagebox.showerror("エラー", "CSVを読み込んでください。")
            return
        if not HAS_PYVIS:
            messagebox.showerror("エラー", "pyvis が見つかりません。`pip install pyvis` を実行してください。")
            return
        try:
            self._print("▶ インタラクティブネットワークを生成中…\n", clear=True)
            
            edges_df = self.df[
                (self.df['E_被リンク元ページURL'].astype(str) != "") &
                (self.df['C_URL'].astype(str) != "")
            ][['D_被リンク元ページタイトル', 'E_被リンク元ページURL',
               'B_ページタイトル', 'C_URL']].copy()

            def in_site(u: str) -> bool:
                try:
                    d = urlparse(u).netloc.lower()
                    if d.startswith("www."): d = d[4:]
                    return (not self.site_domain) or (d == self.site_domain) or d.endswith("." + self.site_domain)
                except Exception:
                    return True
            edges_df = edges_df[edges_df['E_被リンク元ページURL'].apply(in_site) & edges_df['C_URL'].apply(in_site)]
            if edges_df.empty:
                messagebox.showinfo("情報", "描画対象エッジがありません。")
                return

            in_counts = edges_df.groupby('C_URL').size().sort_values(ascending=False)

            TOP_N = 40  # 重い場合は 30 などに下げてOK
            top_targets = set(in_counts.head(TOP_N).index)

            sub = edges_df[edges_df['C_URL'].isin(top_targets)].copy()

            agg = sub.groupby(['E_被リンク元ページURL', 'C_URL']).size().reset_index(name='weight')

            url2title = {}
            for _, r in self.df[['B_ページタイトル','C_URL']].drop_duplicates().iterrows():
                if r['C_URL']:
                    url2title[r['C_URL']] = r['B_ページタイトル']
            for _, r in self.df[['D_被リンク元ページタイトル','E_被リンク元ページURL']].drop_duplicates().iterrows():
                if r['E_被リンク元ページURL']:
                    url2title.setdefault(r['E_被リンク元ページURL'], r['D_被リンク元ページタイトル'])

            def short_label(u: str, n=24) -> str:
                t = str(url2title.get(u, u))
                return (t[:n] + "…") if len(t) > n else t

            # PyVisネットワークの作成 - ここが修正部分
            net = Network(
                height="800px", 
                width="100%", 
                directed=True, 
                bgcolor="#ffffff",
                font_color="black"
            )
            
            # 物理エンジンの設定
            net.barnes_hut(
                gravity=-8000,
                central_gravity=0.3,
                spring_length=160,
                spring_strength=0.03,
                damping=0.12,
                overlap=0.1
            )

            nodes = set(agg['E_被リンク元ページURL']).union(set(agg['C_URL']))
            
            def node_size(u: str) -> int:
                s = int(in_counts.get(u, 0))
                return max(12, min(48, int(12 + math.log2(s + 1) * 8)))

            # ノードを追加
            for u in nodes:
                net.add_node(
                    u,
                    label=short_label(u),
                    title=f"{url2title.get(u, u)}<br>{u}",
                    size=node_size(u)
                )

            # エッジを追加
            for _, r in agg.iterrows():
                src = r['E_被リンク元ページURL']
                dst = r['C_URL']
                w   = int(r['weight'])
                net.add_edge(src, dst, width=min(w, 8))  # width制限で視認性向上

            # ファイルパスの設定
            out_dir = Path.cwd()/"network_exports"
            out_dir.mkdir(exist_ok=True)
            out_html = out_dir / f"interactive_network_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"

            # HTMLファイルの生成 - 修正版
            try:
                # save_graphの代わりにwriteメソッドを使用
                net.save_graph(str(out_html))
                logger.info(f"Network graph saved to: {out_html}")
                
                # 自動オープンの処理
                if self.auto_open.get():
                    self._maybe_open(out_html)
                
                self.last_html = out_html
                
                self._print(
                    f"\nインタラクティブネットワークを生成しました: {out_html}\n"
                    f"（ノード={len(nodes)} / エッジ={len(agg)} / 上位ターゲット={len(top_targets)} / "
                    f"自動オープン: {'ON' if self.auto_open.get() else 'OFF'}）\n"
                    "※ 重いと感じたら TOP_N を 30 などに下げてください。\n"
                    "※ さらに軽くするには weight=1 のエッジを除外する等の調整も有効です。\n"
                )
                
            except Exception as pyvis_error:
                logger.exception("PyVis network generation failed")
                
                # フォールバック: 簡単なHTMLテーブル形式で出力
                self._print(f"\nPyVis描画に失敗しました。フォールバック表示を生成します。\nエラー: {pyvis_error}\n")
                
                rank = in_counts.head(TOP_N).items()
                fallback_html = [
                    "<!doctype html><meta charset='utf-8'>",
                    f"<title>Network Analysis - {self.site_name} (fallback)</title>",
                    "<style>body{font-family: Arial, 'Yu Gothic', Meiryo, sans-serif; padding:16px;} table{border-collapse:collapse; width:100%;} th,td{border:1px solid #ddd; padding:8px;} th{background:#f7f7f7;} a{color:#1565c0; text-decoration:none;} a:hover{text-decoration:underline;}</style>",
                    f"<h2>ネットワーク分析結果 - {self.site_name}</h2>",
                    "<p>PyVis描画に失敗したため、上位ページの一覧を表示しています。</p>",
                    "<table><thead><tr><th>順位</th><th>ページタイトル</th><th>URL</th><th>被リンク数</th></tr></thead><tbody>"
                ]
                
                for i, (url, count) in enumerate(rank, 1):
                    title = url2title.get(url, url)
                    title_escaped = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    fallback_html.append(
                        f"<tr><td>{i}</td><td>{title_escaped}</td>"
                        f"<td><a href='{url}' target='_blank' rel='noopener'>{url}</a></td>"
                        f"<td>{count}</td></tr>"
                    )
                
                fallback_html.append("</tbody></table>")
                
                with open(out_html, "w", encoding="utf-8") as f:
                    f.write("\n".join(fallback_html))
                
                self.last_html = out_html
                self._print(f"\nフォールバック表示を生成しました: {out_html}\n")
                self._maybe_open(out_html)

        except Exception as e:
            logger.exception("show_interactive_network failed")
            messagebox.showerror("描画エラー", f"ネットワーク図の生成に失敗しました:\n{e}")
            self._print(f"\n[致命的エラー] {e}\n")

    # ------------ 直近HTMLを開く/保存 ------------
    def open_last_html(self):
        from tkinter import messagebox
        if not self.last_html or not Path(self.last_html).exists():
            messagebox.showinfo("情報", "直近のHTMLレポートがありません。先に分析を実行してください。")
            return
        try:
            if os.name == "nt": os.startfile(self.last_html)
            else: webbrowser.open(Path(self.last_html).as_posix())
        except Exception:
            webbrowser.open(Path(self.last_html).as_posix())

    def save_last_html(self):
        from tkinter import filedialog, messagebox
        if not self.last_html or not Path(self.last_html).exists():
            messagebox.showinfo("情報", "直近のHTMLレポートがありません。先に分析を実行してください。")
            return
        try:
            dest = filedialog.asksaveasfilename(defaultextension=".html",
                                                filetypes=[("HTML files","*.html")],
                                                initialfile=os.path.basename(self.last_html))
            if not dest: return
            with open(self.last_html, "r", encoding="utf-8") as f: content = f.read()
            with open(dest, "w", encoding="utf-8") as f: f.write(content)
            messagebox.showinfo("保存", f"保存しました: {dest}")
        except Exception:
            logger.exception("save_last_html failed")

    # ------------ Run ------------
    def run(self):
        self.root.mainloop()

def main():
    app = App()
    app.run()

if __name__ == "__main__":
    main()
