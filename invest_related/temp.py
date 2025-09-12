# coding=gbk
import re
import pandas as pd
import akshare as ak
import requests
import demjson3 as dj
import bs4
import io
import sys
import numpy as np
import datetime

pd.set_option("display.max_columns", None)
pd.set_option("display.max_rows", None)
pd.set_option("display.width", 1000)


def fetch_all_nav(fund_code: str):
    """
    功能: 根据基金代码拉取全部历史净值
    参数: fund_code 文本 基金代码，如 000001、161725 等，可带或不带后缀
    返回: dataframe 净值日期, 单位净值, 日增长率
    介绍:
        1. 数据获取
        调用 AkShare 接口，抓取基金的历年日净值数据。
        主要字段有：净值日期、单位净值、日增长率。
        2. 常用技术指标计算
        计算20日均线（MA20）、120日均线（MA120）。
        计算最近10日“日增长率滑动均值”，反映短期动能状况。
        计算近15日最高点（近15日高点）与当前净值的回撤比例（距离高点回撤比），识别阶段顶部或回撤风险。
        3. 历史分位（低估/高估判断）
        计算“低于历史价值百分比”：当前净值在基金历史中的分位（前i天有多少比例净值高于现值，位置越高越低估）。
        计算“低于过去60日的价值百分比”：近期分位，减少历史极端值干扰，增强参考性。
        4. 量化信号给出
        根据均线排列、分位数、日增长率及回撤等多元条件，逐日生成投资信号，包括：
        上涨势头可能要结束了：处于多头趋势，但短期涨幅趋缓且近20日出现不小幅度回撤，属于顶部预警信号，应谨慎操作。
        低估, 可买：多头排列、估值明显低于历史和近60天，双重低估可积极布局。
        关注, 可能还能跌：大趋势尚可但可能仍在下跌，适合谨慎关注。
        高估, 别持有：多头转弱且高估，建议回避。
        合理区间波动：其它无明显信号状态。
    """
    try:
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")  # 累计净值走势
    except Exception as e:
        print(f"[错误] 拉取数据失败，原因：{e}")
        sys.exit()

    """如果你希望「单位净值 + 累计净值」在同一张表，需要自己把两次返回的 DataFrame 按日期 merge
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
    )"""
    df["基金代码"] = fund_code
    df["净值日期"] = pd.to_datetime(df["净值日期"])
    df["MA20"] = df["单位净值"].rolling(20).mean()
    df["MA120"] = df["单位净值"].rolling(120).mean()
    pct_list_all = [np.nan]
    for i in range(1, len(df)):
        history = df["单位净值"].iloc[:i]
        pct = (history > df["单位净值"].iloc[i]).mean()
        pct_list_all.append(pct)
    df["低于历史价值百分比"] = pct_list_all
    # 动态阈值：随过去 250 天滚动，从低到高排(从高估到低估)，低于历史价值百分比的第35%｜70%分位值
    df["高估边界"] = df["低于历史价值百分比"].rolling(360).quantile(0.02)
    df["低估边界"] = df["低于历史价值百分比"].rolling(360).quantile(0.8)
    pct_list_60 = [None] * 60
    for i in range(60, len(df)):
        history = df["单位净值"].iloc[(i-60):i]
        pct = (history > df["单位净值"].iloc[i]).mean()
        pct_list_60.append(pct)
    df["低于过去60日的价值百分比"] = pct_list_60
    df["低于过去60日的价值百分比"] = df["低于过去60日的价值百分比"]
    df["日增长率"] = round(df["日增长率"] / 100, 4)
    df["日增长率滑动均值"] = df["日增长率"].rolling(10).mean()
    df["日增长率滑动均值"] = df["日增长率滑动均值"]
    df["季度最大回撤"] = (df["单位净值"] - df["单位净值"].rolling(30).max()) / df["单位净值"].rolling(90).max()
    df["年最大回撤"] = (df["单位净值"] - df["单位净值"].rolling(360).max()) / df["单位净值"].rolling(360).max()
    df["连跌恐慌"] = (df["日增长率"] < -0.01).rolling(5).sum() >= 3
    tag = []

    for i in range(len(df)):
        price = df.loc[i, "单位净值"]
        ma20 = df.loc[i, "MA20"]
        ma120 = df.loc[i, "MA120"]
        p_under_total = df.loc[i, "低于历史价值百分比"]
        p_under_60d = df.loc[i, "低于过去60日的价值百分比"]
        mean_growth_10d = df.loc[i, "日增长率滑动均值"]
        qdraw = df.loc[i, "季度最大回撤"]
        hydraw = df.loc[i, "年最大回撤"]
        p_under_360d_high, p_under_360d_low = df.loc[i, "高估边界"],  df.loc[i, "低估边界"]
        panic = df.loc[i, "连跌恐慌"]

        if (price > ma20) and (ma20 > ma120) and (mean_growth_10d > 0.001) and (qdraw >= -0.05) and (p_under_total > p_under_360d_high):
            tag.append("良性上涨, 可适量增持")
        elif (price > ma20) and (price > ma120) and (p_under_total <= p_under_360d_high):
            tag.append("高估, 不宜加仓")
        elif (price < ma20) and (price < ma120) and (p_under_total <= p_under_360d_high):
            tag.append("动力不强, 但仍高估, 观望/减仓")
        elif (price > ma20) and (price > ma120) and (ma20 > ma120) and (mean_growth_10d < 0.001) and (qdraw < -0.05):
            tag.append("上涨尾声, 分批落袋")
        elif (price < ma20) and (price < ma120) and (p_under_total >= p_under_360d_low):
            tag.append("动力不强, 但低估, 可考虑分批")
        elif (price > ma120 or p_under_total >= p_under_360d_low) and (hydraw < -0.2) and (p_under_60d >= 0.85):
            tag.append("低估, 可买")
        elif panic and (p_under_total >= p_under_360d_low):
            tag.append("连跌加速, 可关注/耐心等待")

        else:
            tag.append("合理区间波动")

    df["信号"] = tag
    df["低于过去60日的价值百分比"] = df["低于过去60日的价值百分比"].map(lambda x: '%.5f' % x)
    df["日增长率滑动均值"] = df["日增长率滑动均值"].map(lambda x: '%.5f' % x)

    df['信号标记'] = (df['信号'] != df['信号'].shift()).cumsum()  # 列整体向下移动一行, 判断变化, 标记同一信号连续出现的段落
    df['信号连续天数'] = df.groupby('信号标记').cumcount() + 1  # 统计同一段的第几天

    df.sort_values("净值日期", inplace=True)
    df.reset_index(drop=True, inplace=True)

    return df


def basic_profile(fund_code: str):
    basic = ak.fund_individual_basic_info_xq(symbol=fund_code)  # 返回 DataFrame
    intro = ""
    for item in basic.values:
        item = [str(x) if pd.notna(x) else "" for x in item]
        intro += ("\t".join(item))
        intro += "\n"
    return intro


def hold_base(symbol: str):
    now = datetime.datetime.now()
    years = [str(now.year - 1), str(now.year)]
    big = pd.DataFrame()
    for y in years:
        try:
            r = ak.fund_portfolio_hold_em(symbol, y)  # akshare 官方实现
        except Exception as e:
            print(f"【akshare 接口失败】{e}，尝试自解析……")
            # 列名对不上 -> 自己手搓解析
            r = manual_parse(symbol, y)
        if r.empty:
            print(f"代码{symbol} 在 {y} 年暂未披露持仓")
            continue
        big = pd.concat([big, r], ignore_index=True)
    if big.empty:
        return pd.DataFrame(columns=["股票代码", "股票名称", "占净值比例", "持股数", "持仓市值", "季度"])
    # 生成可排序的“标准季度”列
    big["std_q"] = (big["季度"].str.extract(r"(\d{4})[年Qq]([1234])")[0] + "Q" + big["季度"].str.extract(r"(\d{4})[年Qq]([1234])")[1]).apply(lambda x: pd.Period(x, freq="Q"))
    # 取最新季度
    latest_q = big["std_q"].max()
    # 一次性捞出所有属于最新季度的行
    big = big[big["std_q"] == latest_q].drop(columns="std_q")
    return big


def manual_parse(symbol: str, year: str):
    url = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
    params = {"type": "jjcc", "code": symbol, "topline": 10000, "year": year, "month": "", "rt": "0.913877030254846"}
    txt = requests.get(url, params=params, timeout=10).text  # 防止脚本卡死
    data = dj.decode(txt[txt.find("{"): -1])
    # 没有表格直接返回空表
    if not data.get("content", "").strip():
        return pd.DataFrame()
    soup = bs4.BeautifulSoup(data["content"], "lxml")
    heads = [h4.text.split("\xa0\xa0")[1] for h4 in
             soup.find_all("h4", class_="t")]  # <h4 class="t">2024Q1</h4>“分隔符”, \xa0\xa0“不间断空格”

    big = pd.DataFrame()
    for q, html_table in enumerate(pd.read_html(io.StringIO(data["content"]), converters={"股票代码": str})):
        # 把字符串“伪装”成类文件对象，让 pandas 走“内存文本”分支，一次性读表。强制将股票代码当作str看待
        # 把所有列名里的空格、%、全角括号全干掉，方便后面模糊匹配
        html_table.columns = [re.sub(r"[ %　\(\)（）]", "", c.strip()) for c in html_table.columns]
        ratio_col = next((c for c in html_table.columns if "占净值" in c), None)  # “找第一个满足条件的元素”的惯用写法，找不到就 None
        if ratio_col is None:
            html_table["占净值比例"] = pd.NA
        else:
            html_table["占净值比例"] = html_table[ratio_col].astype(str).str.replace("%", "", regex=False)

        # A new DataFrame with the new columns in addition to all the existing columns.
        sub = (
            html_table.assign(季度=heads[q]))
        big = pd.concat([big, sub], ignore_index=True)

    return big


def main():
    fund_code = input(">> 输入基金代码: ")

    print(f"正在拉取基金 {fund_code} 的简介 ……")
    basic_intro = basic_profile(fund_code)
    print(basic_intro)

    print(f"正在拉取基金 {fund_code} 近两年度持仓 ……")
    holding = hold_base(fund_code)
    print(holding)

    print(f"正在拉取基金 {fund_code} 的全部历史净值 ……")
    nav_df = fetch_all_nav(fund_code)

    print(f"完成！共 {len(nav_df)} 条记录")
    nav_df.to_csv(f"{fund_code}_nav_{datetime.datetime.now().strftime('%y%m%d')}", encoding='utf-8')
    print(nav_df)


if __name__ == "__main__":
    main()
