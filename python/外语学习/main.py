# -*- coding: utf-8 -*-
"""
外语单词背诵 + 朗读 + 翻译（跨平台：GUI / CLI 两用）

核心逻辑保持不变：
  - 从 wording_en.txt / wording_jp.txt 随机抽取若干单词
  - 联网翻译（外网用 GoogleTranslator，内网用 translators 的 bing）
  - 用 pyttsx3 朗读

改进：
  - 语音包不再硬编码 Mac 嗓音，改为按语言自动匹配系统中可用的嗓音（Win/Mac/Linux 均可）
  - 提供可选的 tkinter 图形界面；无参数运行时默认启动 GUI，--cli 走原命令行流程
依赖：pyttsx3、deep_translator、translators（pip install pyttsx3 deep_translator translators）
"""

import argparse
import random

import pyttsx3
from deep_translator import GoogleTranslator
import translators as ts

VOICE_HINTS = {
    "ja": ["ja", "japanese", "日本語"],
    "en": ["en", "english", "英文"],
}


def pick_voice(engine, lang: str):
    """按语言在系统已安装嗓音里挑一个，找不到则返回 None（用默认嗓音）。"""
    voices = engine.getProperty("voices") or []
    hints = VOICE_HINTS.get(lang, [])
    for v in voices:
        blob = (getattr(v, "id", "") + " " + getattr(v, "name", "")).lower()
        if any(h in blob for h in hints):
            return v.id
    return None


def get_translation(text: str, internet: str) -> str:
    try:
        if internet == "2":
            return GoogleTranslator(source="auto", target="zh-CN").translate(text)
        return ts.translate_text(text, translator="bing", to_language="zh-CHS")
    except Exception as e:  # noqa
        return f"翻译失败：{e}"


def speak(engine, text: str, lang: str):
    try:
        vid = pick_voice(engine, lang)
        if vid:
            engine.setProperty("voice", vid)
        engine.setProperty("rate", 90)
        engine.setProperty("volume", 1)
        engine.say(text)
        engine.runAndWait()
    except Exception as e:  # noqa
        print(f"朗读失败：{e}")


def load_words(lang: str):
    path = "wording_jp.txt" if lang == "ja" else "wording_en.txt"
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def run_cli(lang: str, n: int, internet: str, read_aloud: bool):
    words = load_words(lang)
    if not (0 < n <= len(words)):
        n = len(words)
    sample = random.sample(words, n)
    engine = pyttsx3.init() if read_aloud else None
    print(f"一共抽取 {len(sample)} 个单词")
    for c, w in enumerate(sample, 1):
        print(f"\n{c}/{len(sample)}: {w}")
        if read_aloud:
            input("按回车朗读…")
            speak(engine, w, lang)
        input("按回车显示翻译…")
        print("翻译：", get_translation(w, internet))
    if engine:
        engine.stop()
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
    root.title("外语单词背诵")
    FONT = pick_font(root)
    root.columnconfigure(1, weight=1)

    lang_var = tk.StringVar(value="英语")
    net_var = tk.StringVar(value="内网")
    n_var = tk.StringVar(value="10")
    read_var = tk.BooleanVar(value=True)

    ttk.Label(root, text="语言").grid(row=0, column=0, sticky="w", padx=8, pady=6)
    ttk.Combobox(root, textvariable=lang_var, values=["英语", "日语"], state="readonly", width=12).grid(
        row=0, column=1, sticky="w")

    ttk.Label(root, text="网络环境").grid(row=1, column=0, sticky="w", padx=8, pady=6)
    ttk.Combobox(root, textvariable=net_var, values=["内网", "外网"], state="readonly", width=12).grid(
        row=1, column=1, sticky="w")

    ttk.Label(root, text="抽取数量").grid(row=2, column=0, sticky="w", padx=8, pady=6)
    ttk.Entry(root, textvariable=n_var, width=14).grid(row=2, column=1, sticky="w")

    ttk.Checkbutton(root, text="朗读", variable=read_var).grid(row=3, column=0, columnspan=2, sticky="w", padx=8)

    # 展示区
    word_label = ttk.Label(root, text="", font=(FONT[0], 28), anchor="center")
    word_label.grid(row=4, column=0, columnspan=3, sticky="ew", padx=8, pady=10)
    trans_label = ttk.Label(root, text="", font=(FONT[0], 16), foreground="#15539e", anchor="center", wraplength=460)
    trans_label.grid(row=5, column=0, columnspan=3, sticky="ew", padx=8, pady=4)
    progress_label = ttk.Label(root, text="", foreground="#888")
    progress_label.grid(row=6, column=0, columnspan=3, sticky="e", padx=8)

    state = {"sample": [], "idx": 0, "engine": None}

    def start():
        lang = "ja" if lang_var.get() == "日语" else "en"
        internet = "2" if net_var.get() == "外网" else "1"
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
        if read_var.get():
            state["engine"] = pyttsx3.init()
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
        if state["engine"]:
            speak(state["engine"], s[i], "ja" if lang_var.get() == "日语" else "en")

    def reveal():
        if not state["sample"]:
            return
        internet = "2" if net_var.get() == "外网" else "1"
        lang = "ja" if lang_var.get() == "日语" else "en"
        trans_label.config(text="翻译中…")
        root.update_idletasks()
        trans_label.config(text=get_translation(state["sample"][state["idx"]], internet))

    def speak_now():
        if not state["sample"]:
            return
        if not state["engine"]:
            state["engine"] = pyttsx3.init()
        speak(state["engine"], state["sample"][state["idx"]], "ja" if lang_var.get() == "日语" else "en")

    def nxt():
        if not state["sample"]:
            return
        if state["idx"] + 1 < len(state["sample"]):
            state["idx"] += 1
            trans_label.config(text="")
            show_current()
        else:
            messagebox.showinfo("完成", "复习结束 🎉")
            if state["engine"]:
                state["engine"].stop()

    ttk.Button(root, text="▶ 开始", command=start).grid(row=7, column=0, padx=8, pady=8)
    ttk.Button(root, text="🔊 朗读", command=speak_now).grid(row=7, column=1, padx=4)
    ttk.Button(root, text="👁 显示翻译", command=reveal).grid(row=7, column=2, padx=4)
    ttk.Button(root, text="➡ 下一词", command=nxt).grid(row=7, column=3, padx=4)

    root.geometry("520x360")
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="外语单词背诵 + 朗读 + 翻译")
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
