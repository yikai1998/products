# 外语单词背诵（朗读 + 翻译）

随机抽取单词卡，自动朗读并翻译，用于背单词 / 练听力。

## 功能

- 从 `wording_en.txt`（英语）或 `wording_jp.txt`（日语）随机抽取若干词
- 联网翻译：外网用 GoogleTranslator，内网用 translators 的 Bing
- **跨平台朗读**：自动在系统已安装嗓音中按语言匹配（Win/Mac/Linux 均可），不再写死 Mac 嗓音
- **图形界面 + 命令行**两用

## 运行

```bash
python main.py            # 默认启动图形界面
python main.py --cli      # 命令行交互模式
python main.py --cli --lang ja --n 20 --net 2   # 日语、抽20个、外网
```

参数：`--lang en|ja`、`--n 数量`、`--net 1|2`（1 内网 / 2 外网）、`--no-audio`（不朗读）。

## 依赖

```bash
pip install pyttsx3 deep_translator translators
```

- `pyttsx3` 在 Windows 用系统语音、Mac 用 `say`、Linux 需 `sudo apt install espeak` 或 `festival`。
- `wording_en.txt` / `wording_jp.txt` 每行一个单词，已随仓库提供示例。

## 图形界面用法

选择语言 / 网络 / 数量，勾选「朗读」→「开始」→ 逐词点「朗读 / 显示翻译 / 下一词」。
