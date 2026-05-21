# Products

个人 Python 工具集，涵盖 AI 对话、办公自动化、语言学习、理财分析等日常场景。

---

## 目录结构

```
python/
├── AI相关/          AI 聊天客户端（OpenAI / Kimi）
├── 办公摸鱼/        自动保持在线状态
├── 外语学习/        外语单词听读练习
├── 小说下载/        古龙武侠小说批量下载
├── 文件格式转换/    HEIC 图片批量转 JPEG
├── 理财/            基金分析与买卖信号
└── 账单计算/        多人 AA 分账计算器
```

---

## 各模块说明

### AI相关

| 文件 | 说明 |
|------|------|
| `agent_v1.py` | 命令行聊天客户端，使用 OpenAI GPT-4 Turbo，支持对话历史保存 |
| `agent_v2.py` | Tkinter GUI 聊天客户端，支持多行输入、自动日志记录 |
| `kimi_agent_v1.py` | 基于 Moonshot AI（Kimi）的 GUI 客户端，接口与 agent_v2 一致 |

**依赖：** `openai` `kimi`

---

### 办公摸鱼

`wecom_v1.py` — 每 3 分钟自动向企业微信发送一条消息，持续 5 小时，用于保持在线状态。

**依赖：** `pyautogui`  
**停止方式：** 将鼠标移到屏幕角落触发 failsafe

---

### 外语学习

`main.py` — 随机播放单词并朗读发音，自动翻译成中文。支持日语和英语，自动检测网络环境（国内/国际）选择翻译后端。

**依赖：** `pyttsx3`、`googletrans` 或 `translate`

---

### 小说下载

`main.py` — 古龙武侠小说批量下载工具，支持两个来源：
- **努努书坊**（国际网络）
- **古龙武侠网**（国内网络）

列出书目后可多选下载，自动保存为 TXT 文件。

---

### 文件格式转换

`main.py` — 批量将 iPhone 拍摄的 HEIC/HEIF 图片转换为 JPEG，自动清理文件名（去除空格、特殊字符），保留原始时间戳，支持重复文件处理。

**依赖：** `pillow-heif`、`Pillow`

---

### 理财

基金量化分析工具，输入基金代码后自动生成分析报告。

**功能：**
- 基金基本信息与持仓分析
- 历史净值与技术指标（20日/120日均线、百分位估值、最大回撤）
- 多因子买卖信号（暴涨过热、暴跌低估、良性上涨、恐慌抛售等 14 种）
- 4 面板可视化图表

详细信号含义及操作建议见 `使用.txt`。

**依赖：** `akshare`、`matplotlib`、`pandas`

---

### 账单计算

`main.py` — Tkinter GUI 分账计算器，支持多人 AA，自动计算每人应付/应收金额，可动态增删条目。

**内置成员：** Bella、Cynthia、Emma、Simon

---

## 快速开始

```bash
# 安装依赖（按需安装对应模块的依赖）
pip install openai pyautogui akshare matplotlib pandas pillow pillow-heif

# 运行示例
python python/理财/main.py
python python/账单计算/main.py
```
