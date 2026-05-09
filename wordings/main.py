# coding = utf-8
import pyttsx3
import time
import pandas as pd
from deep_translator import GoogleTranslator
import random

while True:
    lang_choice = input("请选择朗读语言（j=日语, e=英语）：").strip().lower()
    if lang_choice not in ("j", "e"):
        print("请输入 j 或 e。")
        continue
    break
if lang_choice == "j":
    selected_voice = "com.apple.voice.compact.ja-JP.Kyoko"
    path = "wording_jp.txt"
else:
    selected_voice = "Sandy (English (UK)) | com.apple.eloquence.en-GB.Sandy"
    path = "wording_en.txt"

with open(path, "r", encoding="utf-8") as f:
    base = [line.strip() for line in f if line.strip()]
print(f"一共{len(base)}个单词。")

while True:
    s = input("你计划抽几个单词：").strip()
    if not s.isdigit():
        print("请输入正整数。")
        continue
    n = int(s)
    if n <= 0:
        print("数量必须大于0。")
        continue
    if n > len(base):
        print(f"数量不能大于{len(base)}。")
        continue
    break

review_list = random.sample(base, n)
translator = GoogleTranslator(source="auto", target="zh-CN")

for c, word in enumerate(review_list, 1):
    try:
        result = translator.translate(word)
    except Exception as e:
        result = f"翻译失败：{e}"
    _ = input("按回车播放读音")
    engine = pyttsx3.init()
    engine.setProperty("rate", 90)
    engine.setProperty("volume", 1)
    engine.setProperty("voice", selected_voice)
    engine.say(word)
    engine.runAndWait()
    engine.stop()
    del engine
    time.sleep(0.2)
    _ = input("按回车显示原文")
    print(f"{c}: {word}")
    _ = input("按回车显示翻译结果")
    print(f"{c}: {result}")
    if c < len(review_list):
        print("下一轮...")
        
print("复习结束。")
