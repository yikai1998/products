# encoding = 'utf-8'
import re
import time
import os
from bs4 import BeautifulSoup
import requests

# 请求网页并处理编码
def get_html(url):
    headers = {
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        "referer": "https://www.kanunu8.com/",
    }

    # requests.Session() 的优势: 更适合连续请求多个网页, 自动复用 headers, 自动管理 cookie, 连接复用，效率更高
    session = requests.Session()
    session.headers.update(headers)
    r = session.get(url, timeout=15)
    r.raise_for_status()
    html = r.content.decode("gb18030", errors="ignore")  # gb18030 兼容 gbk / gb2312，适合这种老中文网站

    return html

# 处理文件名中的非法字符
def safe_filename(name):
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = name.strip()

    return name

# 清洗正文
def clean_text(text):
    lines = []

    for line in text.splitlines():
        line = line.replace("\xa0", "")
        line = line.replace("\u3000", "")
        line = line.strip()
        if line:
            lines.append(line)

    return "\n".join(lines)

# 解析作品列表
def parse_books(html, url):
    soup = BeautifulSoup(html, "html.parser")
    links = soup.select(".mulu-list ul li a")
    books = []

    for a in links:
        title = a.get_text(strip=True).strip("《》")
        href = a.get("href", "").strip()
        if not title or not href:
            continue
        book_url = f"{url}{href}"
        match = re.search(r"/book/(\d+)/", href)
        book_id = match.group(1) if match else ""
        books.append({
            "title": title,
            "id": book_id,
            "href": href,
            "url": book_url,
        })

    return books

# 解析某本书的章节目录
def parse_chapters(html, book_url):
    soup = BeautifulSoup(html, "html.parser")
    chapters = []

    # 新版页面
    links = soup.select(".mulu-list ul li a")
    # 旧版页面
    if not links:
        links = soup.find_all("a", href=re.compile(r"^\d+\.html$"))

    for a in links:
        title = a.get_text(strip=True)
        href = a.get("href", "").strip()
        if not title or not href:
            continue
        chapter_url = f"{book_url}{href}"
        chapters.append({
            "title": title,
            "href": href,
            "url": chapter_url,
        })

    return chapters

# 解析章节标题和正文
def parse_chapter(html):
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.select_one("div.content.book-content h1") or soup.select_one("h1")
    title = title_tag.get_text(strip=True) if title_tag else "未知标题"
    content_tag = soup.select_one("#neirong") or soup.select_one(".neirong")
    if content_tag is None:
        candidates = soup.find_all("td")
        if candidates:
            content_tag = max(candidates, key=lambda t: len(t.get_text(strip=True)))
    if content_tag is None:
        return title, ""

    for tag in content_tag.select("script, style"):
        tag.decompose()
    text = content_tag.get_text()
    body = clean_text(text)

    return title, body

# 选择要下载的书
def choose_books(books):
    print("\n作品列表：")
    print("-" * 60)

    for idx, book in enumerate(books, start=1):
        print(f"{idx:02d}. {book['title']}    {book['url']}")

    print("-" * 60)
    print("输入编号下载单本，例如：1")
    print("输入多个编号下载多本，例如：1,3,5")
    print("输入 all 下载全部")
    choice = input("\n请选择要下载的书：").strip()

    if choice.lower() == "all":
        return books

    selected = []
    parts = re.split(r"[,，\s]+", choice)
    if all(part.isdigit() for part in parts if part):
        for part in parts:
            if not part:
                continue
            index = int(part)
            if 1 <= index <= len(books):
                selected.append(books[index - 1])
            else:
                print(f"编号超出范围：{index}")
        return selected

    for book in books:
        if choice in book["title"]:
            selected.append(book)

    return selected

# 下载并保存为 txt
def download_book(book):
    book_title = book["title"]
    book_url = book["url"]
    print(f"\n开始处理：{book_title}")
    print(f"目录地址：{book_url}")

    html = get_html(book_url)
    chapters = parse_chapters(html, book_url)
    if not chapters:
        print(f"没有解析到章节：{book_title}")
        return 0
    print(f"章节数量：{len(chapters)}")

    filename = safe_filename(book_title) + ".txt"
    os.makedirs("Downloads", exist_ok=True)
    save_path = os.path.join("Downloads", filename)
    with open(save_path, "w", encoding="utf-8") as f:
        f.write(book_title)
        f.write("\n")
        f.write("=" * 60)
        f.write("\n\n")

        for idx, chapter in enumerate(chapters, start=1):
            chapter_title = chapter["title"]
            chapter_url = chapter["url"]
            print(f"[{idx}/{len(chapters)}] 下载：{chapter_title}")

            try:
                chapter_html = get_html(chapter_url)
                real_title, body = parse_chapter(chapter_html)

                # 如果章节标题解析不到，就用目录里的标题
                if real_title == "未知标题":
                    real_title = chapter_title

                f.write(real_title)
                f.write("\n")
                f.write("-" * 60)
                f.write("\n\n")
                f.write(body)
                f.write("\n\n\n")

                time.sleep(0.5)

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
