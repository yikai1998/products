# 文件格式转换（HEIC / HEIF → JPEG）

把 iPhone 等生成的 HEIC / HEIF 照片批量转成通用 JPEG，并自动规整文件名。

## 功能

- 批量将 `.heic` / `.heif` 转为 `.jpg`（质量 95）
- 文件名规整：空格 / 连字符 / 特殊字符 → 下划线，合并连续下划线，去首尾下划线
- **输入 / 输出目录可配置**（命令行参数 或 图形界面选择），不再硬编码
- **同名文件安全处理**：默认自动加 `_1` / `_2` 后缀，避免悄悄覆盖（可勾选强制覆盖）

## 运行

方式一：图形界面（默认）

```bash
python main.py
```

方式二：命令行（无界面，便于脚本调用）

```bash
python main.py -i "输入文件夹" -o "输出文件夹" [--overwrite]
```

## 依赖

```bash
pip install Pillow pillow-heif
```

`tqdm`（进度条）与 `tkinter`（界面）均为可选；tkinter 随 Python 自带，Linux 需 `sudo apt install python3-tk`。

## 说明

- 若原目录与目标目录相同，转换后的 `.jpg` 与原 `.heic` 并存，不会删除原始文件（删除请自行确认）。
- 转换会保留原文件的时间戳（`copystat`）。
