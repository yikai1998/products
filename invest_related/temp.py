# coding=gbk
import re
import pandas as pd
import akshare as ak
import requests
import demjson3 as dj
import bs4
import io

pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', None)
pd.set_option('display.width', 1000)


def fetch_all_nav(fund_code: str):
    """
    功能: 根据基金代码拉取全部历史净值
    参数: fund_code 文本 基金代码，如 000001、161725 等，可带或不带后缀
    返回: dataframe 净值日期, 单位净值, 日增长率
    """
    try:
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")  # 累计净值走势
    except Exception as e:
        print(f"[错误] 拉取数据失败，原因：{e}")
        sys.exit()

    df.rename(
        columns={
            "净值日期": "date",
            "单位净值": "unit_nav",  # 反映当天每份基金值多少钱，是买卖成交用的“单价”
            # "累计净值": "acc_nav",  # 在单位净值基础上，把历史上所有分红再投资回去，反映基金从成立到现在的总回报，只是复盘业绩的尺子
            "日增长率": "daily_return_pct",
        },
        inplace=True,
    )
    '''如果你希望「单位净值 + 累计净值」在同一张表，需要自己把两次返回的 DataFrame 按日期 merge
    df = (
    unit.rename(columns={"单位净值": "unit_nav", "日增长率": "daily_pct"})
        .merge(
            acc.rename(columns={"累计净值": "acc_nav"}),
            on="净值日期",
            how="inner"
        )
        .rename(columns={"净值日期": "date"})
        .sort_values("date")
        .reset_index(drop=True)
    )'''
    df["date"] = pd.to_datetime(df["date"])
    df["code"] = fund_code
    df.sort_values("date", inplace=True)
    df.reset_index(drop=True, inplace=True)

    return df


def basic_profile(fund_code: str):
    basic = ak.fund_individual_basic_info_xq(symbol=fund_code)  # 返回 DataFrame
    intro = ''
    for item in basic.values:
        item = [str(x) if pd.notna(x) else '' for x in item]
        intro += ('\t'.join(item))
        intro += '\n'
    return intro


def hold_base(symbol: str, date: str):
    try:
        r = ak.fund_portfolio_hold_em(symbol, date)  # akshare 官方实现
    except Exception as e:
        print(f"【akshare 接口失败】{e}，尝试自解析……")
        # 列名对不上 -> 自己手搓解析
        r = manual_parse(symbol, date)
    if r.empty:
        print(f"代码{symbol} 在 {date} 年暂未披露持仓")
        return pd.DataFrame(columns=["股票代码", "股票名称", "占净值比例", "持股数", "持仓市值", "季度"])
    return r


def manual_parse(symbol: str, date: str):
    url = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
    params = {"type": "jjcc", "code": symbol, "topline": 10000, "year": date, "month": "", "rt": "0.913877030254846"}
    txt = requests.get(url, params=params, timeout=10).text  # 防止脚本卡死
    data = dj.decode(txt[txt.find("{"): -1])
    # 没有表格直接返回空表
    if not data.get("content", "").strip():
        return pd.DataFrame()
    soup = bs4.BeautifulSoup(data["content"], "lxml")
    heads = [h4.text.split("\xa0\xa0")[1] for h4 in
             soup.find_all("h4", class_="t")]  # <h4 class="t">2024Q1</h4>“分隔符”, \xa0\xa0“不间断空格”

    big = pd.DataFrame()
    for q, html_table in enumerate(pd.read_html(io.StringIO(data["content"]), converters={
        "股票代码": str})):  # 把字符串“伪装”成类文件对象，让 pandas 走“内存文本”分支，一次性读表。强制将股票代码当作str看待
        # 把所有列名里的空格、%、全角括号全干掉，方便后面模糊匹配
        html_table.columns = [re.sub(r"[ %　\(\)（）]", "", c.strip()) for c in html_table.columns]
        ratio_col = next((c for c in html_table.columns if "占净值" in c), None)  # “找第一个满足条件的元素”的惯用写法，找不到就 None
        if ratio_col is None:
            html_table["占净值比例"] = pd.NA
        else:
            html_table["占净值比例"] = html_table[ratio_col].astype(str).str.replace("%", "", regex=False)

        # 统一输出列
        keep = {
            "股票代码": "code",
            "股票名称": "name",
            "占净值比例": "ratio",
            "持股数": "shares",
            "持仓市值": "mkt_val",
        }
        # A new DataFrame with the new columns in addition to all the existing columns.
        sub = (
            html_table.rename(columns={k: v for k, v in keep.items() if k in html_table.columns}).assign(季度=heads[q]))
        big = pd.concat([big, sub], ignore_index=True)

    # 类型转换 errors="coerce"把解析失败的变成 NaN，后续画柱状图、算均值都不会炸
    big["ratio"] = pd.to_numeric(big["ratio"], errors="coerce")
    big["shares"] = pd.to_numeric(big["shares"], errors="coerce")
    big["mkt_val"] = pd.to_numeric(big["mkt_val"], errors="coerce")
    return big


def main():
    fund_code = input(">> 输入基金代码: ")

    print(f"正在拉取基金 {fund_code} 的简介 ……")
    basic_intro = basic_profile(fund_code)
    print(basic_intro)

    print(f"正在拉取基金 {fund_code} 的2024年度持仓 ……")
    holding = hold_base(fund_code, "2024")
    print(holding)

    print(f"正在拉取基金 {fund_code} 的全部历史净值 ……")
    nav_df = fetch_all_nav(fund_code)

    print(f"完成！共 {len(nav_df)} 条记录")
    print(nav_df)


if __name__ == "__main__":
    main()

