# coding=gbk
"""
企业微信 5h 保活小工具
防止电脑端 15 min 无操作变“离开”状态。
启动后 15 s 倒计时 → 每 3 min 自动在当前光标处输入 Hi Team, 并逐字回删，全程模拟真人键盘，100 轮后（≈5 h）自动结束。
鼠标甩到左上角立即急停，零配置、零依赖（仅 pyautogui）
"""

import pyautogui
import time

# 1. 弹窗提示
msg = ("脚本将在 15 秒后开始运行\n"
       "稳妥起见, 请先把企业微信置于最前端窗口\n"
       "再打开你自己的聊天窗口, 然后回到本界面按回车"
       "确保鼠标指针落在窗口内, 静静等待即可\n"
       "之后每 3 分钟会自动打字/删字, 保持在线"
       "记住: 鼠标甩到左上角可紧急中止")
_ = input(msg + "\n按回车继续 ...")

# 2. 倒数 15 秒
for t in range(15, 0, -1):
    print(f"\r正式启动倒计时 {t:2d} s ...", end="")  # "\r"会把光标拖回当前行开头, 不会换行
    time.sleep(1)
print("\r开始自动循环, 按 Ctrl+C 退出。")

# 3. 无限循环保活
pyautogui.FAILSAFE = True   # 鼠标甩到左上角可紧急中止, 之后所有 pyautogui 的鼠标/键盘操作都会受它保护
interval = 180
total_rounds = 100  # 100 轮 ≈ 5 小时

for n in range(1, total_rounds + 1):
    # 打字
    pyautogui.write(message="Hi Team,", interval=0.05)
    time.sleep(2)  # 留一点“人类”停顿
    # 删光
    pyautogui.press(keys="backspace", presses=8, interval=0.5)

    print(f"[{time.strftime('%H:%M:%S')}] 已完成一次 `Hi Team,/删除`")
    time.sleep(interval)


print("五小时保活结束，脚本正常退出。")