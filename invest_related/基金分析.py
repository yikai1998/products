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


"""
策略随想 2025-09-20
"极端暴涨, 别上头买"	未持有：别买。已持有：一出现，之后回撤的第1天就卖。（此决策可以被后续其他信号覆盖）
"极端暴跌, 准备关注"	未持有：出现的当天大概率是暴跌的，等后续的当天只要不是暴跌就买进。已持有：别卖，赌未来，原则上见好就收。
"高估, 不宜加仓"		未持有：别买。已持有：在3天内出现至少2次后, 则之后涨的那天就卖。
"动力不强, 但低估, 可考虑分批"	未持有：连续出现至少4天, 再等待出现至少连续2天的"合理区间波动", 则在之后跌的那天就买。已持有：反正别卖，赌未来，原则上见好就收。
"良性上涨, 可适量增持"	未持有：在3天内出现至少2次后, 则之后跌的那天就买。（可自身迭代, 看最后的连续信号）已持有：反正别买，赌未来。
"上涨尾声, 分批落袋"	已持有：只要一出现，再等待第1次回撤, 再等待第1次涨的那天就卖。已持有：反正别买，赌未来。

"连跌加速, 可关注/耐心等待"
"低估, 可买"
"极端暴跌, 刚开始"
"动力不强, 但仍高估, 观望/减仓"
"""


def get_fund_code(path: str = "基金代码名单_持仓.txt"):
    """
    功能: 获取准备好的基金名单, 每行一个
    参数: path 文本 文件路径
    返回: list
    """
    with open(file=path, mode='r', encoding='utf-8') as f:
        fund_code_list = [line.strip() for line in f if line.strip()]
    if len(fund_code_list) == 0:
        print("基金代码名单为空")
        sys.exit(1)
    return fund_code_list


def basic_profile(fund_code: str):
    """
    功能: 获取基金的基本信息（如基金名称、类别、成立时间、运作状态、基金经理等），并以友好格式整理为多行字符串，便于展示概览/打印输出。
    参数: fund_code 文本 基金代码，如 000001、161725 等，可带或不带后缀
    返回: str
    """
    print(f"正在拉取基金 {fund_code} 的简介 ……")
    basic = ak.fund_individual_basic_info_xq(symbol=fund_code)  # 返回 DataFrame
    intro = ""
    for item in basic.values:
        item = [str(x) if pd.notna(x) else "" for x in item]
        intro += ("\t".join(item))
        intro += "\n"
    p = f"基金代码{fund_code}_简介_{datetime.datetime.now().strftime('%y%m%d')}.txt"
    with open(file=p, mode="w", encoding="utf-8") as f:
        f.write(intro)

    return intro


def hold_base(symbol: str):
    """
    功能: 获取基金最近两个年度（含今年和去年）已披露的最新季度的股票重仓持仓数据。会自动兼容 AkShare 官方接口失效时抓取东方财富原始页面，支持通用公募基金。
    参数: fund_code 文本 基金代码，如 000001、161725 等，可带或不带后缀
    返回: DataFrame
    """
    print(f"正在拉取基金 {fund_code} 近两年度持仓 ……")
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
    big = big[big["std_q"] == latest_q].drop(columns=["std_q"])
    big.sort_values(by="占净值比例", inplace=True, ascending=False)
    big.reset_index(drop=True, inplace=True)
    p = f"基金代码{fund_code}_最新持仓_{datetime.datetime.now().strftime('%y%m%d')}.csv"
    big.to_csv(path_or_buf=p, encoding="utf-8", sep="\t", index=False)

    return big


def manual_parse(symbol: str, year: str):
    """
    功能: 用于从东方财富F10（原网页）直接解析某基金某年度的全部历史持仓信息。这个函数一般作为hold_base的辅助后备方案，用于当 AkShare接口出错或字段结构不兼容时的爬虫。
    参数: symbol 文本 基金代码，如 000001、161725 等，可带或不带后缀。year 文本 年份字符串，如 2023
    返回: DataFrame
    """
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


def fetch_all_nav(fund_code: str):
    """
    功能: 根据基金代码拉取全部历史净值
    参数: fund_code 文本 基金代码，如 000001、161725 等，可带或不带后缀
    返回: dataframe
    介绍:
        1. 数据获取
            利用 AkShare 接口，获取指定基金的历史日净值数据，包含净值日期、单位净值、日增长率等基础字段。
        2. 人工预测数据补充（可选）
            拉取历史数据后，支持手工输入“今日预测日增长率”。系统会自动根据上一日单位净值和输入的增长率推算出今日单位净值，补全其它缺省字段，
            并将预测行追加到数据表最后，并统一按“净值日期”升序排序。这样可纳入后续指标和信号分析，实现自动加人工混合推算。
        3. 指标构建与动量特征
            - 计算20日均线（MA20）、120日均线（MA120），用于判断中长期趋势。
            - 计算近10日“日增长率滑动均值”，反映短期动能变化。
            - 计算季度（30日/90日）和年度（360日）最大回撤，用于风险评估。
            - 统计近阶段“连续上涨天数”“连续下跌天数”及标签，有助于刻画超买超卖及惯性走势。
            - 探测短期内“连跌恐慌”现象（如5日内多次大跌）。
        4. 历史分位与动态估值
            - 计算“低于历史价值百分比”：反映当前净值在全部历史中的相对估值水平（百分比分位）。
            - 计算“低于过去60日的价值百分比”：近两月的分位，减少历史极端值干扰，突出近期估值。
            - 动态设定高估/低估分位阈值，支持全局及窗口化判断。
    """
    print(f"正在拉取基金 {fund_code} 的全部历史净值 ……")
    try:
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")  # 累计净值走势
    except Exception as e:
        print(f"[错误] 拉取数据失败，原因：{e}")
        sys.exit()

    df["净值日期"] = pd.to_datetime(df["净值日期"])
    # 获取上一日的单位净值
    last_nav = df.sort_values("净值日期")["单位净值"].iloc[-1]
    # 人工添加数据, 视情况
    predict = input("请输入今天的预测日增长率(如-1=跌1%), 回车跳过: ").strip()
    if predict:
        predict = float(predict)
        new_row = {
            "净值日期": pd.to_datetime(datetime.datetime.now().date()),
            "单位净值": round(last_nav*(1+predict/100), 4),
            "日增长率": predict,
        }
        for col in df.columns:
            if col not in new_row:
                new_row[col] = np.nan
        df.loc[len(df)] = new_row
    else:
        print("未输入今日增长率, 未添加今日预测")
    df["基金代码"] = fund_code
    df.sort_values("净值日期", inplace=True)
    df.reset_index(drop=True, inplace=True)
    df["MA20"] = df["单位净值"].rolling(20).mean()
    df["MA120"] = df["单位净值"].rolling(120).mean()
    pct_list_all = [np.nan]
    for i in range(1, len(df)):
        history = df["单位净值"].iloc[:i]
        pct = (history > df["单位净值"].iloc[i]).mean()
        pct_list_all.append(pct)
    df["低于历史价值百分比"] = pct_list_all
    # 动态阈值：随过去 250 天滚动，从低到高排(从高估到低估)，低于历史价值百分比的第2%｜80%分位值
    df["高估边界"] = df["低于历史价值百分比"].rolling(360).quantile(0.02)
    df["低估边界"] = df["低于历史价值百分比"].rolling(360).quantile(0.8)
    pct_list_60 = [None] * 60
    for i in range(60, len(df)):
        history = df["单位净值"].iloc[(i - 60):i]
        pct = (history > df["单位净值"].iloc[i]).mean()
        pct_list_60.append(pct)
    df["低于过去60日的价值百分比"] = pct_list_60
    df["日增长率"] = round(df["日增长率"] / 100, 4)
    df["日增长率滑动均值"] = df["日增长率"].rolling(10).mean()
    df["日增长率滑动均值"] = df["日增长率滑动均值"]
    df["季度最大回撤"] = (df["单位净值"] - df["单位净值"].rolling(30).max()) / df["单位净值"].rolling(90).max()
    df["年最大回撤"] = (df["单位净值"] - df["单位净值"].rolling(360).max()) / df["单位净值"].rolling(360).max()
    df["连跌恐慌"] = (df["日增长率"] < -0.01).rolling(5).sum() >= 3
    up_days = []  # 连续上涨天数
    cnt = 0
    for rate in df["日增长率"]:
        if rate >= 0:
            cnt += 1
        else:
            cnt = 0
        up_days.append(cnt)
    df["连续上涨天数"] = up_days
    down_days = []  # 连续下跌天数
    cnt = 0
    for rate in df["日增长率"]:
        if rate < 0:
            cnt += 1
        else:
            cnt = 0
        down_days.append(cnt)
    df["连续下跌天数"] = down_days
    df["连涨连跌标签"] = df.apply(
        lambda row: f"连续上涨{row["连续上涨天数"]}天" if row["连续上涨天数"] > 0 else f"连续下跌{row["连续下跌天数"]}天",
        axis=1
    )

    return df


def nav_signal_analysis(df):
    """
    1. 多元量化投资信号输出
    - 信号判据融合了价格与均线关系、分位估值、短期/长期动量、回撤风险、连涨连跌状态等多维因子。
    - 逐日自动打标以下场景（结合信号周期与累计涨跌）：
        - 良性上涨、适量增持
        - 高估，不宜加仓（含连续上涨过多天时的追高风险）
        - 动力不强, 但仍高估，观望/减仓
        - 上涨尾声，分批落袋（动能减弱且已有回撤，顶部信号）
        - 动力不强，但低估，可考虑分批布局
        - 低估，可买（跌深+低估分位+近期连续下跌，左侧信号）
        - 连跌加速，可关注/耐心等待（超卖期间的反弹潜力观测）
        - 合理区间波动（无明显偏强/偏弱状态）
    - “连续上涨/下跌天数”与信号配合，可以辅助规避追涨杀跌情绪、改进定投策略。
    2. 其它
        - 支持信号分段、阶段天数等统计，利于后续分析各信号状态持续时间及周期节奏。
        - 最终输出含历史全部关键指标与信号的DataFrame，为量化择时、估值分析以及定投、左侧配置等实战场景提供参考依据。
        - 保存CSV或HTML
    """
    df = df.copy()
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
        p_under_360d_high, p_under_360d_low = df.loc[i, "高估边界"], df.loc[i, "低估边界"]
        panic = df.loc[i, "连跌恐慌"]
        up_days = df.loc[i, "连续上涨天数"]
        down_days = df.loc[i, "连续下跌天数"]

        if (price > ma20) and (ma20 > ma120) and (mean_growth_10d > 0.001) and (qdraw >= -0.05) and (
                p_under_total > p_under_360d_high):
            tag.append("良性上涨, 可适量增持")
        elif (price > ma20) and (price > ma120) and (p_under_total <= p_under_360d_high) and (up_days >= 5):
            tag.append("高估, 不宜加仓")
        elif (price < ma20) and (price < ma120) and (p_under_total <= p_under_360d_high):
            tag.append("动力不强, 但仍高估, 观望/减仓")
        elif (price > ma20) and (price > ma120) and (ma20 > ma120) and (mean_growth_10d < 0.001) and (
                qdraw < -0.05) and (up_days >= 3):
            tag.append("上涨尾声, 分批落袋")
        elif (price < ma20) and (price < ma120) and (p_under_total >= p_under_360d_low):
            tag.append("动力不强, 但低估, 可考虑分批")
        elif (price > ma120 or p_under_total >= p_under_360d_low) and (hydraw < -0.2) and (p_under_60d >= 0.85) and (
                down_days >= 3):
            tag.append("低估, 可买")
        elif panic and (p_under_total >= p_under_360d_low):
            tag.append("连跌加速, 可关注/耐心等待")

        else:
            tag.append("合理区间波动")

    df["信号"] = tag
    df["低于过去60日的价值百分比"] = df["低于过去60日的价值百分比"].map(lambda x: "%.5f" % x)
    df["日增长率滑动均值"] = df["日增长率滑动均值"].map(lambda x: "%.5f" % x)
    df["信号标记"] = (df["信号"] != df["信号"].shift()).cumsum()  # 列整体向下移动一行, 判断变化, 标记同一信号连续出现的段落
    df["信号连续天数"] = df.groupby("信号标记").cumcount() + 1  # 统计同一段的第几天
    df = df.drop(columns=["信号标记"])
    df.sort_values("净值日期", inplace=True)
    df.reset_index(drop=True, inplace=True)
    p1 = f"基金代码{fund_code}_历史净值_{datetime.datetime.now().strftime('%y%m%d')}.csv"
    df.to_csv(path_or_buf=p1, encoding="utf-8", sep="\t", index=False)
    p2 = f"基金代码{fund_code}_历史净值_{datetime.datetime.now().strftime('%y%m%d')}.html"
    table_html = df.to_html(index=False)
    full_html = f"""<!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>基金净值</title>
    </head>
    <body>
    {table_html}
    </body>
    </html>"""
    with open(p2, encoding="utf-8", mode="w") as f:
        f.write(full_html)

    return df


if __name__ == "__main__":
    pd.set_option("display.max_columns", None)
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 1000)

    code_list = get_fund_code(path="基金代码名单_持仓.txt")
    for fund_code in code_list:

        basic_intro = basic_profile(fund_code)
        print(basic_intro)

        holding = hold_base(fund_code)
        print(holding[:10][["季度", "股票代码", "股票名称", "占净值比例"]])

        nav_df = fetch_all_nav(fund_code)
        nav_df_ana = nav_signal_analysis(df=nav_df)
        print(nav_df_ana[["基金代码", "净值日期", "单位净值", "日增长率", "低于历史价值百分比", "信号", "信号连续天数", "连涨连跌标签"]].sort_values(ascending=False, by="净值日期").head(n=21).reset_index(drop=True))

        time.sleep(2)
