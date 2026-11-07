# AI 对话小工具（OpenAI / Kimi）

三个与 LLM 对话的小脚本，逻辑保持原版不变，仅做跨平台与健壮性整理。

| 文件 | 形态 | 后端 | 说明 |
|------|------|------|------|
| `agent_v1.py` | 命令行 | OpenAI | 终端里多轮对话，可按 y 保存会话到 txt |
| `agent_v2.py` | 图形界面 | OpenAI | tkinter 聊天窗口，回车发送、线程调用防卡顿 |
| `kimi_agent_v1.py` | 图形界面 | Kimi / Moonshot | 同上，接 Moonshot 兼容接口 |

## 运行

```bash
pip install openai

# 命令行版（OpenAI）
export OPENAI_API_KEY="你的key"     # Windows: set OPENAI_API_KEY=...
python agent_v1.py

# 图形界面版（OpenAI）
python agent_v2.py

# 图形界面版（Kimi / Moonshot）
export MOONSHOT_API_KEY="你的key"
python kimi_agent_v1.py
```

## 本轮整理做了什么

- 源码由 GBK 转为 UTF-8（原文件在 GitHub 上中文会乱码）。
- **修复致命 bug**：`agent_v2.py` 与 `kimi_agent_v1.py` 在 `__init__` 里引用了尚未创建的全局 `mac`（`mac.after(...)`），一启动即 `NameError` 崩溃；已改为 `self.root` 并移除。
- API Key 改为**优先读取环境变量**（`OPENAI_API_KEY` / `MOONSHOT_API_KEY`），不再把占位 key 写死在代码。
- 去掉强制窗口置顶（`-topmost`），聊天记录区底色由深蓝改为白底，文字清晰可读。
- 会话仍会自动保存到 `conversation_<时间戳>_log.txt`。
