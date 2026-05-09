# coding=gbk

from PIL import Image
from pillow_heif import register_heif_opener
import os
import shutil
from tqdm import tqdm
import re

register_heif_opener()

# 设置文件夹
input_folder = r"F:\我的信息"  # 输入文件夹
output_folder = r"F:\我的信息"  # 输出文件夹

# 确保输出文件夹存在
os.makedirs(output_folder, exist_ok=True)


def clean_filename(filename):
    """
    清理文件名：
    - 空格 -> 下划线
    - 连续横杠 -> 单个下划线
    - 特殊字符 -> 下划线
    - 多个下划线 -> 单个下划线
    - 去除首尾下划线
    """
    # 分离文件名和扩展名
    name, ext = os.path.splitext(filename)

    # 替换规则
    name = name.replace(" ", "_")  # 空格 -> 下划线
    name = re.sub(r"-+", "_", name)  # 连续横杠 -> 单个下划线
    name = re.sub(r"[^\w\u4e00-\u9fa5]", "_", name)  # 特殊字符（保留中文、字母、数字、下划线）
    name = re.sub(r"_+", "_", name)  # 多个下划线 -> 单个
    name = name.strip("_")  # 去除首尾下划线

    # 防止清理后为空
    if not name:
        name = "unnamed"

    return name


# 获取所有 HEIC/HEIF 文件
image_files = [f for f in os.listdir(input_folder)
               if f.lower().endswith((".heic", ".heif"))]

converted_count = 0
skipped_count = 0

# 批量转换（带进度条）
for filename in tqdm(image_files, desc="转换进度"):
    input_path = os.path.join(input_folder, filename)

    # 清理文件名（不含扩展名）
    clean_name = clean_filename(os.path.splitext(filename)[0])

    # 生成输出文件名
    output_filename = clean_name + ".jpg"
    output_path = os.path.join(output_folder, output_filename)

    # 防覆盖处理：如果文件已存在，添加序号
    # counter = 1
    # original_clean_name = clean_name
    # while os.path.exists(output_path):
    #     output_filename = f"{original_clean_name}_{counter}.jpg"
    #     output_path = os.path.join(output_folder, output_filename)
    #     counter += 1

    try:
        # 打开、转换、保存
        img = Image.open(input_path)
        rename_info = ""
        if os.path.exists(output_path):
            rename_info = f" (覆盖重名文件)"
        img.convert("RGB").save(output_path, "JPEG", quality=95)

        # 保留原始文件的修改时间
        shutil.copystat(input_path, output_path)

        # 显示结果
        tqdm.write(f"完成: {filename} -> {output_filename}{rename_info}")
        converted_count += 1

    except Exception as e:
        tqdm.write(f"失败: {filename} - {e}")
        skipped_count += 1

print(f"\n{'=' * 40}")
print(f"转换完成: {converted_count} 个")
print(f"跳过的  : {skipped_count} 个")