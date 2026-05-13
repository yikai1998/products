# encoding = 'utf-8'
import re
import nunu
import gulongbbs


def choose_source():
    print("\n请选择下载源：")
    print("-" * 60)
    print("1. nunu       努努书坊，适合外网")
    print("2. gulongbbs  古龙武侠网，适合非外网")
    print("-" * 60)

    while True:
        choice = input("请输入 1 或 2：").strip().lower()

        if choice in ["1", "nunu"]:
            return "nunu"

        if choice in ["2", "gulongbbs", "gulong"]:
            return "gulongbbs"

        print("输入无效，请重新输入。")


# 先获取古龙作品列表，然后让用户选择编号
def run_nunu():
    base_url = "https://www.kanunu8.com"  # 努努书坊
    author_url = "https://www.kanunu8.com/zj/10867.html"  # 古龙系列
    print("\n当前使用：努努书坊 nunu")
    print("正在获取作者作品页...")
    html = nunu.get_html(url=author_url)
    books = nunu.parse_books(html, url=base_url)

    if not books:
        print("没有解析到作品列表")
        return 0

    selected_books = nunu.choose_books(books)

    if not selected_books:
        print("没有选择任何书")
        return 0

    print("\n你选择了：")
    for book in selected_books:
        print("-", book["title"])

    confirm = input("\n确认下载？输入 y 开始：").strip().lower()

    if confirm != "y":
        print("已取消")
        return 0

    for book in selected_books:
        nunu.download_book(book)

    print("\n全部完成")
    return 1


# 让用户直接输入 book code
def run_gulongbbs():
    print("\n当前使用：古龙武侠网 gulongbbs")
    print("-" * 60)
    print("请输入要下载的书籍代码，例如：")
    print("  ssydj")
    print("也可以输入多个：")
    print("  ssydj,dqjk,tddh")
    print("-" * 60)
    text = input("请输入书籍代码：").strip()

    if not text:
        return 0

    books = re.split(r"[,，\s]+", text)
    selected_books = [book.strip() for book in books if book.strip()]

    if not selected_books:
        print("没有选择任何书")
        return 0

    print("\n你选择了：")
    for book in selected_books:
        print("-", book)

    confirm = input("\n确认下载？输入 y 开始：").strip().lower()

    if confirm != "y":
        print("已取消")
        return 0

    for book in selected_books:
        gulongbbs.download_book(book)

    print("\n全部完成")
    return 1


def main():
    source = choose_source()

    if source == "nunu":
        run_nunu()
    elif source == "gulongbbs":
        run_gulongbbs()
    else:
        print("未知下载源")


if __name__ == "__main__":
    main()
