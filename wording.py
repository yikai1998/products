# coding = utf-8
import pandas as pd
import random
from deep_translator import GoogleTranslator


base = pd.read_csv("temp.csv", encoding="utf-8").iloc[:, 0].dropna().tolist()
base = [str(x).replace("\u3000", " ").strip() for x in base if str(x).strip()]
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
translator = GoogleTranslator(source="ja", target="zh-CN")
for c, word in enumerate(review_list, 1):
    try:
        result = translator.translate(word.split(" ")[0])
    except Exception as e:
        result = f"翻译失败：{e}"
    print(f"第{c}个单词： {word}")
    input("按回车显示翻译结果")
    print(result)
    if c < len(review_list):
        input("Press Enter to continue...")

print("复习结束。")


"""学习笔记
打乱顺序 → random.shuffle(base)
随机选固定数量 → random.sample(base, n)
生成 0~1 小数列表 → [random.random() for _ in range(n)]
生成只含 0/1 的列表 → [random.randint(0, 1) for _ in range(n)]
"""
