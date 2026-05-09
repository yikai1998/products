# encoding = 'utf-8'
from nunu import *

BASE_URL = "https://www.kanunu8.com"  # 努努书坊
AUTHOR_URL = "https://www.kanunu8.com/zj/10867.html"  # 古龙系列


def main():
    print("正在获取作者作品页...")

    html = get_html(url=AUTHOR_URL)
    books = parse_books(html, url=BASE_URL)

    if not books:
        print("没有解析到作品列表")
        return

    selected_books = choose_books(books)

    if not selected_books:
        print("没有选择任何书")
        return

    print("\n你选择了：")
    for book in selected_books:
        print("-", book["title"])

    confirm = input("\n确认下载？输入 y 开始：").strip().lower()

    if confirm != "y":
        print("已取消")
        return

    for book in selected_books:
        download_book(book)

    print("\n全部完成")


if __name__ == "__main__":
    main()