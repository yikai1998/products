# -*- coding: utf-8 -*-
"""
AA 账单拆分小工具（tkinter 图形界面）

功能：
  - 录入每笔消费：付款人 / 参与人（可多选）/ 金额
  - 自动按 AA 均摊计算每个人的「应收 / 应付」净额
  - 给出最简转账建议（谁转给谁多少钱）
  - 参与人名单可自由增删（不再写死）

算法说明（与原版一致，未改逻辑）：
  对每笔账单，付款人先垫付全额，参与人按人头均摊各自欠款；
  net_off = 应收总额 - 应付总额；>0 表示别人该给你，<0 表示你该给别人。
"""

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, scrolledtext

import pandas as pd
import numpy as np


def pick_cn_font(root):
    """优先挑选系统中真实存在的、能渲染中文的字体，避免 Mac/Linux 上指定
    不存在的字体（如 Windows 的“华文新魏”）导致程序直接报错。"""
    try:
        available = set(tkfont.families(root))
    except Exception:
        return ("Microsoft YaHei", 13)
    for fam in ("Microsoft YaHei", "PingFang SC", "Heiti SC", "SimHei",
                "Noto Sans CJK SC", "WenQuanYi Micro Hei", "Arial"):
        if fam in available:
            return (fam, 13)
    return ("TkDefaultFont", 13)


def validate_numeric_input(p):
    if p == "":
        return True
    if all(ch in "0123456789." for ch in p) and p.count(".") <= 1:
        try:
            float(p)
            return True
        except ValueError:
            return False
    return False


class MultiSelectDropdown(tk.Frame):
    """可动态刷新选项的多选下拉（用于选择“参与人”）。"""

    def __init__(self, parent, options, on_change=None, title="👉 选择参与人"):
        super().__init__(parent)
        self.on_change = on_change
        self.button_str = tk.StringVar(value=title)
        self.var = ""
        self.selected_vars = {}
        self.menu_frame = tk.Frame(self)
        self.button = tk.Button(self, textvariable=self.button_str, command=self.show_menu)
        self.button.grid(row=0, column=0, sticky="w")
        self._build_checks(options)

    def _build_checks(self, options):
        for w in list(self.menu_frame.children.values()):
            w.destroy()
        self.selected_vars = {opt: tk.BooleanVar() for opt in options}
        for opt in options:
            tk.Checkbutton(self.menu_frame, text=opt, variable=self.selected_vars[opt]).pack(anchor="w")
        tk.Button(self.menu_frame, text="确认", command=self.apply_selection).pack(anchor="e", pady=2)

    def refresh(self, options):
        self._build_checks(options)
        self.var = ""
        self.button_str.set("👉 选择参与人")

    def show_menu(self):
        if self.menu_frame.winfo_ismapped():
            self.menu_frame.grid_remove()
        else:
            self.menu_frame.grid(row=1, column=0, sticky="w")

    def apply_selection(self):
        selected = [o for o, v in self.selected_vars.items() if v.get()]
        self.var = ", ".join(selected)
        self.button_str.set("👉 " + self.var if selected else "👉 无人参与")
        self.menu_frame.grid_remove()
        if self.on_change:
            self.on_change()


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("AA 账单拆分工具")
        self.FONT = pick_cn_font(root)
        self.people = ["Alice", "Bob", "Carol", "Dave"]  # 默认示例，可自由增删

        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        root.rowconfigure(4, weight=1)

        self._build_participant_frame()
        self._build_table()
        self._build_input_row()
        self._build_actions()
        self._build_result()

        self._refresh_participant_controls()

    # ---------- 参与人管理 ----------
    def _build_participant_frame(self):
        f = ttk.LabelFrame(self.root, text="参与人名单（可增删）", padding=8)
        f.grid(row=0, column=0, columnspan=4, sticky="ew", padx=10, pady=(10, 4))
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text="当前名单：").grid(row=0, column=0, sticky="w")
        self.people_var = tk.StringVar(value="、".join(self.people))
        ttk.Label(f, textvariable=self.people_var, foreground="#15539e").grid(row=0, column=1, sticky="w")

        self.new_person_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.new_person_var, width=16).grid(row=0, column=2, padx=6)
        ttk.Button(f, text="➕ 添加", command=self._add_person).grid(row=0, column=3, padx=3)
        ttk.Button(f, text="➖ 删除选中", command=self._remove_person).grid(row=0, column=4, padx=3)

        self.person_combo = ttk.Combobox(f, values=self.people, width=14, state="readonly")
        self.person_combo.grid(row=0, column=5, padx=6)

    def _add_person(self):
        name = self.new_person_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "请输入要添加的成员名字")
            return
        if name in self.people:
            messagebox.showinfo("提示", f"「{name}」已在名单中")
            return
        self.people.append(name)
        self.new_person_var.set("")
        self._refresh_participant_controls()

    def _remove_person(self):
        name = self.person_combo.get()
        if not name:
            messagebox.showwarning("提示", "请在下拉框选择要删除的成员")
            return
        if len(self.people) <= 1:
            messagebox.showwarning("提示", "至少保留一名成员")
            return
        self.people.remove(name)
        self._refresh_participant_controls()

    def _refresh_participant_controls(self):
        self.people_var.set("、".join(self.people))
        # 刷新付款人下拉与参与人多选
        self.cb1["values"] = self.people
        self.cb2.refresh(self.people)
        cur = self.person_combo.get()
        self.person_combo["values"] = self.people
        if cur in self.people:
            self.person_combo.set(cur)

    # ---------- 账单表格 ----------
    def _build_table(self):
        self.tree = ttk.Treeview(self.root, columns=("payer", "members", "amount"), show="headings", height=10)
        self.tree.heading("payer", text="付款人", anchor="w")
        self.tree.heading("members", text="参与人", anchor="w")
        self.tree.heading("amount", text="金额(元)", anchor="e")
        self.tree.column("payer", width=120)
        self.tree.column("members", width=240)
        self.tree.column("amount", width=100)
        self.tree.grid(row=1, column=0, columnspan=3, sticky="nsew", padx=10, pady=4)

        sb = ttk.Scrollbar(self.root, orient="vertical", command=self.tree.yview)
        sb.grid(row=1, column=3, sticky="ns", pady=4)
        self.tree.config(yscrollcommand=sb.set)

    # ---------- 录入行 ----------
    def _build_input_row(self):
        f = ttk.Frame(self.root, padding=(10, 4))
        f.grid(row=2, column=0, columnspan=4, sticky="ew")
        for i in range(3):
            f.columnconfigure(i, weight=1)

        ttk.Label(f, text="付款人").grid(row=0, column=0, sticky="w", padx=2)
        self.cb1 = ttk.Combobox(f, values=self.people, state="readonly")
        self.cb1.grid(row=1, column=0, sticky="ew", padx=2)

        ttk.Label(f, text="参与人（多选）").grid(row=0, column=1, sticky="w", padx=2)
        self.cb2 = MultiSelectDropdown(f, self.people, on_change=self._sync_members_to_entry)
        self.cb2.grid(row=1, column=1, sticky="w", padx=2)

        ttk.Label(f, text="金额").grid(row=0, column=2, sticky="w", padx=2)
        vcmd = (self.root.register(validate_numeric_input), "%P")
        self.cb3 = tk.Entry(f, validate="key", validatecommand=vcmd)
        self.cb3.grid(row=1, column=2, sticky="ew", padx=2)

        ttk.Button(f, text="➕ 添加账单", command=self._add_row).grid(row=1, column=3, padx=6)

    def _sync_members_to_entry(self):
        pass  # 多选结果已存在 self.cb2.var，添加时直接读取

    # ---------- 操作按钮 ----------
    def _build_actions(self):
        f = ttk.Frame(self.root, padding=(10, 4))
        f.grid(row=3, column=0, columnspan=4, sticky="ew")
        ttk.Button(f, text="🧮 计算结算", command=self._calculate).pack(side="left", padx=4)
        ttk.Button(f, text="✏️ 编辑选中", command=self._edit_selected).pack(side="left", padx=4)
        ttk.Button(f, text="🗑 删除选中", command=self._delete_selected).pack(side="left", padx=4)
        ttk.Button(f, text="🧹 清空全部", command=self._clear_all).pack(side="left", padx=4)

    # ---------- 结果区 ----------
    def _build_result(self):
        ttk.Label(self.root, text="结算结果").grid(row=4, column=0, sticky="w", padx=10)
        self.result = scrolledtext.ScrolledText(self.root, wrap="word", height=10)
        self.result.grid(row=5, column=0, columnspan=4, sticky="nsew", padx=10, pady=(0, 10))

    # ---------- 业务逻辑 ----------
    def _add_row(self):
        payer = self.cb1.get()
        members = self.cb2.var
        amount = self.cb3.get().strip()
        if not payer or not members or not amount:
            messagebox.showerror("输入有误", "请填写：付款人、参与人、金额")
            return
        try:
            float(amount)
        except ValueError:
            messagebox.showerror("输入有误", "金额必须是数字")
            return
        self.tree.insert("", "end", values=(payer, members, amount))
        self.cb3.delete(0, tk.END)
        self.cb2.var = ""
        self.cb2.button_str.set("👉 选择参与人")

    def _delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选中要删除的记录")
            return
        for it in sel:
            self.tree.delete(it)

    def _edit_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选中要编辑的记录")
            return
        if len(sel) > 1:
            messagebox.showwarning("提示", "一次只能编辑一条")
            return
        values = self.tree.item(sel[0], "values")
        self.cb1.set(values[0])
        for opt, var in self.cb2.selected_vars.items():
            var.set(opt in values[1].split(", "))
        self.cb2.var = values[1]
        self.cb2.button_str.set("👉 " + values[1])
        self.cb3.delete(0, tk.END)
        self.cb3.insert(0, values[2])
        self.tree.delete(sel[0])

    def _clear_all(self):
        if not messagebox.askyesno("确认", "确定清空所有账单记录？"):
            return
        for it in self.tree.get_children():
            self.tree.delete(it)
        self.result.delete("1.0", tk.END)

    def _calculate(self):
        rows = [self.tree.item(r, "values") for r in self.tree.get_children()]
        if not rows:
            messagebox.showinfo("提示", "还没有账单记录")
            return
        if len(self.people) < 2:
            messagebox.showwarning("提示", "参与人至少需要 2 人才能结算")
            return

        n = len(self.people)
        bill_df = pd.DataFrame(data=np.zeros((n, n)), columns=self.people, index=self.people)
        for event in rows:
            payer = event[0]
            members = [m.strip() for m in event[1].split(",") if m.strip()]
            fee = float(event[2])
            unknown = [m for m in members if m not in self.people]
            if payer not in self.people:
                unknown.append(payer)
            if unknown:
                messagebox.showerror("数据异常", f"存在不在名单中的人：{', '.join(unknown)}")
                return
            aa = round(fee / len(members), 4)
            for m in members:
                bill_df.loc[payer, m] += aa
        for i in bill_df.index:
            bill_df.loc[i, i] = 0.0
        bill_df["total_receive"] = bill_df.sum(axis=1)
        bill_df["total_pay"] = bill_df.sum(axis=0)
        bill_df["net_off"] = bill_df["total_receive"] - bill_df["total_pay"]

        # 输出到界面
        self.result.delete("1.0", tk.END)
        self.result.insert(tk.END, "【每人净额】\n")
        creditors, debtors = [], []
        for name in bill_df.index:
            amount = round(float(bill_df.loc[name, "net_off"]), 2)
            if amount > 0:
                creditors.append((name, amount))
                self.result.insert(tk.END, f"  {name}：应收款 {amount} 元\n")
            elif amount < 0:
                debtors.append((name, -amount))
                self.result.insert(tk.END, f"  {name}：应付款 {abs(amount)} 元\n")
            else:
                self.result.insert(tk.END, f"  {name}：已平账\n")

        self.result.insert(tk.END, "\n【最简转账建议】\n")
        transfers = self._settle(creditors, debtors)
        if not transfers:
            self.result.insert(tk.END, "  无需转账，全部已平账。\n")
        else:
            for who, to, amt in transfers:
                self.result.insert(tk.END, f"  {who} → {to}：{amt} 元\n")

    @staticmethod
    def _settle(creditors, debtors):
        """贪心法把“谁该收 / 谁该付”拆成最简转账列表（不改变 AA 结果）。"""
        creditors = sorted(creditors, key=lambda x: -x[1])
        debtors = sorted(debtors, key=lambda x: -x[1])
        transfers = []
        ci = di = 0
        while ci < len(creditors) and di < len(debtors):
            c_name, c_amt = creditors[ci]
            d_name, d_amt = debtors[di]
            pay = min(c_amt, d_amt)
            transfers.append((d_name, c_name, round(pay, 2)))
            creditors[ci] = (c_name, c_amt - pay)
            debtors[di] = (d_name, d_amt - pay)
            if creditors[ci][1] <= 1e-6:
                ci += 1
            if debtors[di][1] <= 1e-6:
                di += 1
        return transfers


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.geometry("860x620")
    root.mainloop()
