# -*- coding: utf-8 -*-
"""
基金走势分析 · 图形界面
======================
用 funds.json 管理自选基金，并与「基金代码名单_*.txt」双向同步：
  - UI 里增 / 删 / 改分类 → 同时写回 funds.json 和各分类 txt；
  - 你手动在 txt 里加的代码 → 下次打开 UI 自动读进来（保留已跑过的更新/信号）。

功能：
  - 按基金代码添加（自动联网查名称与类型）、删除、分类
  - 分类标签可“改名 / 新增 / 删除空标签”（🏷 管理分类）；选中基金可“转移到其它分类”（🔁 转移分类）
  - 单只基金设“今日预测涨幅(%)”，分析时仅对该基金生效（临时展示，不污染历史数据）
  - 一键批量 / 单只分析（后台线程，界面不卡）
  - 列表直接看「类型 / 最新净值 / 估值分位 / 最新信号 / 预测% / 上次更新」
  - 按钮或双击直接打开报告文件夹
  - 默认每次分析都联网抓“最新”净值；断网时可勾“离线模式”只读本地缓存

运行：python gui.py   （需已安装 akshare / pandas / matplotlib / tkinter）
"""

import os
import sys
import json
import queue
import subprocess
import threading
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
# 名单：funds.json 为权威源（含运行信息），txt 为可读镜像，双向同步
# ----------------------------------------------------------------------------
def _read_txt_codes():
    """扫描所有 基金代码名单_*.txt，返回 {code: (name, category)}。"""
    result = {}
    if not os.path.isdir(BASE):
        return result
    for fn in os.listdir(BASE):
        if fn.startswith("基金代码名单_") and fn.endswith(".txt"):
            cat = fn[len("基金代码名单_"):-len(".txt")]
            try:
                with open(os.path.join(BASE, fn), encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        parts = line.split()
                        code = parts[0].zfill(6)
                        name = parts[1] if len(parts) > 1 else ""
                        result[code] = (name, cat)
            except Exception:
                continue
    return result


def load_list():
    """加载名单，并把 txt 中新增/缺名的代码并入（保留 json 中的运行信息）。"""
    items = []
    if os.path.exists(LIST_PATH):
        with open(LIST_PATH, encoding="utf-8") as f:
            items = json.load(f)
    existing = {it["code"]: it for it in items}
    for code, (name, cat) in _read_txt_codes().items():
        if code in existing:
            if not existing[code].get("name") and name:
                existing[code]["name"] = name
        else:
            existing[code] = {"code": code, "name": name, "category": cat}
    items = list(existing.values())
    save_list(items)  # 把合并结果落盘
    return items


def save_list(items):
    """同时写 funds.json 与各分类 txt（双向同步）。"""
    with open(LIST_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    by_cat = {}
    for it in items:
        by_cat.setdefault(it.get("category", "其它"), []).append(it)
    for cat, lst in by_cat.items():
        p = os.path.join(BASE, f"基金代码名单_{cat}.txt")
        with open(p, "w", encoding="utf-8") as f:
            for it in lst:
                f.write(f"{it['code']}\t{it.get('name', '')}\n")


# ----------------------------------------------------------------------------
# 主界面
# ----------------------------------------------------------------------------
class FundApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("基金走势分析")
        self.root.geometry("1060x640")

        self.items = load_list()
        self.q = queue.Queue()
        self.worker = None

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
        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=6, fill=tk.Y)
        ttk.Button(top, text="🔁 转移分类", command=self._transfer_category).pack(side=tk.LEFT, padx=3)
        ttk.Button(top, text="🏷 管理分类", command=self._manage_categories).pack(side=tk.LEFT, padx=3)

        hint = ttk.Label(
            self.root,
            text="默认每次都联网抓最新净值；断网时勾“离线模式”只读本地缓存。多选后点“开始分析选中”批量跑；"
                 "单选一只并“设今日预测”可对该基金单独预测。双击某行打开报告；鼠标悬停某行看详情。"
                 "报告里的「走势图.html」支持顶部日期筛选（From/To）与上下两图滑块联动，指数基金额外显示跟踪指数 PE 分位。",
            foreground="#666",
        )
        hint.pack(fill=tk.X, padx=8)

        # 列表
        cols = ("code", "name", "category", "type", "latest_nav", "valuation", "signal", "predict", "updated")
        self.tree = ttk.Treeview(self.root, columns=cols, show="headings", selectmode="extended")
        headers = {
            "code": "代码", "name": "名称", "category": "分类", "type": "类型",
            "latest_nav": "最新净值", "valuation": "估值分位", "signal": "估值结论",
            "predict": "预测%", "updated": "上次更新",
        }
        widths = {"code": 78, "name": 230, "category": 60, "type": 70, "latest_nav": 80,
                  "valuation": 80, "signal": 150, "predict": 60, "updated": 100}
        for c in cols:
            self.tree.heading(c, text=headers[c])
            self.tree.column(c, width=widths[c], anchor=tk.CENTER if c not in ("name", "signal") else tk.W)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)
        self.tree.bind("<Double-1>", lambda e: self._open_selected())
        self.tree.bind("<Motion>", self._on_motion)
        self.tree.bind("<Leave>", lambda e: self._hide_tip())

        # 日志
        bottom = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        bottom.pack(fill=tk.BOTH, expand=True)
        ttk.Label(bottom, text="运行日志：").pack(anchor=tk.W)
        self.log = scrolledtext.ScrolledText(bottom, height=9, state=tk.DISABLED)
        self.log.pack(fill=tk.BOTH, expand=True)

    # ---- 列表刷新 ----
    def _refresh_tree(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for it in self.items:
            pred = it.get("predict_today")
            pred_txt = "" if pred is None else f"{pred:+.2f}"
            self.tree.insert(
                "", tk.END, iid=it["code"],
                values=(it["code"], it.get("name", ""), it.get("category", "其它"), it.get("type", "-"),
                        it.get("latest_nav", "-"), it.get("valuation", "-"),
                        it.get("signal", "-"), pred_txt, it.get("updated", "-")),
            )

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
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选中要删除的基金")
            return
        for code in sel:
            self.items = [i for i in self.items if i["code"] != code]
        save_list(self.items)
        self._refresh_tree()
        self._log(f"已删除 {len(sel)} 只基金（funds.json 与对应 txt 已同步）")

    def _refresh_names(self):
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
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选中要转移的基金（可多选）")
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
            save_list(self.items)  # 内部会按新分类重写各 txt
            self._refresh_tree()
            self._log(f"已将 {moved} 只基金转移到「{target}」")

    def _manage_categories(self):
        """重命名 / 新增 / 删除分类标签（改动同步到 funds.json 与各 txt 文件名）。"""
        dlg = CategoryManageDialog(self.root, self.items)
        self.root.wait_window(dlg.top)
        if dlg.changed:
            save_list(self.items)  # 重命名后按新分类重写 txt，旧名 txt 已被改名函数处理
            self._refresh_tree()
            self._log("分类标签已更新")

    # ---- 分析流程 ----
    def _start(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选中要分析的基金（可多选）")
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

    # ---- 打开报告 ----
    def _open_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选中一只基金")
            return
        code = sel[0]
        item = next((i for i in self.items if i["code"] == code), None)
        if not item:
            return
        folder = analysis.resolve_fund_dir(code, item.get("name", ""))
        if not os.path.isdir(folder):
            messagebox.showinfo("提示", "该基金还没有分析报告，请先分析。")
            return
        self._open_folder(folder)

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
        # 改名对应的 txt 文件
        old_file = os.path.join(BASE, f"基金代码名单_{old}.txt")
        new_file = os.path.join(BASE, f"基金代码名单_{new}.txt")
        if os.path.exists(old_file):
            os.rename(old_file, new_file)
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
        # 删除空 txt（若有）
        fpath = os.path.join(BASE, f"基金代码名单_{cat}.txt")
        if os.path.exists(fpath):
            os.remove(fpath)
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
