# Products — 个人 Python 工具集

涵盖 AI 对话、办公自动化、语言学习、理财分析、小说下载等日常场景。每个子文件夹都是独立的小工具，逻辑保持原样，本轮统一做了**跨平台（Windows / macOS / Linux）整理**：GBK 源码转 UTF-8、UI 字体自动适配、依赖与路径可配置、GUI 友好化、README 补全。

---

## 目录结构

```
python/
├── AI相关/          与 LLM 对话（OpenAI / Kimi），含 CLI 与 GUI 版
├── 办公摸鱼/        企业微信「保活」自动输入（后台自动化，非 GUI）
├── 外语学习/        外语单词听读 + 翻译（跨平台语音 + GUI/CLI）
├── 小说下载/        古龙武侠小说批量下载（GUI 启动器 + CLI）
├── 文件格式转换/    HEIC/HEIF 批量转 JPEG（GUI + 可配置路径）
├── 理财/            基金分析与买卖信号（GUI + 可交互走势图）
├── 账单计算/        多人 AA 分账计算器（GUI，成员可增删）
└── 加密文件夹/      Windows 文件夹伪装隐藏（保持原逻辑，未做 UI）
```

---

## 各模块说明

### AI相关

| 文件 | 形态 | 后端 |
|------|------|------|
| `agent_v1.py` | 命令行 | OpenAI |
| `agent_v2.py` | 图形界面 | OpenAI |
| `kimi_agent_v1.py` | 图形界面 | Kimi / Moonshot |

- API Key 优先读环境变量：`OPENAI_API_KEY` / `MOONSHOT_API_KEY`。
- 会话自动保存到 `conversation_<时间戳>_log.txt`。
- 本轮修复了 GUI 版一启动就崩溃的 bug（`__init__` 中误用了尚未创建的 `mac` 变量），并去掉强制置顶、聊天区改为白底。

**依赖：** `openai`、`tkinter`（Python 自带）

---

### 办公摸鱼

`wecom_v1.py` — 每 3 分钟向「当前焦点窗口」（请先切到企业微信输入框）输入并删除 `Hi Team,`，持续约 5 小时，防止被判定离开。

- 这是**后台自动化脚本**，刻意不做 GUI（做界面会和打字抢焦点）。
- 紧急停止：把鼠标甩到屏幕任意角落触发 `pyautogui` FAILSAFE。
- **依赖：** `pyautogui`

---

### 外语学习

`main.py` — 随机抽取单词卡，朗读 + 翻译。支持英语 / 日语；外网用 GoogleTranslator，内网用 Bing。

- **跨平台语音**：自动在系统已装嗓音里按语言匹配，不再写死 Mac 嗓音。
- 图形界面（默认）或 `--cli` 命令行；可设数量、是否朗读、逐词显示翻译。
- 单词本：`wording_en.txt` / `wording_jp.txt`（每行一词）。

**依赖：** `pyttsx3`、`deep_translator`、`translators`

---

### 小说下载

`main.py` — 古龙武侠小说批量抓取并合并为 txt（抓取/解析逻辑在 `nunu.py` / `gulongbbs.py`，未改动）。

- `nunu` 书坊（适合外网）、`gulongbbs` 武侠网（适合非外网）。
- GUI（默认）：选来源、勾书目 / 填代码、实时进度日志；或 `--cli` 沿用原交互。

**依赖：** `requests`、`beautifulsoup4`

---

### 文件格式转换

`main.py` — 批量将 iPhone 的 HEIC/HEIF 转 JPEG，文件名自动规整，保留时间戳。

- 输入/输出目录可配置（GUI 选文件夹 或 `-i/-o` 参数）。
- 同名文件默认自动加 `_1/_2` 后缀，避免悄悄覆盖。

**依赖：** `Pillow`、`pillow-heif`（`tqdm`、`tkinter` 可选）

---

### 理财

基金量化分析工具：抓净值/持仓/基本信息，算均线、估值分位、回撤等因子，给出**统一 7 档估值结论**（严重高估→严重低估），指数/ETF 额外叠加**跟踪指数 PE 历史分位**维度。

- 图形界面 `gui.py`：自选基金增删、分类标签**可改名 / 跨标签转移**、单只设今日预测、批量分析、可交互走势图（ECharts，日期滑块联动 + 均线/高低估线开关）。
- 个人数据与缓存已用 `.gitignore` 忽略，不入库。

**依赖：** `akshare`、`pandas`、`numpy`、`matplotlib`、`requests`、`demjson3`、`beautifulsoup4`

---

### 账单计算

`main.py` — Tkinter AA 分账计算器。

- **参与人名单可自由增删**（不再是写死的 4 个英文名）。
- 计算结果直接显示在界面（不再只打到控制台），并给出**最简转账建议**。
- 跨平台字体自动适配，去除强制置顶。

**依赖：** `pandas`、`numpy`

---

### 加密文件夹

`locker.py` — 把文件夹伪装成 Windows「控制面板」系统文件夹并隐藏（CLSID + `attrib +h +s`）。

- 按需求**未做图形界面、未改逻辑**。
- **仅 Windows 有效**，属「隐藏」而非真加密，密码写在源码里，重要资料请用 BitLocker / VeraCrypt。

---

## 快速开始

```bash
# 各模块按需安装依赖，例如：
pip install openai pyautogui pyttsx3 deep_translator translators \
            requests beautifulsoup4 Pillow pillow-heif \
            akshare pandas numpy matplotlib demjson3

# 运行示例
python 理财/gui.py
python 账单计算/main.py
python 外语学习/main.py          # 图形界面；加 --cli 走命令行
python 小说下载/main.py
python 文件格式转换/main.py
python AI相关/agent_v2.py
```

> 说明：tkinter 随 Python 官方安装包自带（Linux 需 `sudo apt install python3-tk`）。
