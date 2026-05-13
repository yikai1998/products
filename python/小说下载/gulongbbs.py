# coding=utf-8
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import requests
import time
import os
import re


headers = {
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36"
    ),
    "referer": "https://www.gulongbbs.com/",
}

session = requests.Session()
session.headers.update(headers)

# 请求网页并返回 HTML 文本
def get_html(url):
    r = session.get(url, timeout=15)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text

def safe_filename(name):
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = name.strip()
    return name or "未命名"

# 从目录页解析中文书名
def parse_book_title(html, fallback="未知书名"):
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.select_one("h4.blue strong")
    if tag:
        title = tag.get_text(strip=True)
        title = title.replace("古龙《", "").replace("》", "")
        return title.strip() or fallback

    if soup.title:
        title = soup.title.get_text(strip=True)
        # 古龙《多情剑客无情剑》 - 古龙武侠小说全集 - 古龙武侠网
        title = title.split(" - ")[0]
        title = title.replace("古龙《", "").replace("》", "")
        return title.strip() or fallback

    return fallback

# 从 #pages 中寻找“下一页”，目录页和章节页都能用
def get_next_page(html, current_url):
    soup = BeautifulSoup(html, "html.parser")
    pages = soup.select_one("#pages")

    if not pages:
        return None

    for a in pages.select("a"):
        text = a.get_text(strip=True)
        if text == "下一页":
            href = a.get("href")
            if href:
                return urljoin(current_url, href)

    return None

# 从一个目录页中提取章节：标题、链接
def parse_chapters_from_index(html, current_url):
    soup = BeautifulSoup(html, "html.parser")
    chapters = []

    for li in soup.select(".col-left ul.list li"):
        a = li.select_one("a")
        if not a:
            continue

        title = a.get_text(strip=True)
        href = a.get("href")

        if not title or not href:
            continue

        full_url = urljoin(current_url, href)

        chapters.append({
            "title": title,
            "url": full_url
        })

    return chapters

# 抓一本书的所有目录分页，返回全部章节
def crawl_book_index(start_url):
    url = start_url
    visited = set()
    all_chapters = []

    while url and url not in visited:
        visited.add(url)
        print("正在抓目录页:", url)
        html = get_html(url)
        chapters = parse_chapters_from_index(html, url)
        all_chapters.extend(chapters)
        next_url = get_next_page(html, url)

        if not next_url:
            print("没有下一页目录了")
            break

        url = next_url
        time.sleep(0.5)

    # 按 URL 去重，防止分页或排行榜误入时重复
    seen = set()
    unique_chapters = []

    for ch in all_chapters:
        if ch["url"] in seen:
            continue
        seen.add(ch["url"])
        unique_chapters.append(ch)

    return unique_chapters

# 解析章节正文
def parse_chapter_content(html, url=""):
    soup = BeautifulSoup(html, "html.parser")
    article = soup.find("div", id="Article")

    if not article:
        raise ValueError(f"未找到 div#Article: {url}")

    content_div = article.find("div", class_="content")
    if not content_div:
        raise ValueError(f"未找到正文 div.content: {url}")

    # 删除脚本和样式
    for tag in content_div(["script", "style"]):
        tag.decompose()

    text = content_div.get_text().strip()

    return text

# 抓一个章节的全部正文。如果章节有分页，会自动继续抓“下一页”。
def crawl_chapter(start_url):
    url = start_url
    visited = set()
    all_text = []

    while url and url not in visited:
        visited.add(url)
        print("    正在抓章节页:", url)
        html = get_html(url)
        text = parse_chapter_content(html, url=url)

        if text:
            all_text.append(text)

        next_url = get_next_page(html, url)

        if not next_url:
            break

        url = next_url
        time.sleep(0.8)

    return "\n\n".join(all_text)


def download_book(book):
    """
    下载一本书。
    book 示例：
        ssydj
        dqjk
        tddh
    """
    book_url = f"https://www.gulongbbs.com/book/{book}/"
    print("\n" + "=" * 80)
    print(f"开始处理：{book}")
    print(f"目录地址：{book_url}")

    # 先抓一次目录首页，用来解析中文书名
    index_html = get_html(book_url)
    book_title = parse_book_title(index_html, fallback=book)
    print(f"书名：{book_title}")

    chapters = crawl_book_index(book_url)

    if not chapters:
        print(f"没有解析到章节：{book_title}")
        return 0

    print(f"章节数量：{len(chapters)}")

    os.makedirs("Downloads2", exist_ok=True)

    filename = safe_filename(book_title) + ".txt"
    save_path = os.path.join("Downloads2", filename)

    with open(save_path, "w", encoding="utf-8") as f:
        f.write(book_title)
        f.write("\n")
        f.write("=" * 60)
        f.write("\n\n")

        for idx, chapter in enumerate(chapters, start=1):
            chapter_title = chapter["title"]
            chapter_url = chapter["url"]

            print(f"[{idx}/{len(chapters)}] 下载：{chapter_title}")
            print(f"    地址：{chapter_url}")

            try:
                body = crawl_chapter(start_url=chapter_url)

                f.write(chapter_title)
                f.write("\n")
                f.write("-" * 60)
                f.write("\n\n")
                f.write(body)
                f.write("\n\n\n")

                time.sleep(0.8)

            except Exception as e:
                print(f"下载失败：{chapter_title} {chapter_url}")
                print("原因：", e)

                f.write(chapter_title)
                f.write("\n")
                f.write("-" * 60)
                f.write("\n\n")
                f.write(f"本章下载失败：{chapter_url}\n")
                f.write(f"原因：{e}\n\n\n")

    print(f"\n保存完成：{save_path}")
    return 1


if __name__ == "__main__":
    download_book("ssydj")
    # download_book("dqjk")
    # download_book("tddh")
