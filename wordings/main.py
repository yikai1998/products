# coding = utf-8
import pandas as pd
import random
from deep_translator import GoogleTranslator
import pyttsx3


def get_lang_voices(engine):
    voices = engine.getProperty("voices")
    lang_voices = {"japanese": [], "english": []}

    for v in voices:
        lang = str(getattr(v, "languages", ""))
        if "ja_JP" in lang or "Japanese" in v.name or "ja-JP" in v.id:
            lang_voices["japanese"].append(v)
        elif "en_US" in lang or "en_GB" in lang or "English" in v.name or "en-" in v.id:
            lang_voices["english"].append(v)

    return lang_voices


def choose_voice(voice_list, lang_name):
    if not voice_list:
        print(f"没有找到可用的{lang_name} voice。")
        return None

    print(f"\n可用的{lang_name} voice：")
    for i, v in enumerate(voice_list, 1):
        print(f"{i}. {v.name} | {v.id}")

    while True:
        s = input(f"请选择一个{lang_name} voice 编号 (0表示不用)：").strip()
        if not s.isdigit():
            print("请输入数字编号。")
            continue
        idx = int(s)
        if idx == 0:
            return 0
        if not (1 <= idx <= len(voice_list)):
            print("编号超出范围，请重新输入。")
            continue
        return voice_list[idx - 1]


# main
engine = pyttsx3.init()
lang_voices = get_lang_voices(engine)

while True:
    lang_choice = input("请选择朗读语言（j=日语, e=英语）：").strip().lower()
    if lang_choice not in ("j", "e"):
        print("请输入 j 或 e。")
        continue
    break

if lang_choice == "j":
    selected_voice = choose_voice(lang_voices["japanese"], "日语")
    path = "wording_jp.csv"
else:
    selected_voice = choose_voice(lang_voices["english"], "英语")
    path = "wording_en.csv"

base = pd.read_csv(filepath_or_buffer=path, encoding="utf-8", sep="|").iloc[:, 0].dropna().tolist()
base = [
    str(x)
    .replace("\u3000", " ")
    .replace("」「", " ")
    .replace("」", "")
    .replace("「", "")
    .strip()
    for x in base if str(x).strip()
]
print(f"一共{len(base)}个单词。")

while True:
    s = input("你计划抽几个单词：").strip()
    if not s.isdigit():
        # 如果 s.isdigit() 为真，那么 n 一定是 0 或正整数
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

    print(f"第{c}个单词： {word}")
    if selected_voice != 0:
        input("按回车播放读音")
        try:
            engine = pyttsx3.init()
            engine.setProperty("voice", selected_voice.id)
            engine.setProperty("rate", 120)
            engine.setProperty("volume", 1)
            engine.say(word)
            engine.runAndWait()
            engine.stop()
        except Exception as e:
            print(f"朗读失败：{e}")
    input("按回车显示翻译结果")
    print(result)
    if c < len(review_list):
        input("Press Enter to continue...")

print("复习结束。")
