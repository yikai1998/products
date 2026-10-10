import os
import sys


PASSWORD = "mysecretpassword"
FOLDER_NAME = "MyPrivateData"
CLSID = "{21EC2020-3AEA-1069-A2DD-08002B30309D}"  # Windows 系统里“控制面板”的身份证号, 即使露出来了，Windows 也以为它是“控制面板”
LOCKED_NAME = f"{FOLDER_NAME}.{CLSID}"


def unlock():
    input_pwd = input("请输入解锁密码: ")
    if input_pwd == PASSWORD:
        if os.path.exists(LOCKED_NAME):
            # 取消系统隐藏属性并还原名称
            os.system(f'attrib -h -s "{LOCKED_NAME}"')
            os.rename(LOCKED_NAME, FOLDER_NAME)
            print(f"解锁成功！文件夹 '{FOLDER_NAME}' 已显现。")
        else:
            print("文件夹已经是解锁状态，或不存在。")
    else:
        print("密码错误！")


def lock():
    if os.path.exists(FOLDER_NAME):
        os.rename(FOLDER_NAME, LOCKED_NAME)
        """当你在资源管理器里勾选“显示隐藏文件”时，Windows只展示普通隐藏文件。Windows依然会帮你把这个文件夹藏得死死的，因为它觉得：“这是系统命脉，不能给用户看，万一被删了电脑就蓝屏了！”
        除非有人专门去设置里把“隐藏受保护的操作系统文件”的勾给去掉，它才会露出来。"""
        os.system(f'attrib +h +s "{LOCKED_NAME}"')
        print("锁定成功！文件夹已隐藏伪装。")
    elif os.path.exists(LOCKED_NAME):
        print("文件夹已经是锁定隐藏状态。")
    else:
        # 如果文件夹不存在，自动创建
        os.makedirs(FOLDER_NAME)
        print(f"已为你创建新文件夹 '{FOLDER_NAME}'，请将隐私文件放入其中后再运行此脚本锁定。")


if __name__ == "__main__":
    print("=== U盘文件夹密码控制助手 ===")
    print("1. 解锁/显示文件夹")
    print("2. 锁定/隐藏文件夹")
    choice = input("请选择操作 (1/2): ").strip()

    if choice == "1":
        unlock()
    elif choice == "2":
        lock()
    else:
        print("无效输入。")
