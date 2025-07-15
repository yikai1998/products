import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
import pandas as pd
import numpy as np


def validate_numeric_input(p):
    if p == '':
        return True
    if all(char in '0123456789.' for char in p):
        if p.count('.') <= 1:
            return True
    return False


def add_row():
    values = [cb1.get(), cb2.var, cb3.get()]
    if any([values[0] == '', values[1] == '', values[2] == '']):
        messagebox.showerror("Invalid Input", "Please enter valid info!")
        return 0
    tree.insert('', 'end', values=values)


def calculate():
    bill_raw = [tree.item(r, 'values') for r in tree.get_children()]
    print(bill_raw)

    number = len(people_list)
    bill_df = pd.DataFrame(data=np.array([[0.0] * number] * number), columns=people_list, index=people_list)
    for event in bill_raw:
        payer = event[0]
        member = event[1].split(', ')
        fee = float(event[2])
        aa_amount = round(fee / len(member), 2)
        for m in member:
            bill_df.loc[bill_df.index == payer, m] += aa_amount
    for i in bill_df.index:
        bill_df.loc[i, i] = 0
    bill_df['total_receive'] = bill_df.sum(axis=1)
    bill_df['total_pay'] = bill_df.sum(axis=0)
    bill_df['net_off'] = bill_df['total_receive'] - bill_df['total_pay']
    print(bill_df)

    print('>> 结论：')
    for name in bill_df.index:
        amount = round(bill_df.loc[bill_df.index == name, 'net_off'].values[0], 2)
        pay_rev = '应收款 ' if amount > 0 else '应付款 '
        print(f'{name} {pay_rev}{abs(amount)}(元)')


class MultiSelectDropdown(tk.Frame):
    def __init__(self, parent, options, title='👉无人参与'):
        super().__init__(parent)
        self.options = options
        self.button_str = tk.StringVar(value=title)
        self.var = ''
        self.selected_vars = {option: tk.BooleanVar() for option in options}
        self.button = tk.Button(self, textvariable=self.button_str, command=self.show_menu)
        self.button.grid(row=3, column=1)
        self.menu_frame = tk.Frame(self)

        for option in options:
            checkbox = tk.Checkbutton(self.menu_frame, text=option, variable=self.selected_vars[option])
            checkbox.pack(anchor='w')

        self.submit_button = tk.Button(self.menu_frame, text='确认', command=self.apply_selection)
        self.submit_button.pack()

    def show_menu(self):
        if self.menu_frame.winfo_ismapped():
            self.menu_frame.grid_remove()
        else:
            self.menu_frame.grid()

    def apply_selection(self):
        selected_items = [option for option, var in self.selected_vars.items() if var.get()]
        self.var = ", ".join(selected_items) if selected_items else ''
        self.button_str.set('👉名单详情' if selected_items else '👉无人参与')
        update_selection_label()
        self.menu_frame.grid_remove()


def update_selection_label():
    selected_items = cb2.var
    selection_label.config(text=selected_items)


def delete_selected():
    selected_item = tree.selection()
    if not selected_item:
        messagebox.showerror("错误", "请先选择要删除的记录")
        return
    for item in selected_item:
        tree.delete(item)


def edit_selected():
    selected_item = tree.selection()
    if not selected_item:
        messagebox.showerror("错误", "请先选择要编辑的记录")
        return
    if len(selected_item) > 1:
        messagebox.showerror("错误", "一次只能编辑一条记录")
        return

    # 获取选中行的值
    values = tree.item(selected_item[0], 'values')

    # 填充到输入框
    cb1.set(values[0])

    # 处理参与人（多选框）
    participants = values[1].split(', ')
    for option, var in cb2.selected_vars.items():
        var.set(option in participants)
    cb2.var = values[1]
    update_selection_label()

    # 填充金额
    cb3.delete(0, tk.END)
    cb3.insert(0, values[2])

    # 删除选中行，用户可以修改后重新添加
    tree.delete(selected_item[0])


# main structure of windows
root = tk.Tk()
root.title("AA Bill Tool")
root.columnconfigure(0, weight=1)
root.columnconfigure(1, weight=1)
root.columnconfigure(2, weight=1)
root.columnconfigure(3, weight=1)
root.rowconfigure(0, weight=1)
root.rowconfigure(1, weight=1)
root.rowconfigure(2)
root.rowconfigure(3)
root.rowconfigure(4)
root.rowconfigure(5)

# data table
tree = ttk.Treeview(root, columns=('Column 1', 'Column 2', 'Column 3'), show='headings')
tree.heading('Column 1', text='付款人', anchor='e')
tree.heading('Column 2', text='参与人')
tree.heading('Column 3', text='金额')
tree.column('Column 1', width=100)
tree.column('Column 2', width=100)
tree.column('Column 3', width=100)
tree.grid(row=0, column=0, sticky="nsew", padx=10, pady=10, columnspan=3, rowspan=2)

people_list = ['Bella', 'Cynthia', 'Emma', 'Simonr']

# scroll bar
scrollbar = ttk.Scrollbar(root, orient="vertical", command=tree.yview)
scrollbar.grid(row=0, column=3, sticky="nsew", padx=10, pady=10, rowspan=2)
tree.config(yscrollcommand=scrollbar.set)

# dropdown menu and string-box used for input
tk.Label(root, text='付款人', font='华文新魏 13 bold').grid(row=2, column=0, sticky="nsw", padx=10, pady=10)
tk.Label(root, text='参与人', font='华文新魏 13 bold').grid(row=2, column=1, sticky="nsw", padx=10, pady=10)
tk.Label(root, text='金额', font='华文新魏 13 bold').grid(row=2, column=2, sticky="nsw", padx=10, pady=10)
cb1 = ttk.Combobox(root, values=people_list)
cb2 = MultiSelectDropdown(parent=root, options=people_list)
vcmd = (root.register(validate_numeric_input), '%P')
cb3 = tk.Entry(root, validate='key', validatecommand=vcmd)
cb1.grid(row=3, column=0, sticky="nsew", padx=10, pady=10)
cb2.grid(row=4, column=1, sticky="nsew", padx=10, pady=10)
cb3.grid(row=3, column=2, sticky="nsew", padx=10, pady=10)


selection_label = tk.Label(root, text='')
selection_label.grid(row=3, column=1, sticky="nsew", padx=10, pady=10)

# add-on button
add_button = ttk.Button(root, text="Add Row", command=add_row)
add_button.grid(row=2, column=3, sticky="nsew", padx=10, pady=10)

# calculate button
calculate_button = ttk.Button(root, text="Generate Bill", command=calculate)
calculate_button.grid(row=3, column=3, sticky="nsew", padx=10, pady=10)

# edit button
delete_button = ttk.Button(root, text="Removed Selected", command=delete_selected)
delete_button.grid(row=4, column=3, sticky="nsew", padx=10, pady=10)
edit_button = ttk.Button(root, text="Edit Selected", command=edit_selected)
edit_button.grid(row=5, column=3, sticky="nsew", padx=10, pady=10)

root.geometry('1200x400')
root.attributes('-topmost', True)
root.focus_force()  # 强制获取焦点
root.after(5000, lambda: root.attributes('-topmost', False))  # 5秒后允许被其它窗口覆盖
root.mainloop()
