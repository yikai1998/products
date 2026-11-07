# -*- coding: utf-8 -*-
"""
外语单词抽背（自查）工具：GUI / CLI 两用

用途：从 wording_en.txt / wording_jp.txt 随机抽取单词，自己先想意思，
      再按需「显示翻译」或「朗读」来核对掌握程度（听力 / 翻译均可自主触发）。

改进：
  - 朗读改用操作系统内置 TTS（Windows PowerShell / macOS say / Linux espeak），
    以子进程方式调用，不再用 pyttsx3 在主线程里 runAndWait——
    既消除朗读时的界面卡顿，也彻底避免 pyttsx3 在程序退出时
    因后台线程触发 PyEval_RestoreThread(GIL) 致命崩溃。
  - 翻译改为后台线程 + 主线程回调，联网慢也不会冻结界面。
  - 单词 / 翻译自动换行（随窗口宽度动态设置 wraplength）；底部按钮固定可见。
  - 不再自动朗读：单词先显示，是否听发音、何时看翻译完全由你点击决定。
依赖：翻译需要 deep_translator / translators（pip install deep_translator translators）；
      朗读使用系统自带语音，无需额外安装（Linux 需 espeak）。
"""

import argparse
import base64
import os
import platform
import random
import subprocess
import threading

from deep_translator import GoogleTranslator
import translators as ts

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def get_translation(text: str, internet: str) -> str:
    try:
        if internet == "2":
            return GoogleTranslator(source="auto", target="zh-CN").translate(text)
        return ts.translate_text(text, translator="bing", to_language="zh-CHS")
    except Exception as e:  # noqa
        return f"翻译失败：{e}"


_speech_lock = threading.Lock()
_last_proc = None
_mac_voices = None


def _mac_voice(lang: str):
    """在 macOS 已安装嗓音里挑一个匹配语言的，找不到返回 None（用默认嗓音）。"""
    global _mac_voices
    if _mac_voices is None:
        try:
            _mac_voices = subprocess.run(
                ["say", "-v", "?"], capture_output=True, text=True, timeout=5
            ).stdout.lower()
        except Exception:
            _mac_voices = ""
    prefer = ("kyoko", "otoya") if lang == "ja" else ("samantha", "alex", "daniel")
    for v in prefer:
        if v in _mac_voices:
            return v.capitalize() if v != "otoya" else "Otoya"
    return None


def speak(text: str, lang: str, block: bool = False):
    """调用操作系统内置 TTS 朗读（子进程，不阻塞界面，也不会引发 GIL 崩溃）。"""
    global _last_proc
    if not text:
        return
    sys_name = platform.system()
    try:
        if sys_name == "Windows":
            culture = "ja-JP" if lang == "ja" else "en-US"
            safe = text.replace("'", "''")
            # 用 EncodedCommand 传递脚本，避免中文/日文与引号在命令行上的编码问题
            ps = (
                "Add-Type -AssemblyName System.Speech\n"
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
                "try { $s.SelectVoiceByHints([System.Globalization.CultureInfo]::"
                "GetCultureInfo('%s')) } catch {}\n"
                "$s.Speak('%s')\n"
                "$s.Dispose()" % (culture, safe)
            )
            encoded = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
            p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=0x08000000)  # CREATE_NO_WINDOW
        elif sys_name == "Darwin":
            voice = _mac_voice(lang)
            cmd = ["say", "-v", voice, text] if voice else ["say", text]
            p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:  # Linux
            voice = "ja" if lang == "ja" else "en"
            p = subprocess.Popen(["espeak", "-v", voice, text],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 连点朗读时，先结束上一段，避免多个 TTS 进程叠加抢音频设备造成卡顿
        with _speech_lock:
            if _last_proc is not None and _last_proc.poll() is None:
                try:
                    _last_proc.terminate()
                except Exception:
                    pass
            _last_proc = p
        if block:
            p.wait(timeout=30)
    except Exception as e:  # noqa
        print(f"朗读失败：{e}")


def load_words(lang: str):
    path = os.path.join(BASE_DIR, "wording_jp.txt" if lang == "ja" else "wording_en.txt")
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def run_cli(lang: str, n: int, internet: str, read_aloud: bool):
    words = load_words(lang)
    if not (0 < n <= len(words)):
        n = len(words)
    sample = random.sample(words, n)
    print(f"一共抽取 {len(sample)} 个单词（先自己想意思，回车后再看翻译）")
    for c, w in enumerate(sample, 1):
        print(f"\n{c}/{len(sample)}: {w}")
        input("按回车显示翻译…")
        print("翻译：", get_translation(w, internet))
        if read_aloud:
            input("按回车朗读…")
            speak(w, lang, block=True)
    print("\n复习结束")


# ---------------------------------------------------------------------------
# 图形界面
# ---------------------------------------------------------------------------
def run_gui():
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import ttk, messagebox

    def pick_font(root):
        try:
            fams = set(tkfont.families(root))
        except Exception:
            return ("Microsoft YaHei", 14)
        for f in ("Microsoft YaHei", "PingFang SC", "Heiti SC", "SimHei", "Noto Sans CJK SC", "Arial"):
            if f in fams:
                return (f, 14)
        return ("TkDefaultFont", 14)

    root = tk.Tk()
    root.title("外语单词抽背")
    FONT = pick_font(root)
    root.minsize(520, 380)
    root.geometry("560x400")

    # 底部按钮独立容器，任何窗口尺寸下都完整可见
    btn_frame = ttk.Frame(root)
    btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=8)

    main_frame = ttk.Frame(root)
    main_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
    main_frame.columnconfigure(1, weight=1)
    main_frame.rowconfigure(4, weight=1)

    lang_var = tk.StringVar(value="英语")
    net_var = tk.StringVar(value="内网")
    n_var = tk.StringVar(value="10")
    read_var = tk.BooleanVar(value=True)

    ttk.Label(main_frame, text="语言").grid(row=0, column=0, sticky="w", padx=8, pady=6)
    ttk.Combobox(main_frame, textvariable=lang_var, values=["英语", "日语"],
                 state="readonly", width=12).grid(row=0, column=1, sticky="w")

    ttk.Label(main_frame, text="网络环境").grid(row=1, column=0, sticky="w", padx=8, pady=6)
    ttk.Combobox(main_frame, textvariable=net_var, values=["内网", "外网"],
                 state="readonly", width=12).grid(row=1, column=1, sticky="w")

    ttk.Label(main_frame, text="抽取数量").grid(row=2, column=0, sticky="w", padx=8, pady=6)
    ttk.Entry(main_frame, textvariable=n_var, width=14).grid(row=2, column=1, sticky="w")

    ttk.Checkbutton(main_frame, text="启用发音（点击「朗读」时发声）",
                    variable=read_var).grid(row=3, column=0, columnspan=2, sticky="w", padx=8)

    # 展示区
    word_label = ttk.Label(main_frame, text="点击「开始」抽取单词",
                           font=(FONT[0], 28), anchor="center", justify="center")
    word_label.grid(row=4, column=0, columnspan=3, sticky="nsew", padx=8, pady=10)
    trans_label = ttk.Label(main_frame, text="", font=(FONT[0], 16), foreground="#15539e",
                            anchor="center", justify="center")
    trans_label.grid(row=5, column=0, columnspan=3, sticky="ew", padx=8, pady=4)
    progress_label = ttk.Label(main_frame, text="", foreground="#888")
    progress_label.grid(row=6, column=0, columnspan=3, sticky="e", padx=8)

    def on_resize(event=None):
        w = root.winfo_width() - 40
        if w > 60:
            word_label.config(wraplength=w)
            trans_label.config(wraplength=w)

    root.bind("<Configure>", on_resize)

    state = {"sample": [], "idx": 0, "seq": 0}

    def start():
        lang = "ja" if lang_var.get() == "日语" else "en"
        try:
            n = int(n_var.get())
        except ValueError:
            messagebox.showwarning("提示", "数量需为整数")
            return
        try:
            words = load_words(lang)
        except FileNotFoundError:
            messagebox.showerror("错误", f"未找到 {'wording_jp.txt' if lang == 'ja' else 'wording_en.txt'}")
            return
        if not (0 < n <= len(words)):
            n = len(words)
        state["sample"] = random.sample(words, n)
        state["idx"] = 0
        state["seq"] += 1
        trans_label.config(text="")
        show_current()

    def show_current():
        s = state["sample"]
        if not s:
            return
        i = state["idx"]
        word_label.config(text=s[i])
        trans_label.config(text="")
        progress_label.config(text=f"{i + 1} / {len(s)}")

    def reveal():
        """翻译放后台线程，结果回主线程显示；用序号防止切词后结果串台。"""
        if not state["sample"]:
            return
        internet = "2" if net_var.get() == "外网" else "1"
        word = state["sample"][state["idx"]]
        state["seq"] += 1
        seq = state["seq"]
        trans_label.config(text="翻译中…")

        def work():
            result = get_translation(word, internet)
            def apply():
                if seq == state["seq"]:
                    trans_label.config(text=result)
            root.after(0, apply)

        threading.Thread(target=work, daemon=True).start()

    def speak_now():
        if not state["sample"]:
            return
        if not read_var.get():
            messagebox.showinfo("提示", "发音未启用，可在上方勾选「启用发音」")
            return
        lang = "ja" if lang_var.get() == "日语" else "en"
        speak(state["sample"][state["idx"]], lang)

    def nxt():
        if not state["sample"]:
            return
        if state["idx"] + 1 < len(state["sample"]):
            state["idx"] += 1
            state["seq"] += 1
            trans_label.config(text="")
            show_current()
        else:
            messagebox.showinfo("完成", "复习结束 🎉")

    ttk.Button(btn_frame, text="▶ 开始", command=start).pack(side=tk.LEFT, padx=(0, 4))
    ttk.Button(btn_frame, text="👁 显示翻译", command=reveal).pack(side=tk.LEFT, padx=4)
    ttk.Button(btn_frame, text="🔊 朗读", command=speak_now).pack(side=tk.LEFT, padx=4)
    ttk.Button(btn_frame, text="➡ 下一词", command=nxt).pack(side=tk.LEFT, padx=4)

    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="外语单词抽背 + 翻译（+ 可选系统发音）")
    parser.add_argument("--cli", action="store_true", help="使用命令行交互模式（默认启动图形界面）")
    parser.add_argument("--lang", choices=["en", "ja"], default="en")
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--net", choices=["1", "2"], default="1", help="1=内网 2=外网")
    parser.add_argument("--no-audio", action="store_true")
    args = parser.parse_args()

    if args.cli:
        run_cli(args.lang, args.n, args.net, not args.no_audio)
    else:
        run_gui()


if __name__ == "__main__":
    main()
