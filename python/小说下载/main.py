# encoding = 'utf-8'
"""
小说下载（古龙作品）：nunu 书坊（适合外网）/ 古龙武侠网（适合非外网）

- nunu.py / gulongbbs.py 为下载核心，逻辑保持不变。
- 两个来源统一保存到 Downloads/。
- 本文件提供两种入口：
    * 图形界面（默认）：选择来源、勾选书目 / 输入代码、实时进度日志
    * 命令行（python main.py --cli）：沿用原交互流程
依赖：requests、beautifulsoup4（pip install requests beautifulsoup4）
"""

import argparse
import os
import platform
import queue
import re
import subprocess
import sys
import threading

import nunu
import gulongbbs

NUNU_BASE_URL = "https://www.kanunu8.com"
NUNU_AUTHOR_URL = "https://www.kanunu8.com/zj/10867.html"

# 统一目录：固定为脚本所在目录下的 Downloads/，不受启动时的当前工作目录影响
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(SCRIPT_DIR, "Downloads")


# ---------------------------------------------------------------------------
# 命令行模式（保留原交互逻辑）
# ---------------------------------------------------------------------------
def choose_source():
    print("\n请选择下载源：")
    print("-" * 60)
    print("1. nunu       努努书坊，适合外网")
    print("2. gulongbbs  古龙武侠网，适合非外网")
    print("-" * 60)
    while True:
        choice = input("请输入 1 或 2：").strip().lower()
        if choice in ["1", "nunu"]:
            return "nunu"
        if choice in ["2", "gulongbbs", "gulong"]:
            return "gulongbbs"
        print("输入无效，请重新输入。")


def run_nunu():
    print("\n当前使用：努努书坊 nunu")
    print("正在获取作者作品页...")
    html = nunu.get_html(url=NUNU_AUTHOR_URL)
    books = nunu.parse_books(html, url=NUNU_BASE_URL)
    if not books:
        print("没有解析到作品列表")
        return 0
    selected_books = nunu.choose_books(books)
    if not selected_books:
        print("没有选择任何书")
        return 0
    print("\n你选择了：")
    for book in selected_books:
        print("-", book["title"])
    if input("\n确认下载？输入 y 开始：").strip().lower() != "y":
        print("已取消")
        return 0
    for book in selected_books:
        nunu.download_book(book, out_dir=DOWNLOAD_DIR)
    print("\n全部完成")
    return 1


def run_gulongbbs():
    print("\n当前使用：古龙武侠网 gulongbbs")
    print("-" * 60)
    print("请输入要下载的书籍代码，例如：ssydj （可多个：ssydj,dqjk,tddh）")
    print("-" * 60)
    text = input("请输入书籍代码：").strip()
    if not text:
        return 0
    selected_books = [b.strip() for b in re.split(r"[,，\s]+", text) if b.strip()]
    if not selected_books:
        print("没有选择任何书")
        return 0
    print("\n你选择了：")
    for book in selected_books:
        print("-", book)
    if input("\n确认下载？输入 y 开始：").strip().lower() != "y":
        print("已取消")
        return 0
    for book in selected_books:
        gulongbbs.download_book(book, out_dir=DOWNLOAD_DIR)
    print("\n全部完成")
    return 1


def run_cli():
    source = choose_source()
    if source == "nunu":
        run_nunu()
    elif source == "gulongbbs":
        run_gulongbbs()
    else:
        print("未知下载源")


# ---------------------------------------------------------------------------
# 图形界面
# ---------------------------------------------------------------------------
def run_gui():
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import ttk, scrolledtext, messagebox

    def pick_font(root):
        try:
            fams = set(tkfont.families(root))
        except Exception:
            return ("Microsoft YaHei", 11)
        for f in ("Microsoft YaHei", "PingFang SC", "Heiti SC", "SimHei", "Noto Sans CJK SC", "Arial"):
            if f in fams:
                return (f, 11)
        return ("TkDefaultFont", 11)

    root = tk.Tk()
    root.title("古龙小说下载")
    FONT = pick_font(root)
    root.minsize(640, 560)
    root.geometry("640x600")

    # 底部按钮独立容器：先 pack 到底部，保证任何窗口尺寸下都完整可见
    btn_frame = ttk.Frame(root)
    btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=8)

    # 主内容区占据剩余空间
    main_frame = ttk.Frame(root)
    main_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
    main_frame.columnconfigure(1, weight=1)
    main_frame.rowconfigure(2, weight=1)   # 作品列表可拉伸
    main_frame.rowconfigure(5, weight=1)   # 进度日志可拉伸

    source_var = tk.StringVar(value="nunu")
    books_cache = {"nunu": []}
    log_queue = queue.Queue()

    # 来源
    ttk.Label(main_frame, text="下载源").grid(row=0, column=0, sticky="w", padx=8, pady=6)
    ttk.Radiobutton(main_frame, text="努努书坊（外网）", variable=source_var, value="nunu").grid(
        row=0, column=1, sticky="w")
    ttk.Radiobutton(main_frame, text="古龙武侠网（非外网）", variable=source_var, value="gulongbbs").grid(
        row=0, column=2, sticky="w")

    # nunu 作品列表
    ttk.Label(main_frame, text="作品列表（努努，可多选）").grid(
        row=1, column=0, columnspan=3, sticky="w", padx=8)
    list_frame = ttk.Frame(main_frame)
    list_frame.grid(row=2, column=0, columnspan=3, sticky="nsew", padx=8)
    list_frame.rowconfigure(0, weight=1)
    list_frame.columnconfigure(0, weight=1)
    book_list = tk.Listbox(list_frame, selectmode=tk.MULTIPLE, font=FONT, height=7)
    book_list.grid(row=0, column=0, sticky="nsew")
    sb = ttk.Scrollbar(list_frame, orient="vertical", command=book_list.yview)
    sb.grid(row=0, column=1, sticky="ns")
    book_list.config(yscrollcommand=sb.set)

    # gulong 代码
    ttk.Label(main_frame, text="书籍代码（古龙武侠网，逗号分隔，如 ssydj,dqjk）").grid(
        row=3, column=0, columnspan=3, sticky="w", padx=8, pady=(6, 0))
    code_var = tk.StringVar()
    ttk.Entry(main_frame, textvariable=code_var).grid(
        row=3, column=1, columnspan=2, sticky="ew", padx=8)

    # 日志
    ttk.Label(main_frame, text=f"进度日志（保存至 {DOWNLOAD_DIR}/）").grid(
        row=4, column=0, sticky="w", padx=8)
    log = scrolledtext.ScrolledText(main_frame, wrap="word", height=8, font=FONT)
    log.grid(row=5, column=0, columnspan=3, sticky="nsew", padx=8, pady=(0, 4))

    # 子线程只往线程安全队列写字符串，绝不接触任何 Tk 对象
    class GuiLog:
        def write(self, msg):
            if msg:
                log_queue.put(str(msg))
        def flush(self):
            pass

    def drain_log():
        try:
            while True:
                msg = log_queue.get_nowait()
                log.insert(tk.END, msg)
                log.see(tk.END)
        except queue.Empty:
            pass
        root.after(80, drain_log)

    drain_log()

    def ui(fn, *args):
        """把 UI 操作调度回主线程执行（Tkinter 只能在主线程触碰）。"""
        root.after(0, fn, *args)

    def fetch_books():
        # 校验在主线程完成
        if source_var.get() != "nunu":
            messagebox.showinfo("提示", "作品列表仅努努书坊可用；古龙武侠网请直接填书籍代码。")
            return

        def fill(books):
            books_cache["nunu"] = books
            book_list.delete(0, tk.END)
            for b in books:
                book_list.insert(tk.END, b["title"])

        def fail(e):
            messagebox.showerror("获取失败", str(e))

        def work():
            try:
                html = nunu.get_html(url=NUNU_AUTHOR_URL)
                books = nunu.parse_books(html, url=NUNU_BASE_URL)
                ui(fill, books)
            except Exception as e:  # noqa
                ui(fail, e)

        btn_fetch.config(state="disabled")
        def run():
            try:
                work()
            finally:
                ui(lambda: btn_fetch.config(state="normal"))
        threading.Thread(target=run, daemon=True).start()

    def download():
        src = source_var.get()
        # 校验在主线程完成，避免子线程里弹 messagebox
        if src == "nunu":
            sel = book_list.curselection()
            books = [books_cache["nunu"][i] for i in sel]
            if not books:
                messagebox.showwarning("提示", "请在作品列表中勾选要下载的书")
                return
        else:
            text = code_var.get().strip()
            codes = [c.strip() for c in re.split(r"[,，\s]+", text) if c.strip()]
            if not codes:
                messagebox.showwarning("提示", "请填写书籍代码")
                return

        def run():
            old = sys.stdout
            sys.stdout = GuiLog()
            try:
                if src == "nunu":
                    for b in books:
                        nunu.download_book(b, out_dir=DOWNLOAD_DIR)
                else:
                    for c in codes:
                        gulongbbs.download_book(c, out_dir=DOWNLOAD_DIR)
                print("\n全部完成")
            except Exception as e:  # noqa
                print("出错：", e)
            finally:
                sys.stdout = old
                ui(lambda: btn_download.config(state="normal"))

        btn_download.config(state="disabled")
        threading.Thread(target=run, daemon=True).start()

    def open_dir():
        target = DOWNLOAD_DIR if os.path.isdir(DOWNLOAD_DIR) else os.getcwd()
        try:
            if platform.system() == "Windows":
                os.startfile(target)
            elif platform.system() == "Darwin":
                subprocess.call(["open", target])
            else:
                subprocess.call(["xdg-open", target])
        except Exception as e:  # noqa
            messagebox.showerror("打开失败", str(e))

    btn_fetch = ttk.Button(btn_frame, text="🔄 获取作品列表", command=fetch_books)
    btn_fetch.pack(side=tk.LEFT, padx=(0, 4))
    btn_download = ttk.Button(btn_frame, text="⬇ 开始下载", command=download)
    btn_download.pack(side=tk.LEFT, padx=4)
    ttk.Button(btn_frame, text="📂 打开下载目录", command=open_dir).pack(side=tk.LEFT, padx=4)

    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="古龙小说下载")
    parser.add_argument("--cli", action="store_true", help="使用原命令行交互模式（默认启动图形界面）")
    args = parser.parse_args()
    if args.cli:
        run_cli()
    else:
        run_gui()


if __name__ == "__main__":
    main()
