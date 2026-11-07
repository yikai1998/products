# -*- coding: utf-8 -*-
"""
文件格式转换：把 HEIC / HEIF 照片批量转成 JPEG，并清洗文件名。

原逻辑保留：HEIC/HEIF -> JPEG(quality=95) + 文件名规整（空格/连字符/特殊字符 -> 下划线）。
改进：
  - 源码转 UTF-8（原 GBK，GitHub 上中文会乱码）
  - 输入/输出目录可配置（命令行参数 或 图形界面选择），不再硬编码 F:\
  - 同名文件安全处理：默认自动加 _1/_2 后缀，避免悄悄覆盖
  - 可选简易 tkinter 界面（文件夹选择 + 日志）
依赖：Pillow、pillow-heif（pip install Pillow pillow-heif）；tqdm 与 tkinter 均为可选。
"""

import argparse
import os
import re
import shutil
import sys

from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener()

INPUT_EXTS = (".heic", ".heif")
OUTPUT_EXT = ".jpg"
SUPPORT_TQDM = False
try:
    from tqdm import tqdm
    SUPPORT_TQDM = True
except Exception:
    pass


def clean_filename(filename: str) -> str:
    """规整文件名：
    - 空格 -> 下划线
    - 连续连字符 -> 单个下划线
    - 非(字母/数字/中文/下划线) -> 下划线
    - 合并连续下划线 -> 单个
    - 去掉首尾下划线
    """
    name, ext = os.path.splitext(filename)
    name = name.replace(" ", "_")
    name = re.sub(r"-+", "_", name)
    name = re.sub(r"[^\w\u4e00-\u9fa5]", "_", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_")
    if not name:
        name = "unnamed"
    return name + ext


def _unique_path(output_path: str, overwrite: bool):
    """若目标已存在：overwrite=True 直接覆盖；否则追加 _1/_2 后缀。"""
    if overwrite or not os.path.exists(output_path):
        return output_path
    base, ext = os.path.splitext(output_path)
    i = 1
    while os.path.exists(f"{base}_{i}{ext}"):
        i += 1
    return f"{base}_{i}{ext}"


def convert_folder(input_folder: str, output_folder: str, overwrite: bool = False, log=print):
    os.makedirs(output_folder, exist_ok=True)
    files = [f for f in os.listdir(input_folder) if f.lower().endswith(INPUT_EXTS)]
    if not files:
        log(f"在 {input_folder} 未找到 HEIC/HEIF 文件。")
        return 0, 0

    iterator = tqdm(files, desc="转换中") if SUPPORT_TQDM and log is print else files
    converted = skipped = 0
    for filename in iterator:
        in_path = os.path.join(input_folder, filename)
        clean = clean_filename(os.path.splitext(filename)[0]) + OUTPUT_EXT
        out_path = _unique_path(os.path.join(output_folder, clean), overwrite)
        try:
            img = Image.open(in_path)
            img.convert("RGB").save(out_path, "JPEG", quality=95)
            shutil.copystat(in_path, out_path)
            tag = " (覆盖)" if out_path == os.path.join(output_folder, clean) and os.path.exists(out_path) else ""
            log(f"✓ {filename} -> {os.path.basename(out_path)}{tag}")
            converted += 1
        except Exception as e:  # noqa
            log(f"✗ {filename} 失败：{e}")
            skipped += 1
    log(f"\n转换完成：成功 {converted} 个，失败 {skipped} 个。")
    return converted, skipped


# ---------------------------------------------------------------------------
# 图形界面
# ---------------------------------------------------------------------------
def run_gui():
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import ttk, filedialog, scrolledtext, messagebox

    def pick_font(root):
        try:
            fams = set(tkfont.families(root))
        except Exception:
            return ("Microsoft YaHei", 12)
        for f in ("Microsoft YaHei", "PingFang SC", "Heiti SC", "SimHei", "Noto Sans CJK SC", "Arial"):
            if f in fams:
                return (f, 12)
        return ("TkDefaultFont", 12)

    def choose(which):
        d = filedialog.askdirectory()
        if d:
            (in_var if which == "in" else out_var).set(d)

    def start():
        inf, outf = in_var.get(), out_var.get()
        if not inf or not outf:
            messagebox.showwarning("提示", "请先选择输入和输出文件夹")
            return
        log_area.delete("1.0", tk.END)

        class _Log:
            @staticmethod
            def write(msg):
                log_area.insert(tk.END, msg + "\n")
                log_area.see(tk.END)

        convert_folder(inf, outf, overwrite=overwrite_var.get(), log=_Log.write)

    root = tk.Tk()
    root.title("HEIC/HEIF → JPEG 批量转换")
    FONT = pick_font(root)
    root.columnconfigure(1, weight=1)

    in_var, out_var = tk.StringVar(), tk.StringVar()
    overwrite_var = tk.BooleanVar(value=False)

    ttk.Label(root, text="输入文件夹").grid(row=0, column=0, sticky="w", padx=8, pady=6)
    ttk.Entry(root, textvariable=in_var).grid(row=0, column=1, sticky="ew", padx=6)
    ttk.Button(root, text="浏览", command=lambda: choose("in")).grid(row=0, column=2, padx=6)

    ttk.Label(root, text="输出文件夹").grid(row=1, column=0, sticky="w", padx=8, pady=6)
    ttk.Entry(root, textvariable=out_var).grid(row=1, column=1, sticky="ew", padx=6)
    ttk.Button(root, text="浏览", command=lambda: choose("out")).grid(row=1, column=2, padx=6)

    ttk.Checkbutton(root, text="覆盖同名文件（不勾则自动加 _1/_2 后缀）", variable=overwrite_var).grid(
        row=2, column=0, columnspan=3, sticky="w", padx=8, pady=4)

    ttk.Button(root, text="▶ 开始转换", command=start).grid(row=3, column=0, columnspan=3, pady=8)

    log_area = scrolledtext.ScrolledText(root, wrap="word", height=14)
    log_area.grid(row=4, column=0, columnspan=3, sticky="nsew", padx=8, pady=(0, 8))
    root.rowconfigure(4, weight=1)

    root.geometry("640x460")
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="HEIC/HEIF -> JPEG 批量转换")
    parser.add_argument("-i", "--input", help="输入文件夹（含 HEIC/HEIF）")
    parser.add_argument("-o", "--output", help="输出文件夹")
    parser.add_argument("--overwrite", action="store_true", help="覆盖同名文件（默认自动加后缀）")
    args = parser.parse_args()

    if args.input and args.output:
        convert_folder(args.input, args.output, overwrite=args.overwrite)
    else:
        run_gui()


if __name__ == "__main__":
    main()
