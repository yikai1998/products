# 外语单词抽背（自查）

随机抽取单词，**先自己想意思**，再按需看翻译或听发音，用来抽查掌握程度（听力 / 翻译均可自主触发）。

## 功能

- 从 `wording_en.txt`（英语）或 `wording_jp.txt`（日语）随机抽取若干词
- 联网翻译：外网用 GoogleTranslator，内网用 translators 的 Bing
- **发音改用操作系统内置 TTS**（Windows PowerShell / macOS `say` / Linux `espeak`）调用，**无需安装 pyttsx3**：
  - 以子进程方式朗读，不阻塞界面（修复朗读时界面卡顿）
  - 彻底避免 pyttsx3 在程序退出时因后台线程触发 `PyEval_RestoreThread(GIL)` 致命崩溃
  - 按语言自动选嗓音（英文 en-US / 日文 ja-JP）；若系统未装对应语言嗓音，会使用默认嗓音
- **图形界面 + 命令行**两用
- 单词 / 翻译支持按窗口宽度**自动换行**（随窗口缩放）
- 翻译放在后台线程，联网慢也不会冻结界面；结果与「下一词」用序号校验，不会串台
- 底部四个按钮固定在窗口底部，默认尺寸下完整可见
- 单词本按**脚本所在目录**读取，从任意目录启动都能找到
- Windows 用 PowerShell `-EncodedCommand`（UTF-16LE）传参，中文/日文与引号不会乱码

## 运行

```bash
python main.py            # 默认启动图形界面
python main.py --cli      # 命令行交互模式
python main.py --cli --lang ja --n 20 --net 2   # 日语、抽20个、外网
```

参数：`--lang en|ja`、`--n 数量`、`--net 1|2`（1 内网 / 2 外网）、`--no-audio`（不朗读）。

## 依赖

```bash
pip install deep_translator translators
```

- 翻译需要联网；朗读使用系统自带语音，无需额外安装（Windows 自带 .NET System.Speech；Mac 自带 `say`；Linux 需 `sudo apt install espeak`）。
- `wording_en.txt` / `wording_jp.txt` 每行一个单词，已随仓库提供示例。

## 图形界面用法

1. 选择语言 / 网络 / 数量，勾选「启用发音」。
2. 点「开始」抽取单词（只显示单词，不自动发音）。
3. 自己想一下意思后，再点「显示翻译」或「朗读」来核对——**是否听、何时看完全由你决定**。
4. 点「下一词」继续，直到全部完成。
