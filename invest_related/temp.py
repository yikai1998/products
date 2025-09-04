# coding=gbk
import sys
import akshare as ak
import pandas as pd

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
    basic = ak.fund_individual_basic_info_xq(symbol="163806")  # 返回 DataFrame
    intro = ''
    for item in basic.values:
        item = [str(x) if pd.notna(x) else '' for x in item]
        intro += ('\t'.join(item))
        intro += '\n'
    return intro


def main():
    fund_code = input(">> 输入基金代码: ")

    print(f"正在拉取基金 {fund_code} 的简介 ……")
    basic_intro = basic_profile(fund_code)
    print(basic_intro)

    print(f"正在拉取基金 {fund_code} 的全部历史净值 ……")
    nav_df = fetch_all_nav(fund_code)

    print(f"完成！共 {len(nav_df)} 条记录")
    print(nav_df)


if __name__ == "__main__":
    main()

