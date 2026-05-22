import pandas as pd
import numpy as np
from pathlib import Path

base = "/Users/ben.chen/PycharmProjects/ben_awx_project/space/我的/理财/"
BOND  = {10309, 163806, 3157, 6760}
EQUITY = {8929, 12414, 8189, 9860}

dfs = []
for path in Path(base).rglob("历史净值.csv"):
    try:
        df = pd.read_csv(path, sep="\t", encoding="utf-8")
        df["净值日期"] = pd.to_datetime(df["净值日期"])
        df = df.sort_values("净值日期").reset_index(drop=True)
        nav = df["累计净值"].values
        for n in [10, 20, 60]:
            fwd = np.full(len(nav), np.nan)
            for i in range(len(nav) - n):
                if nav[i] > 0 and not np.isnan(nav[i]):
                    fwd[i] = (nav[i + n] - nav[i]) / nav[i]
            df[f"fwd_{n}d"] = fwd
        df = df[df["信号"] != "数据不足"].copy()
        code = int(df["基金代码"].iloc[0])
        df["类型"] = "债基" if code in BOND else ("股基" if code in EQUITY else "其他")
        dfs.append(df)
    except Exception as e:
        print(f"失败: {e}")

all_df = pd.concat(dfs, ignore_index=True)

def analyze(sub, sig, thresholds):
    rows_all = sub[sub["信号"] == sig]
    if len(rows_all) == 0:
        return
    results = {}
    for t in thresholds:
        if t == 0:
            r = rows_all
        else:
            r = rows_all[rows_all["信号连续天数"] == t]
        if len(r) < 5:
            results[t] = None
            continue
        v60 = r["fwd_60d"].dropna()
        v20 = r["fwd_20d"].dropna()
        v10 = r["fwd_10d"].dropna()
        results[t] = {
            "n": len(r),
            "20d_med": v20.median()*100 if len(v20) else np.nan,
            "20d_win": (v20>0).mean()*100 if len(v20) else np.nan,
            "60d_med": v60.median()*100 if len(v60) else np.nan,
            "60d_win": (v60>0).mean()*100 if len(v60) else np.nan,
        }
    return results

ALL_SIGS = [
    "极端大跌 且 低估",
    "极端大跌（未低估）",
    "动力不强, 但低估",
    "短期调整，长期低估",
    "连跌加速",
    "良性上涨",
    "合理区间波动",
    "短期调整，估值中性",
    "高估",
    "动力不强, 但仍高估",
    "上涨尾声",
    "极端大涨 且 高估",
    "极端大涨（未高估）",
]

for ftype in ["债基", "股基"]:
    sub = all_df[all_df["类型"] == ftype]
    print(f"\n{'='*70}")
    print(f"【{ftype}】  +20d / +60d   中位收益% | 盈利率%")
    print(f"  {'信号':<22}  {'天数':>4}  {'n':>4}  {'20d中位':>7}  {'20d盈%':>6}  {'60d中位':>7}  {'60d盈%':>6}")
    print(f"  {'─'*22}  {'─'*4}  {'─'*4}  {'─'*7}  {'─'*6}  {'─'*7}  {'─'*6}")

    for sig in ALL_SIGS:
        rows_all = sub[sub["信号"] == sig]
        if len(rows_all) == 0:
            continue
        # overall
        v20 = rows_all["fwd_20d"].dropna(); v60 = rows_all["fwd_60d"].dropna()
        print(f"  {sig:<22}  {'全部':>4}  {len(rows_all):>4}  {v20.median()*100:>+7.2f}  {(v20>0).mean()*100:>6.0f}  {v60.median()*100:>+7.2f}  {(v60>0).mean()*100:>6.0f}")
        # by threshold
        for t in [1, 3, 5, 10, 15]:
            r = rows_all[rows_all["信号连续天数"] == t]
            if len(r) < 5: continue
            v20t = r["fwd_20d"].dropna(); v60t = r["fwd_60d"].dropna()
            print(f"  {'':22}  {f'第{t}天':>4}  {len(r):>4}  {v20t.median()*100:>+7.2f}  {(v20t>0).mean()*100:>6.0f}  {v60t.median()*100:>+7.2f}  {(v60t>0).mean()*100:>6.0f}")
