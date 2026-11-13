# -*- coding: utf-8 -*-
"""
基金走势分析 · 图形界面
======================
用 funds.json 作为唯一权威源管理自选基金（不再使用 txt 名单）：
  - UI 里增 / 删 / 改分类 → 写回 funds.json；
  - 你也可以直接编辑 funds.json 手动增删基金，下次打开或点「刷新名称」自动生效。

功能：
  - 按基金代码添加（自动联网查名称与类型）、删除、分类
  - 分类标签可“改名 / 新增 / 删除空标签”（🏷 管理分类）；选中基金可“转移到其它分类”（🔁 转移分类）
  - 单只基金设“今日预测涨幅(%)”，分析时仅对该基金生效（临时展示，不污染历史数据）
  - 一键批量 / 单只分析（后台线程，界面不卡）
  - 列表直接看「类型 / 最新净值 / 估值分位 / 最新信号 / 预测% / 上次更新」
  - 列表前加勾选框可多选基金（删除 / 分析 / 转移 以勾选为准；工具栏“☑ 全选”可一键全选/取消）
  - 支持按关键字（代码/名称）、分类筛选，并支持“只看已勾选”
  - 每个分类可自定义行底色配色（🎨 配色），列表按分类染色便于区分
  - 按钮或双击直接打开报告（浏览器查看“走势图.html”，不再每次都新开一个文件夹窗口；需要原始文件时点“📁 文件夹”）
  - 今日预测仅在“今日真实净值尚未发布”时叠加显示在走势图上，并连到历史走势；一旦当日真实净值发布，预测自动清除（不会永远留在那里）
  - 默认每次分析都联网抓“最新”净值；断网时可勾“离线模式”只读本地缓存

运行：python gui.py   （需已安装 akshare / pandas / matplotlib / tkinter）
"""

import os
import sys
import json
import csv
import queue
import subprocess
import threading
import webbrowser
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog

import analysis

BASE = os.path.dirname(os.path.abspath(__file__))
LIST_PATH = os.path.join(BASE, "funds.json")
CAT_PATH = os.path.join(BASE, "categories.json")
DEFAULT_CATEGORIES = ["持仓", "临时", "自选", "观察", "其它"]


# ----------------------------------------------------------------------------
# 分类标签：可被 UI 重命名 / 新增 / 删除，故动态读写（存在 categories.json）
# ----------------------------------------------------------------------------
def get_categories() -> list:
    if os.path.exists(CAT_PATH):
        try:
            with open(CAT_PATH, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass
    return list(DEFAULT_CATEGORIES)


def save_categories(cats: list):
    with open(CAT_PATH, "w", encoding="utf-8") as f:
        json.dump(cats, f, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------------
# 分类配色：每行底色按分类染色，便于区分；颜色存于 cat_colors.json（可自定义）
# ----------------------------------------------------------------------------
CAT_COLORS_PATH = os.path.join(BASE, "cat_colors.json")
DEFAULT_CAT_COLORS = {"持仓": "#2e7d32", "临时": "#f9a825", "自选": "#1565c0",
                      "观察": "#6a1b9a", "其它": "#757575"}
PALETTE = ["#2e7d32", "#f9a825", "#1565c0", "#6a1b9a", "#757575",
           "#c62828", "#00838f", "#ef6c00", "#4527a0", "#ad1457"]

# 估值结论（信号）按等级着色（前景色），便于一眼区分高估/低估
SIGNAL_COLORS = {
    "严重高估": "#b71c1c",
    "高估":     "#d32f2f",
    "估值偏高": "#e65100",
    "合理":     "#546e7a",
    "估值偏低": "#2e7d32",
    "低估":     "#1b8a3a",
    "严重低估": "#00695c",
}


def get_cat_colors() -> dict:
    colors = dict(DEFAULT_CAT_COLORS)
    if os.path.exists(CAT_COLORS_PATH):
        try:
            with open(CAT_COLORS_PATH, encoding="utf-8") as f:
                colors.update(json.load(f))
        except Exception:
            pass
    # 确保每个现有分类都有颜色
    for i, c in enumerate(get_categories()):
        if c not in colors:
            colors[c] = PALETTE[i % len(PALETTE)]
    return colors


def save_cat_colors(colors: dict):
    with open(CAT_COLORS_PATH, "w", encoding="utf-8") as f:
        json.dump(colors, f, ensure_ascii=False, indent=2)


def _lighten(hex_color: str, ratio: float = 0.82) -> str:
    """把颜色向白色混合 ratio 比例，得到淡色（用于行底色，保证黑字可读）。"""
    h = hex_color.lstrip("#")
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return "#f2f2f2"
    r = int(r + (255 - r) * ratio)
    g = int(g + (255 - g) * ratio)
    b = int(b + (255 - b) * ratio)
    return f"#{r:02x}{g:02x}{b:02x}"


# ----------------------------------------------------------------------------
# 名单：funds.json 为唯一权威源（含运行信息）。已弃用 txt 名单，所有读写只针对 json。
# ----------------------------------------------------------------------------
def load_list():
    """加载名单（funds.json 为唯一权威源）。代码统一补零到 6 位并去重
    （如 110→000110），避免重复。"""
    items = []
    if os.path.exists(LIST_PATH):
        try:
            with open(LIST_PATH, encoding="utf-8") as f:
                items = json.load(f)
        except Exception:
            items = []
    # 归一化代码 + 去重，避免 110 / 000110 被当成两只基金
    norm = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        code = str(it.get("code", "")).strip().zfill(6)
        it["code"] = code
        if code in norm:
            # 合并：用信息更全的一方填补空缺字段
            for k, v in it.items():
                if v not in (None, "", "-") and norm[code].get(k) in (None, "", "-"):
                    norm[code][k] = v
        else:
            norm[code] = it
    items = list(norm.values())
    save_list(items)  # 归一化后落盘
    return items


def save_list(items):
    """把名单写入 funds.json（唯一权威源）。代码统一补零到 6 位。"""
    norm_items = []
    for it in items:
        it = dict(it)
        it["code"] = str(it.get("code", "")).strip().zfill(6)
        norm_items.append(it)
    with open(LIST_PATH, "w", encoding="utf-8") as f:
        json.dump(norm_items, f, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------------
# 主界面
# ----------------------------------------------------------------------------
class FundApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("基金走势分析")
        self.root.geometry("1180x720")

        self.items = load_list()
        self._prune_obsolete_predictions()   # 启动时清除“今日真实净值已发布”的过期预测
        self.q = queue.Queue()
        self.worker = None
        self.sort_key = None          # 当前排序列（None = 按自定义/手动顺序）
        self.sort_reverse = False
        self.drag_item = None         # 拖拽中的行（自定义排序）
        self.did_drag = False         # 本次按下后是否真发生了移动（用于区分“单击”与“拖拽”）
        self.checked = set()          # 勾选框选中的基金代码集合

        self._build_ui()
        self._refresh_tree()

    # ---- UI 布局 ----
    def _build_ui(self):
        self._tip = None  # 悬停详情浮层
        # 顶部工具栏
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill=tk.X)
        ttk.Button(top, text="➕ 添加基金", command=self._add_fund).pack(side=tk.LEFT, padx=3)
        ttk.Button(top, text="🗑 删除选中", command=self._delete_fund).pack(side=tk.LEFT, padx=3)
        ttk.Button(top, text="🔄 刷新名称", command=self._refresh_names).pack(side=tk.LEFT, padx=3)
        ttk.Button(top, text="📈 设今日预测", command=self._set_predict).pack(side=tk.LEFT, padx=3)
        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=6, fill=tk.Y)
        self.offline_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="离线模式(用缓存,不联网)", variable=self.offline_var).pack(side=tk.LEFT, padx=3)
        ttk.Button(top, text="▶ 开始分析选中", command=self._start).pack(side=tk.LEFT, padx=3)
        ttk.Button(top, text="📂 打开报告", command=self._open_selected).pack(side=tk.LEFT, padx=3)
        ttk.Button(top, text="📁 文件夹", command=self._open_folder_selected).pack(side=tk.LEFT, padx=3)
        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=6, fill=tk.Y)
        ttk.Button(top, text="🔁 转移分类", command=self._transfer_category).pack(side=tk.LEFT, padx=3)
        ttk.Button(top, text="🏷 管理分类", command=self._manage_categories).pack(side=tk.LEFT, padx=3)
        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=6, fill=tk.Y)
        ttk.Button(top, text="↺ 清除排序", command=self._clear_sort).pack(side=tk.LEFT, padx=3)
        self.sort_var = tk.StringVar(value="顺序：自定义（拖拽行可调整）")
        ttk.Label(top, textvariable=self.sort_var, foreground="#1a73e8").pack(side=tk.LEFT, padx=4)

        hint = ttk.Label(
            self.root,
            text="默认每次都联网抓最新净值；断网时勾“离线模式”只读本地缓存。多选后点“开始分析选中”批量跑；"
                 "单选一只并“设今日预测”可对该基金单独预测。双击某行打开报告；鼠标悬停某行看详情。"
                 "左上角勾选框可多选基金（删除/分析/转移以勾选为准，“☑ 全选”一键全选/取消）；"
                 "顶部可按关键字、分类筛选（含“只看已勾选”）；点击列头排序（再点切换升/降序）；"
                 "无筛选/无排序时上下拖动行可自定义顺序，松手即保存为默认顺序；分类行底色可在“🎨 配色”里自定义。"
                 "估值结论按信号等级着色（红=偏贵、绿=偏便宜），与分类底色互不冲突。"
                 "报告里的「走势图.html」支持顶部日期筛选（From/To）与上下两图滑块联动，指数基金额外显示跟踪指数 PE 分位。",
            foreground="#666",
        )
        hint.pack(fill=tk.X, padx=8)

        # 筛选栏
        filter_f = ttk.Frame(self.root, padding=(8, 2, 8, 6))
        filter_f.pack(fill=tk.X)
        ttk.Label(filter_f, text="筛选：").pack(side=tk.LEFT)
        self.filter_text_var = tk.StringVar()
        self.filter_text_var.trace_add("write", lambda *a: self._refresh_tree())
        ttk.Entry(filter_f, textvariable=self.filter_text_var, width=18).pack(side=tk.LEFT, padx=3)
        ttk.Label(filter_f, text="分类：").pack(side=tk.LEFT, padx=(6, 2))
        self.filter_cat_var = tk.StringVar(value="全部")
        self.filter_cat_cb = ttk.Combobox(filter_f, textvariable=self.filter_cat_var,
                                          values=["全部"] + get_categories(), width=10, state="readonly")
        self.filter_cat_cb.pack(side=tk.LEFT, padx=3)
        self.filter_cat_var.trace_add("write", lambda *a: self._refresh_tree())
        self.filter_checked_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(filter_f, text="只看已勾选", variable=self.filter_checked_var,
                        command=self._refresh_tree).pack(side=tk.LEFT, padx=6)
        ttk.Separator(filter_f, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=8, fill=tk.Y)
        ttk.Button(filter_f, text="☑ 全选", command=self._toggle_all).pack(side=tk.LEFT, padx=2)
        self.check_var = tk.StringVar(value="已勾选 0 只")
        ttk.Label(filter_f, textvariable=self.check_var, foreground="#137333").pack(side=tk.LEFT, padx=4)
        ttk.Button(filter_f, text="🎨 配色", command=self._edit_colors).pack(side=tk.LEFT, padx=2)

        # 列表（带垂直 + 水平滚动条，避免“看不到底部/右侧内容”）
        cols = ("sel", "code", "name", "category", "type", "latest_nav", "valuation", "signal", "predict", "updated")
        tree_frame = ttk.Frame(self.root)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="extended")
        headers = {
            "sel": "✓", "code": "代码", "name": "名称", "category": "分类", "type": "类型",
            "latest_nav": "最新净值", "valuation": "估值分位", "signal": "估值结论",
            "predict": "预测%", "updated": "上次更新",
        }
        widths = {"sel": 34, "code": 78, "name": 230, "category": 60, "type": 70, "latest_nav": 80,
                  "valuation": 80, "signal": 150, "predict": 60, "updated": 100}
        for c in cols:
            self.tree.heading(c, text=headers[c], command=lambda c=c: self._on_heading_click(c))
            self.tree.column(c, width=widths[c], anchor=tk.CENTER if c not in ("name", "signal") else tk.W)
        # 滚动条：垂直（右侧，看全列表）+ 水平（底部，看全列）
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", lambda e: self._open_selected())
        self.tree.bind("<Motion>", self._on_motion)
        self.tree.bind("<Leave>", lambda e: self._hide_tip())
        # 自定义排序：拖拽行（与双击打开报告不冲突：移动打断双击）
        self.tree.bind("<ButtonPress-1>", self._on_press)
        self.tree.bind("<B1-Motion>", self._on_drag)
        self.tree.bind("<ButtonRelease-1>", self._on_release)

        # 日志
        bottom = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        bottom.pack(fill=tk.BOTH, expand=True)
        ttk.Label(bottom, text="运行日志：").pack(anchor=tk.W)
        self.log = scrolledtext.ScrolledText(bottom, height=9, state=tk.DISABLED)
        self.log.pack(fill=tk.BOTH, expand=True)

    # ---- 列表刷新 ----
    def _refresh_tree(self):
        # 分类底色：每个分类一个 tag
        colors = get_cat_colors()
        cat_tag = {}
        for i, c in enumerate(get_categories()):
            tag = f"cat{i}"
            cat_tag[c] = tag
            self.tree.tag_configure(tag, background=_lighten(colors.get(c, "#757575")))

        # 估值结论：按信号等级着色（前景色），一眼区分高估/低估
        sig_tag = {}
        for idx, (s, col) in enumerate(SIGNAL_COLORS.items()):
            tag = f"sig{idx}"
            sig_tag[s] = tag
            self.tree.tag_configure(tag, foreground=col)

        # 排序
        if self.sort_key:
            base = sorted(self.items, key=lambda it: self._cell_sort_key(self.sort_key, it),
                          reverse=self.sort_reverse)
        else:
            base = self.items

        # 筛选
        text = self.filter_text_var.get().strip().lower()
        catf = self.filter_cat_var.get()
        chk_only = self.filter_checked_var.get()
        displayed = []
        for it in base:
            if catf != "全部" and it.get("category") != catf:
                continue
            if text:
                if text not in it["code"].lower() and text not in str(it.get("name", "")).lower():
                    continue
            if chk_only and it["code"] not in self.checked:
                continue
            displayed.append(it)

        for row in self.tree.get_children():
            self.tree.delete(row)
        for it in displayed:
            pred = it.get("predict_today")
            pred_txt = "" if pred is None else f"{pred:+.2f}"
            checked = "☑" if it["code"] in self.checked else "☐"
            tag = cat_tag.get(it.get("category", "其它"), "cat0")
            sig = it.get("signal", "-")
            tags = (tag, sig_tag[sig]) if sig in sig_tag else (tag,)
            self.tree.insert(
                "", tk.END, iid=it["code"], tags=tags,
                values=(checked, it["code"], it.get("name", ""), it.get("category", "其它"), it.get("type", "-"),
                        it.get("latest_nav", "-"), it.get("valuation", "-"),
                        it.get("signal", "-"), pred_txt, it.get("updated", "-")),
            )

    # ---- 排序 / 自定义顺序 ----
    def _on_heading_click(self, col):
        """点击列头排序：同列再次点击切换升/降序，换列则重置为升序。"""
        if col == "sel":   # 勾选框列不参与排序
            return
        if self.sort_key == col:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_key = col
            self.sort_reverse = False
        self._refresh_tree()
        self._update_sort_label()

    def _clear_sort(self):
        """取消列排序，回到用户自定义的手动顺序。"""
        self.sort_key = None
        self.sort_reverse = False
        self._refresh_tree()
        self._update_sort_label()

    def _update_sort_label(self):
        if not self.sort_key:
            self.sort_var.set("顺序：自定义（拖拽行可调整）")
            return
        headers = {"code": "代码", "name": "名称", "category": "分类", "type": "类型",
                   "latest_nav": "最新净值", "valuation": "估值分位", "signal": "估值结论",
                   "predict": "预测%", "updated": "上次更新"}
        arrow = "↓降序" if self.sort_reverse else "↑升序"
        self.sort_var.set(f"已按「{headers.get(self.sort_key, self.sort_key)}」{arrow}")

    @staticmethod
    def _cell_sort_key(col, it):
        """返回排序用的 (rank, value) 元组：rank=0 有值排前面，rank=1 缺失排最后。"""
        if col == "valuation":
            v = it.get("valuation")
            return (0, float(v)) if isinstance(v, (int, float)) else (1, 0.0)
        if col == "latest_nav":
            v = it.get("latest_nav")
            try:
                return (0, float(v))
            except (TypeError, ValueError):
                return (1, 0.0)
        if col == "predict":
            v = it.get("predict_today")
            return (0, float(v)) if isinstance(v, (int, float)) else (1, 0.0)
        if col == "signal":
            order = {"严重高估": 0, "高估": 1, "估值偏高": 2, "合理": 3,
                     "估值偏低": 4, "低估": 5, "严重低估": 6}
            s = it.get("signal", "-")
            return (0, order.get(s, 7)) if s in order else (1, 0)
        v = it.get(col, "")
        return (0, str(v))

    # ---- 拖拽自定义排序 ----
    def _on_press(self, event):
        self.drag_item = None
        self.did_drag = False
        # 点在第一列（勾选框）-> 切换勾选，不触发拖拽
        if self.tree.identify_column(event.x) == "#1":
            row = self.tree.identify_row(event.y)
            if row:
                self._toggle_check(row)
            return
        self.drag_item = self.tree.identify_row(event.y)

    def _on_drag(self, event):
        if self.drag_item is None:
            return
        # 真正发生了移动才算“拖拽”，否则视为普通单击（不触发重排/不弹提示）
        self.did_drag = True
        # 拖动时高亮目标行，给出视觉反馈（ttk 行背景 tag）
        row = self.tree.identify_row(event.y)
        if row and row != self.drag_item:
            try:
                self.tree.tag_configure("__drag__", background="#e3f2fd")
                for r in self.tree.get_children():
                    self.tree.item(r, tags=())
                self.tree.item(row, tags=("__drag__",))
            except Exception:
                pass

    def _on_release(self, event):
        di = self.drag_item
        self.drag_item = None
        # 仅当“真正拖动过”才进入拖拽逻辑；普通单击直接放行，避免误报“拖拽禁用”
        if di is None or not self.did_drag:
            return
        # 筛选/排序状态下拖拽重排无意义（显示顺序 ≠ 真实顺序），禁用并提示
        if not self._plain_mode():
            self._log("当前处于筛选/排序状态，拖拽重排已禁用；请先清除筛选与排序再调整顺序。")
            self._refresh_tree()
            return
        target = self.tree.identify_row(event.y)
        if not target or target == di:
            self._refresh_tree()
            return
        # 进入自定义顺序：清除列排序，按当前界面顺序重排 self.items 并保存
        self.sort_key = None
        children = list(self.tree.get_children())
        codes_order = [c for c in children if c != di]
        insert_at = codes_order.index(target)
        codes_order.insert(insert_at, di)
        by_code = {it["code"]: it for it in self.items}
        self.items = [by_code[c] for c in codes_order]
        save_list(self.items)
        self._update_sort_label()
        self._refresh_tree()
        self._log(f"已调整顺序（{di} 移到 {target} 之前），已保存为默认顺序")

    # ---- 勾选框 / 筛选 相关 ----
    def _toggle_check(self, code):
        """切换某行的勾选状态（只改单元格，不重排）。"""
        if code in self.checked:
            self.checked.discard(code)
            self.tree.set(code, "sel", "☐")
        else:
            self.checked.add(code)
            self.tree.set(code, "sel", "☑")
        self._update_check_label()

    def _update_check_label(self):
        if hasattr(self, "check_var"):
            self.check_var.set(f"已勾选 {len(self.checked)} 只")

    def _toggle_all(self):
        """一键全选 / 取消：若当前可见行已全部勾选则取消全选，否则全选当前可见行。"""
        visible = list(self.tree.get_children())
        if visible and all(c in self.checked for c in visible):
            self.checked = set()
        else:
            self.checked = set(visible)
        self._refresh_tree()
        self._update_check_label()

    def _plain_mode(self):
        """是否处于“无筛选 + 无排序”的纯自定义顺序模式（仅此模式允许拖拽重排）。"""
        return (not self.sort_key and
                self.filter_cat_var.get() == "全部" and
                not self.filter_text_var.get().strip() and
                not self.filter_checked_var.get())

    def _active_selection(self):
        """批量操作的选中目标：优先取勾选集合，否则取 Treeview 选中行；只作用于可见行。"""
        visible = set(self.tree.get_children())
        if self.checked:
            return [c for c in self.checked if c in visible]
        return [c for c in self.tree.selection() if c in visible]

    def _refresh_filter_categories(self):
        if hasattr(self, "filter_cat_cb"):
            self.filter_cat_cb["values"] = ["全部"] + get_categories()

    def _edit_colors(self):
        dlg = CategoryColorDialog(self.root)
        self.root.wait_window(dlg.top)
        self._refresh_tree()

    def _log(self, msg):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    # ---- 增删改 ----
    def _add_fund(self):
        dlg = AddFundDialog(self.root)
        self.root.wait_window(dlg.top)
        if dlg.result:
            code = dlg.result["code"]
            if any(i["code"] == code for i in self.items):
                messagebox.showinfo("提示", f"代码 {code} 已在列表中")
                return
            self.items.append(dlg.result)
            save_list(self.items)
            self._refresh_tree()
            self._log(f"已添加 {code} {dlg.result['name']}（{dlg.result.get('category','')}）")

    def _delete_fund(self):
        sel = self._active_selection()
        if not sel:
            messagebox.showinfo("提示", "请先勾选要删除的基金（或选中行）")
            return
        for code in sel:
            self.items = [i for i in self.items if i["code"] != code]
        self.checked = {c for c in self.checked if c in {i["code"] for i in self.items}}
        save_list(self.items)
        self._refresh_tree()
        self._update_check_label()
        self._log(f"已删除 {len(sel)} 只基金（已写入 funds.json）")

    def _refresh_names(self):
        # funds.json 是唯一权威源：先重新读取（拾取你手动在 json 里新增的代码），
        # 再按 id 联网刷新名称与类型
        self.items = load_list()
        self._refresh_tree()
        sel = self.tree.selection() or [i["code"] for i in self.items]
        for code in sel:
            try:
                basic = analysis.get_fund_basic(code)
                for it in self.items:
                    if it["code"] == code:
                        it["name"] = basic.get("基金名称", it.get("name", ""))
                        it["type"] = basic.get("基金类型", it.get("type", ""))
            except Exception as e:  # noqa
                self._log(f"[{code}] 刷新失败：{e}")
        save_list(self.items)
        self._refresh_tree()
        self._log("名称/类型刷新完成")

    def _set_predict(self):
        sel = self.tree.selection()
        if len(sel) != 1:
            messagebox.showinfo("提示", "请“单选”一只基金再设今日预测")
            return
        code = sel[0]
        dlg = PredictDialog(self.root, code, next(i for i in self.items if i["code"] == code))
        self.root.wait_window(dlg.top)
        if dlg.changed:
            save_list(self.items)
            self._refresh_tree()
            self._log(f"已为 {code} 设置今日预测：{dlg.value}")

    # ---- 分类管理 ----
    def _transfer_category(self):
        """把选中的基金转移到另一个分类（支持多选）。"""
        sel = self._active_selection()
        if not sel:
            messagebox.showinfo("提示", "请先勾选要转移的基金（或选中行，可多选）")
            return
        dlg = TransferDialog(self.root, get_categories())
        self.root.wait_window(dlg.top)
        if dlg.result:
            target = dlg.result
            moved = 0
            for code in sel:
                for it in self.items:
                    if it["code"] == code:
                        it["category"] = target
                        moved += 1
            save_list(self.items)  # 内部按新分类写回 funds.json
            self._refresh_tree()
            self._log(f"已将 {moved} 只基金转移到「{target}」")

    def _manage_categories(self):
        """重命名 / 新增 / 删除分类标签（改动写回 funds.json 与 categories.json）。"""
        dlg = CategoryManageDialog(self.root, self.items)
        self.root.wait_window(dlg.top)
        if dlg.changed:
            save_list(self.items)  # 重命名后按新分类写回 funds.json
            self._refresh_filter_categories()
            self._refresh_tree()
            self._log("分类标签已更新")

    # ---- 分析流程 ----
    def _start(self):
        sel = self._active_selection()
        if not sel:
            messagebox.showinfo("提示", "请先勾选要分析的基金（或选中行，可多选）")
            return
        self._log(f"开始分析 {len(sel)} 只基金 ……（后台运行中，界面可继续操作）")
        self.worker = threading.Thread(target=self._run_worker, args=(list(sel),), daemon=True)
        self.worker.start()
        self.root.after(120, self._poll)

    def _run_worker(self, codes):
        offline = self.offline_var.get()
        pred_map = {it["code"]: it.get("predict_today") for it in self.items}
        for code in codes:
            try:
                res = analysis.run_fund(code, offline=offline, predict_today=pred_map.get(code))
                self.q.put(("ok", res))
            except Exception as e:  # noqa
                self.q.put(("err", (code, str(e))))
        self.q.put(("done", None))

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "ok":
                    self._apply_result(payload)
                    self._log(f"✔ {payload['code']} {payload['name']}【{payload.get('type','')}】→ {payload['signal']}（估值分位 {payload['valuation']}）")
                elif kind == "err":
                    code, err = payload
                    self._log(f"✘ {code} 失败：{err}")
                elif kind == "done":
                    self._refresh_tree()
                    self._log("全部完成。")
                    return
        except queue.Empty:
            pass
        self.root.after(120, self._poll)

    def _apply_result(self, res):
        for it in self.items:
            if it["code"] == res["code"]:
                it.update({
                    "name": res.get("name", it.get("name", "")),
                    "type": res.get("type", it.get("type", "")),
                    "latest_nav": res.get("latest_nav", "-"),
                    "valuation": res.get("valuation") if res.get("valuation") is not None else "-",
                    "signal": res.get("signal", "-"),
                    "detail": res.get("detail", "-"),
                    "drawdown": res.get("drawdown") if res.get("drawdown") is not None else "-",
                    "updated": res.get("updated", "-"),
                })
                # 今日真实净值已发布 → 预测已无意义，自动清除（避免预测永远留在那里）
                if res.get("prediction_obsolete") and it.get("predict_today") is not None:
                    it["predict_today"] = None
                    self._log(f"ℹ {res['code']}：今日真实净值已发布，今日预测已自动清除")
        save_list(self.items)

    # ---- 悬停详情 ----
    def _on_motion(self, event):
        rowid = self.tree.identify_row(event.y)
        if not rowid:
            self._hide_tip()
            return
        item = next((i for i in self.items if i["code"] == rowid), None)
        if not item:
            self._hide_tip()
            return
        iv = item.get("index_val")
        iv_txt = ""
        if iv:
            iv_txt = f"指数估值：{iv.get('index','')} PE={iv.get('pe','-')} 分位={iv.get('pe_pct','-')}\n"
        txt = (f"{item['code']} {item.get('name', '')}\n"
               f"类型：{item.get('type', '-')}\n"
               f"估值结论：{item.get('signal', '-')}\n"
               f"细节：{item.get('detail', '-')}\n"
               f"{iv_txt}"
               f"近一年最大回撤：{item.get('drawdown', '-')}")
        if self._tip is None:
            self._tip = tk.Toplevel(self.root)
            self._tip.wm_overrideredirect(True)
            self._tip_label = tk.Label(self._tip, text=txt, justify=tk.LEFT,
                                       background="#fffbe6", relief=tk.SOLID, borderwidth=1,
                                       font=("Microsoft YaHei", 9))
            self._tip_label.pack()
        else:
            self._tip_label.configure(text=txt)
        self._tip.wm_geometry(f"+{event.x_root + 14}+{event.y_root + 14}")

    def _hide_tip(self):
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None

    # ---- 预测过期清理 ----
    def _prune_obsolete_predictions(self):
        """启动时扫描：若某基金本地缓存的最新净值日期已是今天（今日真实净值已出），
        则清除其 predict_today，避免“预测永远留在那里”。仅读本地缓存，不联网。"""
        today = str(datetime.now().date())
        changed = False
        for it in self.items:
            if it.get("predict_today") is None:
                continue
            code = it["code"]
            csv_path = os.path.join(analysis.resolve_fund_dir(code, it.get("name", "")), "历史净值.csv")
            last_date = None
            if os.path.exists(csv_path):
                try:
                    with open(csv_path, encoding="utf-8-sig", newline="") as f:
                        r = csv.reader(f)
                        header = next(r, None)
                        rows = [row for row in r]
                    if rows:
                        idx = 0
                        if header and "净值日期" in header:
                            idx = header.index("净值日期")
                        last_date = (rows[-1][idx] or "").strip()
                except Exception:
                    last_date = None
            if last_date and last_date[:10] == today:
                it["predict_today"] = None
                changed = True
        if changed:
            save_list(self.items)
            self._log("已自动清除今日真实净值已发布的过期预测")

    # ---- 打开报告 ----
    def _open_selected(self):
        """双击 / “打开报告”按钮：直接在默认浏览器里打开该基金的「走势图.html」。
        浏览器用标签页，不会出现“每次双击都新开一个文件夹窗口”的堆积问题。"""
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选中一只基金")
            return
        self._open_report(sel[0])

    def _open_report(self, code):
        item = next((i for i in self.items if i["code"] == code), None)
        if not item:
            return
        folder = analysis.resolve_fund_dir(code, item.get("name", ""))
        html = os.path.join(folder, "走势图.html")
        if os.path.exists(html):
            webbrowser.open("file://" + os.path.abspath(html))
        elif os.path.isdir(folder):
            # 还没生成过交互图，退回打开文件夹（仍可能看到 PNG）
            self._open_folder(folder)
        else:
            messagebox.showinfo("提示", "该基金还没有分析报告，请先分析。")

    def _open_folder_selected(self):
        """“打开文件夹”按钮：当你确实需要 CSV / PNG 等原始文件时才用，单独一个按钮避免误开。"""
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选中一只基金")
            return
        item = next((i for i in self.items if i["code"] == sel[0]), None)
        if not item:
            return
        folder = analysis.resolve_fund_dir(sel[0], item.get("name", ""))
        if os.path.isdir(folder):
            self._open_folder(folder)
        else:
            messagebox.showinfo("提示", "该基金还没有分析文件夹，请先分析。")

    @staticmethod
    def _open_folder(folder: str):
        """跨平台打开目录：Windows 用 explorer，macOS 用 open，Linux 用 xdg-open。"""
        try:
            if sys.platform == "win32":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.run(["open", folder], check=False)
            else:
                subprocess.run(["xdg-open", folder], check=False)
        except Exception as e:  # noqa
            messagebox.showerror("打开失败", f"无法打开目录：{e}")


# ----------------------------------------------------------------------------
# 添加基金弹窗
# ----------------------------------------------------------------------------
class AddFundDialog:
    def __init__(self, parent):
        self.result = None
        self.top = tk.Toplevel(parent)
        self.top.title("添加基金")
        self.top.geometry="380x210"
        self.top.resizable(False, False)
        self.top.grab_set()

        f = ttk.Frame(self.top, padding=12)
        f.pack(fill=tk.BOTH, expand=True)
        ttk.Label(f, text="基金代码：").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.code_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.code_var, width=16).grid(row=0, column=1, sticky=tk.W, pady=4)
        ttk.Button(f, text="查询名称", command=self._query).grid(row=0, column=2, padx=6, pady=4)

        ttk.Label(f, text="基金名称：").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.name_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.name_var, width=26).grid(row=1, column=1, columnspan=2, sticky=tk.W, pady=4)

        ttk.Label(f, text="分类：").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.cat_var = tk.StringVar(value=get_categories()[0])
        ttk.Combobox(f, textvariable=self.cat_var, values=get_categories(), width=14, state="readonly").grid(
            row=2, column=1, columnspan=2, sticky=tk.W, pady=4)

        self.status = ttk.Label(f, text="")
        self.status.grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=2)

        btns = ttk.Frame(f)
        btns.grid(row=4, column=0, columnspan=3, pady=10)
        ttk.Button(btns, text="确定", command=self._ok).pack(side=tk.LEFT, padx=8)
        ttk.Button(btns, text="取消", command=self._cancel).pack(side=tk.LEFT, padx=8)

    def _query(self):
        code = self.code_var.get().strip().zfill(6)
        if not code.isdigit() or len(code) != 6:
            self.status.config(text="请输入 6 位数字基金代码")
            return
        self.status.config(text="查询中……")
        try:
            basic = analysis.get_fund_basic(code)
            self.name_var.set(basic.get("基金名称", ""))
            self.status.config(text=f"已自动填入（类型：{basic.get('基金类型','')}），可手动修改")
        except Exception as e:  # noqa
            self.status.config(text=f"自动查询失败，可手动填写：{e}")

    def _ok(self):
        code = self.code_var.get().strip().zfill(6)
        if not code.isdigit() or len(code) != 6:
            self.status.config(text="请输入 6 位数字基金代码")
            return
        self.result = {"code": code, "name": self.name_var.get().strip(), "category": self.cat_var.get()}
        self.top.destroy()

    def _cancel(self):
        self.top.destroy()


# ----------------------------------------------------------------------------
# 设今日预测弹窗
# ----------------------------------------------------------------------------
class PredictDialog:
    def __init__(self, parent, code, item):
        self.code = code
        self.item = item
        self.changed = False
        self.value = item.get("predict_today")
        self.top = tk.Toplevel(parent)
        self.top.title(f"今日预测 · {code}")
        self.top.geometry("360x250")
        self.top.resizable(False, False)
        self.top.grab_set()

        f = ttk.Frame(self.top, padding=14)
        f.pack(fill=tk.BOTH, expand=True)
        ttk.Label(f, text=f"基金 {code} {item.get('name','')}").pack(anchor=tk.W)
        ttk.Label(f, text="今日预测涨幅(%)：").pack(anchor=tk.W, pady=(8, 2))
        self.var = tk.StringVar(value="" if self.value is None else str(self.value))
        ttk.Entry(f, textvariable=self.var, width=12).pack(anchor=tk.W)
        ttk.Label(f, text="例：-1 表示今日预计跌 1%；留空 = 清除预测。").pack(anchor=tk.W, pady=(4, 0))

        btns = ttk.Frame(f)
        btns.pack(pady=10)
        ttk.Button(btns, text="确定", command=self._ok).pack(side=tk.LEFT, padx=8)
        ttk.Button(btns, text="取消", command=self._cancel).pack(side=tk.LEFT, padx=8)

    def _ok(self):
        raw = self.var.get().strip()
        if raw == "":
            self.item["predict_today"] = None
            self.changed = True
            self.top.destroy()
            return
        try:
            self.item["predict_today"] = float(raw)
        except ValueError:
            messagebox.showerror("错误", "请输入数字，如 -1 表示跌 1%")
            return
        self.changed = True
        self.top.destroy()

    def _cancel(self):
        self.top.destroy()


# ----------------------------------------------------------------------------
# 管理分类标签弹窗（改名 / 新增 / 删除空标签）
# ----------------------------------------------------------------------------
class CategoryManageDialog:
    def __init__(self, parent, items):
        self.items = items
        self.changed = False
        self.top = tk.Toplevel(parent)
        self.top.title("管理分类标签")
        self.top.geometry("380x340")
        self.top.resizable(False, False)
        self.top.grab_set()
        self.cats = list(get_categories())

        f = ttk.Frame(self.top, padding=12)
        f.pack(fill=tk.BOTH, expand=True)
        ttk.Label(f, text="分类标签（可直接改名 / 新增 / 删除空标签）：").pack(anchor=tk.W)
        self.lb = tk.Listbox(f, height=8)
        self.lb.pack(fill=tk.BOTH, expand=True, pady=6)
        for c in self.cats:
            self.lb.insert(tk.END, c)

        row = ttk.Frame(f)
        row.pack(fill=tk.X, pady=4)
        ttk.Button(row, text="改名", command=self._rename).pack(side=tk.LEFT, padx=4)
        ttk.Button(row, text="新增", command=self._add).pack(side=tk.LEFT, padx=4)
        ttk.Button(row, text="删除空标签", command=self._delete).pack(side=tk.LEFT, padx=4)

        btns = ttk.Frame(f)
        btns.pack(pady=8)
        ttk.Button(btns, text="确定", command=self._ok).pack(side=tk.LEFT, padx=8)
        ttk.Button(btns, text="取消", command=self._cancel).pack(side=tk.LEFT, padx=8)

    def _used_count(self, cat):
        return sum(1 for it in self.items if it.get("category") == cat)

    def _rename(self):
        sel = self.lb.curselection()
        if not sel:
            messagebox.showinfo("提示", "请先选中一个标签再改名")
            return
        idx = sel[0]
        old = self.lb.get(idx)
        new = simpledialog.askstring("改名", f"将「{old}」改为：", initialvalue=old, parent=self.top)
        if not new:
            return
        new = new.strip()
        if not new:
            messagebox.showinfo("提示", "名称不能为空")
            return
        if new in self.cats:
            messagebox.showinfo("提示", "已存在同名标签")
            return
        # 更新基金项的分类
        for it in self.items:
            if it.get("category") == old:
                it["category"] = new
        self.cats[idx] = new
        self.lb.delete(idx)
        self.lb.insert(idx, new)
        self.changed = True
        save_categories(self.cats)

    def _add(self):
        new = simpledialog.askstring("新增分类", "请输入新分类名称：", parent=self.top)
        if not new:
            return
        new = new.strip()
        if not new:
            messagebox.showinfo("提示", "名称不能为空")
            return
        if new in self.cats:
            messagebox.showinfo("提示", "已存在同名标签")
            return
        self.cats.append(new)
        self.lb.insert(tk.END, new)
        self.changed = True
        save_categories(self.cats)

    def _delete(self):
        sel = self.lb.curselection()
        if not sel:
            messagebox.showinfo("提示", "请先选中一个标签再删除")
            return
        idx = sel[0]
        cat = self.lb.get(idx)
        n = self._used_count(cat)
        if n > 0:
            messagebox.showinfo("提示", f"「{cat}」下还有 {n} 只基金，无法删除。\n请先把这些基金转移到其它分类，或改用「改名」。")
            return
        del self.cats[idx]
        self.lb.delete(idx)
        self.changed = True
        save_categories(self.cats)

    def _ok(self):
        self.top.destroy()

    def _cancel(self):
        self.top.destroy()


# ----------------------------------------------------------------------------
# 转移到分类弹窗
# ----------------------------------------------------------------------------
class TransferDialog:
    def __init__(self, parent, cats):
        self.result = None
        self.top = tk.Toplevel(parent)
        self.top.title("转移到分类")
        self.top.geometry("320x150")
        self.top.resizable(False, False)
        self.top.grab_set()
        f = ttk.Frame(self.top, padding=12)
        f.pack(fill=tk.BOTH, expand=True)
        ttk.Label(f, text="把选中基金转移到：").pack(anchor=tk.W)
        self.var = tk.StringVar(value=cats[0] if cats else "其它")
        ttk.Combobox(f, textvariable=self.var, values=cats, width=16, state="readonly").pack(anchor=tk.W, pady=8)
        btns = ttk.Frame(f)
        btns.pack(pady=8)
        ttk.Button(btns, text="确定", command=self._ok).pack(side=tk.LEFT, padx=8)
        ttk.Button(btns, text="取消", command=self._cancel).pack(side=tk.LEFT, padx=8)

    def _ok(self):
        self.result = self.var.get().strip()
        self.top.destroy()

    def _cancel(self):
        self.top.destroy()


# ----------------------------------------------------------------------------
# 分类配色弹窗
# ----------------------------------------------------------------------------
class CategoryColorDialog:
    def __init__(self, parent):
        self.top = tk.Toplevel(parent)
        self.top.title("分类配色")
        self.top.geometry("380x480")
        self.top.resizable(False, False)
        self.top.grab_set()
        self.colors = get_cat_colors()
        self.cat_frames = {}     # cat -> {palette_color: button}
        self.custom_btns = {}    # cat -> “自定义”按钮（其 bg 反映当前色）

        f = ttk.Frame(self.top, padding=12)
        f.pack(fill=tk.BOTH, expand=True)
        ttk.Label(f, text="点击色块即可设为该分类的行底色；当前选中块带高亮边框。").pack(anchor=tk.W)

        body = ttk.Frame(f)
        body.pack(fill=tk.BOTH, expand=True, pady=6)
        for c in get_categories():
            block = ttk.LabelFrame(body, text=c, padding=6)
            block.pack(fill=tk.X, pady=4)
            cur = self.colors.get(c, "#757575")
            self.cat_frames[c] = {}
            for col in PALETTE:
                b = tk.Button(block, width=3, height=1, bg=col, relief=tk.SOLID, bd=1,
                              command=lambda cc=c, co=col: self._set(cc, co))
                b.pack(side=tk.LEFT, padx=2, pady=2)
                if col == cur:
                    b.config(relief=tk.SUNKEN, bd=3)
                self.cat_frames[c][col] = b
            cb = tk.Button(block, text="自定义…", width=7, bg=cur,
                           command=lambda cc=c: self._custom(cc))
            cb.pack(side=tk.LEFT, padx=8)
            self.custom_btns[c] = cb

        ttk.Label(f, text="（颜色用于列表行底色，便于区分分类；过深可能影响黑字可读性）",
                  foreground="#666").pack(anchor=tk.W, pady=(4, 0))

        btns = ttk.Frame(f)
        btns.pack(pady=10)
        ttk.Button(btns, text="重置默认", command=self._reset).pack(side=tk.LEFT, padx=8)
        ttk.Button(btns, text="确定", command=self._ok).pack(side=tk.LEFT, padx=8)

    def _set(self, cat, col):
        """选中某个调色板颜色：更新数据 + 高亮当前块 + 同步“自定义”按钮底色。"""
        self.colors[cat] = col
        for co, b in self.cat_frames[cat].items():
            b.config(relief=tk.SUNKEN if co == col else tk.SOLID, bd=3 if co == col else 1)
        if cat in self.custom_btns:
            self.custom_btns[cat].config(bg=col)

    def _custom(self, cat):
        """原生取色器：先释放本窗口的 grab，避免取色器被抢占而无法点击。"""
        self.top.grab_release()
        try:
            res = tk.colorchooser.askcolor(initialcolor=self.colors.get(cat, "#757575"),
                                           parent=self.top)
        finally:
            self.top.grab_set()
        if res and res[1]:
            self._set(cat, res[1])

    def _reset(self):
        for c in get_categories():
            col = DEFAULT_CAT_COLORS.get(c) or PALETTE[0]
            self._set(c, col)

    def _ok(self):
        save_cat_colors(self.colors)
        self.top.destroy()


if __name__ == "__main__":
    try:
        import tkinter  # noqa
    except ImportError:
        messagebox.showerror("缺少组件", "当前 Python 未安装 tkinter，无法启动图形界面。\n"
                                  "请使用 Windows 官方 Python 安装包（勾选 tk）或 pip 安装。")
        raise

    root = tk.Tk()
    FundApp(root)
    root.mainloop()
