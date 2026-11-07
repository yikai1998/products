# 文件格式转换（图片批量转格式）

把图片批量转成指定格式，并自动规整文件名。默认面向 HEIC / HEIF 照片，但可在界面里自选常用转换类型。

## 功能

- **转换类型可选**（图形界面下拉 / 命令行 `--type`，常用预设）：
  - `HEIC/HEIF → JPG`
  - `PNG → JPG`、`WEBP → JPG`
  - `全部图片 → JPG / PNG / WEBP`（输入涵盖 heic/heif/png/jpg/jpeg/webp/bmp/tif/tiff/gif）
  - 同格式文件自动跳过（例如「全部图片 → PNG」时原本就是 .png 的不再处理）
- 文件名规整：空格 / 连字符 / 特殊字符 → 下划线，合并连续下划线，去首尾下划线
- **输入 / 输出目录可配置**（命令行参数 或 图形界面选择），不再硬编码
- **同名文件安全处理**：默认自动加 `_1` / `_2` 后缀，避免悄悄覆盖（可勾选强制覆盖）

## 运行

方式一：图形界面（默认，顶部先选「转换类型」）

```bash
python main.py
```

方式二：命令行（无界面，便于脚本调用）

```bash
python main.py -i "输入文件夹" -o "输出文件夹" -t heic_jpg [--overwrite]
```

`--type` 可选值：`heic_jpg` / `png_jpg` / `webp_jpg` / `all_jpg` / `all_png` / `all_webp`（默认 `heic_jpg`）。

## 依赖

```bash
pip install Pillow pillow-heif
```

`tqdm`（进度条）与 `tkinter`（界面）均为可选；tkinter 随 Python 自带，Linux 需 `sudo apt install python3-tk`。

## 说明

- 若原目录与目标目录相同，转换后的文件与原文件并存，不会删除原始文件（删除请自行确认）。
- 转换会保留原文件的时间戳（`copystat`）。
