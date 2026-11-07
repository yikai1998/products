# -*- coding: utf-8 -*-
"""
基金走势分析引擎
================
抓取基金基本信息 / 持仓 / 历史净值，计算技术指标与多因子信号，落盘。

相比旧版 main.py 的改进：
1. 统一 UTF-8；用“基金代码”做稳定文件夹主键（兼容旧「名称_基金代码xxx」目录）。
2. 净值增量缓存：本地 4 天内数据直接复用，不重复全网抓取。
3. CSV 改为标准逗号分隔 + utf-8-sig（中文 Excel 直接不乱码）。
4. 去掉所有 input() 阻塞；今日预测涨幅改为“单只基金、临时叠加”，不写进历史数据。
5. matplotlib 使用 Agg 后端，不弹窗、不阻塞、可无头运行。
6. “低于历史价值百分比”重命名为语义清晰的“估值分位”并加注释。
7. 统一“估值结论”适用于【所有】基金类型，可直接横比；并进一步细分为 7 档
   （严重高估 / 高估 / 估值偏高 / 合理 / 估值偏低 / 低估 / 严重低估），比单纯“高估/低估/合理”更细。
   债券/货币等低波动基金细节仅补“回撤关注”。
8. 指数基金额外抓取“跟踪指数”的市盈率(TTM)历史分位作为基本面估值维度（与净值历史分位互为印证）；
   主动股票/混合基金没有统一市盈率，仍用净值历史分位作为代理（已在报告里注明）。
9. 走势图改为可交互 HTML（ECharts）：上图=净值相关、下图=估值分位，两图日期滑块联动同步；
   顶部新增 From/To 日期筛选框，默认展示全部历史；支持均线/高低估线开关。保留静态 PNG 作为离线兜底。
10. 默认每次分析都联网抓“最新”净值；仅在断网时用“离线模式”读缓存。

对外主要接口：
    run_fund(code, name=None, force=False, predict_today=None, with_holdings=True)
    返回每只基金的分析摘要 dict，GUI / 命令行均可调用。
"""

from __future__ import annotations

import os
import re
import io
import time
import json
import datetime
from typing import Optional

import numpy as np
import pandas as pd
import requests
import demjson3 as dj
from bs4 import BeautifulSoup

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import akshare as ak

# ----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HOLD_COLUMNS = ["序号", "股票代码", "股票名称", "占净值比例", "持股数", "持仓市值", "季度"]

# 低波动基金类型：均线/估值分位信号意义不大，改用轻量信号
LOW_VOL_TYPES = {"债券型", "货币型", "理财型", "保本型", "短期理财", "货币"}

# 中文字体：给出跨平台候选列表（Mac=PingFang/Heiti，Win=雅黑/SimHei，Linux=文泉驿），
# matplotlib 会依次尝试，保证 Mac 与 Windows 上中文都能正常显示。
plt.rcParams["font.sans-serif"] = [
    "PingFang SC", "Heiti SC", "Microsoft YaHei", "SimHei",
    "Arial Unicode MS", "WenQuanYi Micro Hei", "sans-serif",
]
plt.rcParams["axes.unicode_minus"] = False


# ----------------------------------------------------------------------------
def resolve_fund_dir(fund_code: str, name: Optional[str] = None) -> str:
    """定位（或创建）基金专属目录。优先复用已存在的「*基金代码code」目录，避免更名产生孤儿文件夹。"""
    code = str(fund_code).zfill(6)
    if os.path.isdir(BASE_DIR):
        for entry in os.listdir(BASE_DIR):
            full = os.path.join(BASE_DIR, entry)
            if os.path.isdir(full) and entry.endswith(f"基金代码{code}"):
                return full
    folder_name = f"{name}_基金代码{code}" if name else code
    return os.path.join(BASE_DIR, folder_name)


# ----------------------------------------------------------------------------
# 1) 基本信息（含基金类型识别）
# ----------------------------------------------------------------------------
def _detect_type(intro: dict, name: str) -> str:
    t = intro.get("基金类型") or intro.get("类型") or ""
    if not t:
        nm = name or ""
        if "货币" in nm or "现金" in nm:
            t = "货币型"
        elif "债" in nm:
            t = "债券型"
        elif "指数" in nm or "ETF" in nm.upper():
            t = "指数型"
        elif "混合" in nm:
            t = "混合型"
        elif "股票" in nm:
            t = "股票型"
        else:
            t = "其它"
    return t


def get_fund_basic(fund_code: str) -> dict:
    """抓取基金基本信息，落盘 简介.txt 与 meta.json，返回信息 dict（含基金类型）。"""
    code = str(fund_code).zfill(6)
    basic = ak.fund_individual_basic_info_xq(symbol=code)
    intro = {str(k): (str(v) if pd.notna(v) else "") for k, v in basic.values}

    name = (
        intro.get("基金名称")
        or intro.get("基金简称")
        or intro.get("名称")
        or intro.get("基金全称")
        or code
    )
    intro["基金名称"] = name
    fund_type = _detect_type(intro, name)
    intro["基金类型"] = fund_type

    d = resolve_fund_dir(code, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "简介.txt"), "w", encoding="utf-8") as f:
        for k, v in intro.items():
            f.write(f"{k}\t{v}\n")
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"code": code, "name": name, "type": fund_type}, f, ensure_ascii=False, indent=2)
    return intro


def fetch_index_valuation(fund_type: str, basic: dict) -> Optional[dict]:
    """
    仅对【指数 / ETF 类】基金：抓取跟踪指数的市盈率(TTM)历史，算“指数PE分位”。
    返回 {index, pe, pe_pct} 或 None（非指数基金 / 抓不到 / 字段缺失时）。

    说明：
      - 主动股票/混合基金没有统一市盈率（持仓季度披露、不透明），本函数直接返回 None，
        这类基金仍用“净值历史分位”作为估值代理。
      - pe_pct = 历史上有多少比例交易日 PE 比现在低 → 越大越便宜（与净值估值分位同口径）。
    """
    ft = str(fund_type or "")
    if "指数" not in ft and "ETF" not in ft.upper():
        return None
    idx_name = (basic.get("跟踪标的") or basic.get("跟踪指数") or "").strip()
    if not idx_name:
        return None
    try:
        df = ak.stock_index_valuation(symbol=idx_name)
    except Exception as e:  # noqa
        print(f"[指数估值] 抓取失败（{idx_name}）：{e}")
        return None
    if df is None or df.empty:
        return None
    df = df.copy()
    pe = None
    for col in ("滚动市盈率", "静态市盈率", "市盈率"):
        if col in df.columns:
            s = pd.to_numeric(df[col], errors="coerce").dropna()
            if not s.empty:
                pe = s
                break
    if pe is None or pe.empty:
        return None
    latest_pe = float(pe.iloc[-1])
    pe_pct = float((pe < latest_pe).mean())
    return {"index": idx_name, "pe": round(latest_pe, 2), "pe_pct": round(pe_pct, 4)}


# ----------------------------------------------------------------------------
# 2) 持仓（东方财富 F10 自解析兜底）
# ----------------------------------------------------------------------------
def extract_js_object(txt: str) -> str:
    if not txt:
        raise ValueError("东方财富返回空内容")
    left, right = txt.find("{"), txt.rfind("}")
    if left == -1 or right == -1 or right <= left:
        preview = txt[:500].replace("\n", "\\n")
        raise ValueError(f"返回内容中找不到有效 JSON/JS 对象，前500字符：{preview}")
    return txt[left : right + 1]


def manual_parse(symbol: str, year: str) -> pd.DataFrame:
    symbol, year = str(symbol).zfill(6), str(year)
    url = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
    params = {"type": "jjcc", "code": symbol, "topline": "10000", "year": year, "month": "", "rt": str(time.time())}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Referer": f"https://fundf10.eastmoney.com/ccmx_{symbol}.html",
        "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    resp = requests.get(url=url, params=params, headers=headers, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP 状态异常：{resp.status_code}，url={resp.url}")

    js_text = extract_js_object(resp.text.strip())
    try:
        data = dj.decode(js_text)
    except Exception as e:  # noqa
        preview = js_text[:500].replace("\n", "\\n")
        raise ValueError(f"demjson3 解析失败；待解析内容前500字符：{preview}") from e

    content = data.get("content", "")
    if not content or not str(content).strip():
        return pd.DataFrame(columns=HOLD_COLUMNS)

    soup = BeautifulSoup(content, "lxml")
    heads = []
    for h4 in soup.find_all("h4", class_="t"):
        text = h4.get_text(strip=True)
        heads.append(text.split("\xa0\xa0")[-1] if "\xa0\xa0" in text else text)

    try:
        tables = pd.read_html(io.StringIO(content), converters={"股票代码": str})
    except ValueError:
        return pd.DataFrame(columns=HOLD_COLUMNS)
    if not tables:
        return pd.DataFrame(columns=HOLD_COLUMNS)

    result_list = []
    for idx, html_table in enumerate(tables):
        html_table = html_table.copy()
        html_table.columns = [re.sub(r"[ %　()（）]", "", str(c).strip()) for c in html_table.columns]
        if "相关资讯" in html_table.columns:
            html_table.drop(columns=["相关资讯"], inplace=True)
        code_col = next((c for c in html_table.columns if "股票代码" in c), None)
        name_col = next((c for c in html_table.columns if "股票名称" in c), None)
        if code_col is None or name_col is None:
            continue
        ratio_col = next((c for c in html_table.columns if "占净值" in c), None)
        shares_col = next((c for c in html_table.columns if "持股数" in c), None)
        value_col = next((c for c in html_table.columns if "持仓市值" in c), None)

        sub = pd.DataFrame()
        sub["股票代码"] = html_table[code_col].astype(str).str.zfill(6)
        sub["股票名称"] = html_table[name_col].astype(str)
        sub["占净值比例"] = (
            html_table[ratio_col].astype(str).str.replace("%", "", regex=False).str.strip()
            if ratio_col is not None else pd.NA
        )
        sub["持股数"] = html_table[shares_col] if shares_col is not None else pd.NA
        sub["持仓市值"] = html_table[value_col] if value_col is not None else pd.NA
        sub["季度"] = heads[idx] if idx < len(heads) else f"{year}年未知季度"
        result_list.append(sub)

    if not result_list:
        return pd.DataFrame(columns=HOLD_COLUMNS)
    big = pd.concat(result_list, ignore_index=True)
    big["占净值比例"] = pd.to_numeric(big["占净值比例"], errors="coerce")
    big["持股数"] = pd.to_numeric(big["持股数"], errors="coerce")
    big["持仓市值"] = pd.to_numeric(big["持仓市值"], errors="coerce")
    big.insert(0, "序号", range(1, len(big) + 1))
    return big[HOLD_COLUMNS]


def get_holdings(fund_code: str, name: str) -> pd.DataFrame:
    """抓取最近两个年度已披露的最新季度持仓，落盘 最新持仓.csv。"""
    code = str(fund_code).zfill(6)
    now = datetime.datetime.now()
    years = [str(now.year - 1), str(now.year)]
    big = pd.DataFrame()
    for y in years:
        try:
            r = ak.fund_portfolio_hold_em(symbol=code, date=y)
        except Exception as e:  # noqa
            print(f"[akshare 接口失败] {code} {y}: {e}，尝试自解析……")
            try:
                r = manual_parse(code, y)
            except Exception as e2:  # noqa
                print(f"[自解析也失败] {code} {y}: {e2}")
                r = pd.DataFrame(columns=HOLD_COLUMNS)
        if r is None or r.empty:
            print(f"代码 {code} 在 {y} 年暂未披露持仓")
            continue
        big = pd.concat([big, r], ignore_index=True)
        time.sleep(0.8)
    if big.empty:
        return pd.DataFrame(columns=HOLD_COLUMNS)

    q_extract = big["季度"].astype(str).str.extract(r"(\d{4})[年Qq]?第?([1234])?[季度]?")
    bad = q_extract[0].isna() | q_extract[1].isna()
    if bad.any():
        q2 = big.loc[bad, "季度"].astype(str).str.extract(r"(\d{4}).*?([1234])")
        q_extract.loc[bad, 0], q_extract.loc[bad, 1] = q2[0], q2[1]
    big["std_q_text"] = q_extract[0] + "Q" + q_extract[1]
    big["std_q"] = big["std_q_text"].apply(
        lambda x: pd.Period(x, freq="Q") if isinstance(x, str) and re.match(r"\d{4}Q[1-4]", x) else pd.NaT
    )
    big = big.dropna(subset=["std_q"])
    if big.empty:
        return pd.DataFrame(columns=HOLD_COLUMNS)
    latest_q = big["std_q"].max()
    big = big[big["std_q"] == latest_q].drop(columns=["std_q", "std_q_text"])
    big["占净值比例"] = pd.to_numeric(big["占净值比例"], errors="coerce")
    big.sort_values(by="占净值比例", ascending=False, inplace=True)
    big.reset_index(drop=True, inplace=True)
    d = resolve_fund_dir(code, name)
    os.makedirs(d, exist_ok=True)
    big.to_csv(os.path.join(d, "最新持仓.csv"), encoding="utf-8-sig", index=False)
    return big


# ----------------------------------------------------------------------------
# 3) 历史净值 + 指标
# ----------------------------------------------------------------------------
def _download_nav(fund_code: str) -> pd.DataFrame:
    code = str(fund_code).zfill(6)
    df_unit = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
    df_cum = ak.fund_open_fund_info_em(symbol=code, indicator="累计净值走势")
    return df_unit.merge(df_cum[["净值日期", "累计净值"]], on="净值日期", how="left")


def _build_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    在原始净值基础上计算技术指标与估值分位。

    估值分位（核心，原“低于历史价值百分比”）：
        估值分位 = 历史上净值「高于」今日的交易日占比。
        - 值越大 → 今日越接近历史低位（越便宜）；
        - 值越小 → 今日越接近历史高位（越贵）。
    由此：高估线 = 估值分位序列的 10% 分位（小值→贵）；低估线 = 90% 分位（大值→便宜）。

    说明：日增长率在此处应为“小数”。百分比→小数的转换仅在下载时做一次，保证幂等、缓存复用不会二次除 100。
    """
    df = df.copy()
    df["净值日期"] = pd.to_datetime(df["净值日期"], errors="coerce")
    df["单位净值"] = pd.to_numeric(df["单位净值"], errors="coerce")
    df["累计净值"] = pd.to_numeric(df["累计净值"], errors="coerce")
    df["日增长率"] = pd.to_numeric(df["日增长率"], errors="coerce")
    df = df.dropna(subset=["净值日期", "单位净值", "累计净值"]).sort_values("净值日期").reset_index(drop=True)

    df["MA20"] = df["累计净值"].rolling(20).mean()
    df["MA120"] = df["累计净值"].rolling(120).mean()

    cum = df["累计净值"].values
    n = len(cum)
    pct_all = np.full(n, np.nan)
    for i in range(1, n):
        pct_all[i] = (cum[:i] > cum[i]).mean()
    df["估值分位"] = pct_all

    win = min(750, n - 2)
    df["高估线"] = df["估值分位"].rolling(win, min_periods=250).quantile(0.1).shift(1)
    df["低估线"] = df["估值分位"].rolling(win, min_periods=250).quantile(0.9).shift(1)

    pct60 = np.full(n, np.nan)
    for i in range(60, n):
        pct60[i] = (cum[i - 60 : i] > cum[i]).mean()
    df["近60日估值分位"] = pct60

    df["日增长率10日均"] = df["日增长率"].rolling(10).mean()
    df["极端涨幅线"] = df["日增长率"].rolling(250).quantile(0.98).shift(1)
    df["极端跌幅线"] = df["日增长率"].rolling(250).quantile(0.01).shift(1)
    df["季度最大回撤"] = (df["累计净值"] - df["累计净值"].rolling(90).max()) / df["累计净值"].rolling(90).max()
    df["年最大回撤"] = (df["累计净值"] - df["累计净值"].rolling(260).max()) / df["累计净值"].rolling(260).max()
    df["连跌恐慌"] = (df["日增长率"] < -0.01).rolling(5).sum() >= 3

    up_days, down_days, cu, cd = [], [], 0, 0
    for rate in df["日增长率"]:
        cu = cu + 1 if rate >= 0 else 0
        cd = cd + 1 if rate < 0 else 0
        up_days.append(cu)
        down_days.append(cd)
    df["连续上涨天数"], df["连续下跌天数"] = up_days, down_days
    df["连涨连跌标签"] = [f"连续上涨{u}天" if u > 0 else f"连续下跌{d}天" for u, d in zip(up_days, down_days)]
    return df


def _predict_row(df: pd.DataFrame, predict_pct: float) -> dict:
    """根据最近一日累计净值与“今日预测涨幅(%)”推算今日预测点（仅用于临时展示，不落盘历史）。"""
    last = df.sort_values("净值日期").iloc[-1]
    nav = round(float(last["累计净值"]) * (1 + predict_pct / 100), 4)
    cum = df["累计净值"].values
    val_pct = float((cum > nav).mean()) if len(cum) else np.nan
    return {"date": pd.Timestamp(datetime.date.today()), "累计净值": nav, "估值分位": val_pct}


def _append_predict(df: pd.DataFrame, predict_pct: float) -> pd.DataFrame:
    df = df.copy()
    last = df.iloc[-1]
    new_row = {
        "净值日期": pd.Timestamp(datetime.date.today()),
        "单位净值": round(float(last["单位净值"]) * (1 + predict_pct / 100), 4),
        "累计净值": round(float(last["累计净值"]) * (1 + predict_pct / 100), 4),
        "日增长率": predict_pct / 100,
    }
    for col in df.columns:
        if col not in new_row:
            new_row[col] = np.nan
    df.loc[len(df)] = new_row
    return _build_indicators(df.sort_values("净值日期").reset_index(drop=True))


def fetch_nav(fund_code: str, offline: bool = False, force: bool = False) -> pd.DataFrame:
    """
    获取历史净值与指标。

      - 默认（offline=False）：每次都联网抓取“最新”历史净值（保证你看到的就是最新），
        并把结果回写本地缓存；若联网失败则自动回退到上次缓存（不会报错中断）。
      - offline=True：不联网，仅用本地「历史净值.csv」缓存（适合断网时查看旧数据）。
      - force=True：忽略缓存直接全量重抓（一般无需，仅在怀疑缓存脏了时用）。

    注意：此处只返回真实历史，预测涨幅不在此处叠加（见 run_fund）。
    """
    code = str(fund_code).zfill(6)
    d = resolve_fund_dir(code)
    os.makedirs(d, exist_ok=True)
    cache_path = os.path.join(d, "历史净值.csv")
    cached = None
    if os.path.exists(cache_path):
        try:
            cached = pd.read_csv(cache_path, encoding="utf-8-sig")
        except Exception:
            cached = None

    # 离线模式：直接用缓存（没有缓存也要兜底抓一次）
    if offline:
        if cached is not None and {"净值日期", "单位净值", "累计净值"}.issubset(cached.columns):
            return _build_indicators(cached)

    # 联网抓取（默认路径；离线但无缓存时也会走到这里）
    try:
        print(f"[{code}] 联网抓取最新历史净值 ……")
        df = _download_nav(code)
        df["日增长率"] = pd.to_numeric(df["日增长率"], errors="coerce") / 100  # 百分比→小数，仅下载时一次
        df.to_csv(cache_path, encoding="utf-8-sig", index=False)
        return _build_indicators(df)
    except Exception as e:  # noqa
        if cached is not None:
            print(f"[{code}] 联网失败，回退本地缓存：{e}")
            return _build_indicators(cached)
        raise


# ----------------------------------------------------------------------------
# 4) 信号打标（按基金类型分支）
# ----------------------------------------------------------------------------
def _valuation_level(val: float, over: float, under: float) -> str:
    """
    把“估值分位”细分为 7 档结论（值越大越便宜）：
        严重高估 → 高估 → 估值偏高 → 合理 → 估值偏低 → 低估 → 严重低估
    其中：
        - val <= 高估线(over, 历史10%分位, 小值=贵)        → 高估区
        - val >= 低估线(under, 历史90%分位, 大值=便宜)      → 低估区
        - 两者之间为“合理”区，按距离中点再细分为 偏高 / 合理 / 偏低
    对【所有】基金类型一致，可直接横比。
    """
    if pd.isna(val) or pd.isna(over) or pd.isna(under):
        return "数据不足"
    if val <= over:
        return "严重高估" if (val <= over * 0.5 or val <= 0.04) else "高估"
    if val >= under:
        gap = 1 - under
        return "严重低估" if val >= under + gap * 0.5 else "低估"
    mid = (over + under) / 2
    half = (under - over) / 2
    if abs(val - mid) <= half * 0.45:
        return "合理"
    return "估值偏高" if val <= mid else "估值偏低"


def _assign_signals(df: pd.DataFrame, fund_type: str = "") -> pd.DataFrame:
    """
    打信号。统一给出“估值结论”（高估 / 低估 / 合理），对【所有】基金类型一致：
        - 估值分位 <= 高估线(历史10%分位，小值=贵) → 高估（当前处历史高位，相对贵）
        - 估值分位 >= 低估线(历史90%分位，大值=便宜) → 低估（当前处历史低位，相对便宜）
        - 否则 → 合理（估值中性）

    补充说明：
        - 股票/混合/指数/QDII 额外给出“信号”细节（动能/回撤/极端涨跌），便于细看；
        - 债券/货币等低波动基金细节只补“回撤关注”（对它们而言均线/估值信号本就微弱）。
    估值结论始终可比、可横比；信号细节仅作参考（详见每只基金的报告）。
    """
    df = df.copy()
    low_vol = fund_type in LOW_VOL_TYPES
    concl, detail = [], []
    for i in range(len(df)):
        row = df.iloc[i]
        val = row["估值分位"]
        over, under = row["高估线"], row["低估线"]
        if pd.isna(val) or pd.isna(over) or pd.isna(under):
            concl.append("数据不足")
            detail.append("数据不足")
            continue

        # —— 统一的估值结论（所有类型一致，细分为 7 档）——
        c = _valuation_level(val, over, under)
        concl.append(c)

        # —— 细节说明 ——
        if low_vol:
            ydraw = row.get("年最大回撤", np.nan)
            note = "回撤关注" if (not pd.isna(ydraw) and ydraw < -0.05) else ""
            detail.append(c if not note else f"{c}·{note}")
            continue

        # 股票 / 混合 / 指数 / QDII 等多因子细节
        need = ["极端涨幅线", "极端跌幅线", "MA20", "MA120", "日增长率", "日增长率10日均",
                "季度最大回撤", "年最大回撤", "连跌恐慌", "连续上涨天数", "连续下跌天数", "近60日估值分位"]
        if row[need].isna().any():
            detail.append(c)
            continue
        rate = row["日增长率"]; up_ext = row["极端涨幅线"]; down_ext = row["极端跌幅线"]
        price = row["累计净值"]; ma20 = row["MA20"]; ma120 = row["MA120"]
        p60 = row["近60日估值分位"]; g10 = row["日增长率10日均"]; qdraw = row["季度最大回撤"]; ydraw = row["年最大回撤"]
        panic = row["连跌恐慌"]; ud = row["连续上涨天数"]; dd = row["连续下跌天数"]

        if (rate >= up_ext) and (val <= over) and (ud >= 2):
            detail.append("极端大涨且高估")
        elif (rate <= down_ext) and (val >= under) and (dd >= 2):
            detail.append("极端大跌且低估")
        elif rate >= up_ext:
            detail.append("极端大涨(未高估)")
        elif rate <= down_ext:
            detail.append("极端大跌(未低估)")
        elif (price > ma20) and (ma20 > ma120) and (g10 > 0.001) and (qdraw >= -0.05) and (val > over):
            detail.append("良性上涨")
        elif (price > ma20) and (price > ma120) and (ma20 > ma120) and (g10 < 0.001) and (qdraw < -0.05):
            detail.append("上涨尾声")
        elif (price > ma20) and (price > ma120) and (val <= over):
            detail.append("高估")
        elif (price < ma20) and (price < ma120) and (val <= over):
            detail.append("动力弱仍高估")
        elif (price < ma20) and (price < ma120) and (val >= under):
            detail.append("动力弱但低估")
        elif (price > ma120) and (price < ma20):
            detail.append("短期调整·长期低估" if val >= under else "短期调整·估值中性")
        elif (val >= under) and (ydraw < -0.2) and (p60 >= 0.85) and (dd >= 3):
            detail.append("低估")
        elif panic and (val >= under):
            detail.append("连跌加速")
        else:
            detail.append("合理区间波动")

    df["估值结论"] = concl
    df["信号"] = detail
    return df


# ----------------------------------------------------------------------------
# 5) 落盘：CSV / HTML / 图
# ----------------------------------------------------------------------------
def _save_html(df: pd.DataFrame, path: str) -> None:
    table_html = df.to_html(index=False, float_format=lambda x: f"{x:.5f}")
    full_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>基金净值与信号</title>
<style>
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: left; white-space: nowrap; }}
th {{ background: #f5f5f5; position: sticky; top: 0; }}
</style></head>
<body>{table_html}</body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(full_html)


def _save_png(df: pd.DataFrame, fund_code: str, name: str, folder: str, predict: Optional[dict] = None) -> None:
    df_plot = df.sort_values("净值日期")
    fig, axes = plt.subplots(nrows=2, ncols=2, figsize=(22, 8), constrained_layout=True)
    ax1, ax2, ax3, ax4 = axes[0, 0], axes[0, 1], axes[1, 0], axes[1, 1]

    ax1.plot(df_plot["净值日期"], df_plot["累计净值"], color="blue", linewidth=2)
    ax1.set_xlabel("日期"); ax1.set_ylabel("累计净值"); ax1.set_title("全历史累计净值走势")
    ax1.tick_params(axis="x", rotation=40); ax1.margins(y=0.1)
    if predict:
        ax1.scatter([predict["date"]], [predict["累计净值"]], color="red", zorder=5, s=40, label="今日预测")
        ax1.legend(loc="upper left")

    ax2.plot(df_plot["净值日期"], df_plot["估值分位"], color="blue", linewidth=2)
    ax2.plot(df_plot["净值日期"], df_plot["高估线"], color="red", linestyle="--", linewidth=1.8, label="高估线")
    ax2.plot(df_plot["净值日期"], df_plot["低估线"], color="green", linestyle="--", linewidth=1.8, label="低估线")
    ax2.set_xlabel("日期"); ax2.set_ylabel("估值分位"); ax2.set_title("全历史估值分位 + 高/低估线")
    ax2.tick_params(axis="x", rotation=40); ax2.margins(y=0.1); ax2.invert_yaxis()
    ax2.legend(loc="lower right", fontsize=8, framealpha=0.8)
    if predict and not pd.isna(predict["估值分位"]):
        ax2.scatter([predict["date"]], [predict["估值分位"]], color="red", zorder=5, s=40)

    tail = df_plot.tail(250)
    ax3.plot(tail["净值日期"], tail["累计净值"], color="blue", linewidth=2)
    ax3.set_xlabel("日期"); ax3.set_ylabel("累计净值"); ax3.set_title("近250日累计净值走势")
    ax3.tick_params(axis="x", rotation=40); ax3.margins(y=0.1)
    if predict:
        ax3.scatter([predict["date"]], [predict["累计净值"]], color="red", zorder=5, s=40, label="今日预测")
        ax3.legend(loc="upper left")

    ax4.plot(tail["净值日期"], tail["近60日估值分位"], color="blue", linewidth=2)
    ax4.set_xlabel("日期"); ax4.set_ylabel("近60日估值分位"); ax4.set_title("近250日估值分位(60日窗口)")
    ax4.tick_params(axis="x", rotation=40); ax4.margins(y=0.1); ax4.invert_yaxis()
    if predict and not pd.isna(predict["估值分位"]):
        ax4.scatter([predict["date"]], [predict["估值分位"]], color="red", zorder=5, s=40)

    fig.suptitle(f"{name}（{fund_code}）走势仪表盘", fontsize=14)
    fig.savefig(os.path.join(folder, "历史趋势.png"), dpi=200)
    plt.close(fig)


def _save_interactive_html(df, fund_code, name, fund_type, signal, valuation, drawdown, predict, folder, index_val=None):
    """生成可交互的 HTML 走势图（ECharts）：
       - 上图 = 净值相关（累计净值 + 单位净值 + MA20 + MA120）；
       - 下图 = 估值分位（全历史分位 + 近60日短期分位 + 高/低估线）；
       - 顶部 From/To 日期筛选框，默认展示全部历史，上下两图日期滑块联动同步；
       - 点击图例可开关 均线 / 高·低估线；
       - 估值分位图 y 轴反向：越往上越“贵”(分位小)，越往下越“便宜”(分位大)；
       - 若设了今日预测，两图都会标红今日预测点。"""
    dfp = df.sort_values("净值日期").reset_index(drop=True)
    dates = [pd.to_datetime(x).strftime("%Y-%m-%d") for x in dfp["净值日期"]]
    first_date, last_date = (dates[0] if dates else ""), (dates[-1] if dates else "")

    def pairs(colname):
        out = []
        for d, v in zip(dates, dfp[colname].tolist()):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                continue
            out.append([d, round(float(v), 5)])
        return out

    latest_nav = None
    for v in reversed(dfp["累计净值"].tolist()):
        if v is not None and not (isinstance(v, float) and pd.isna(v)):
            latest_nav = round(float(v), 4)
            break

    data = {
        "cum": pairs("累计净值"),
        "unit": pairs("单位净值"),
        "ma20": pairs("MA20"),
        "ma120": pairs("MA120"),
        "val": pairs("估值分位"),
        "over": pairs("高估线"),
        "under": pairs("低估线"),
        "p60": pairs("近60日估值分位"),
    }
    info = {
        "code": fund_code, "name": name, "type": fund_type or "-",
        "nav": latest_nav, "signal": signal, "valuation": valuation, "drawdown": drawdown,
    }
    if predict and not pd.isna(predict.get("估值分位")):
        predict_js = json.dumps({
            "date": pd.to_datetime(predict["date"]).strftime("%Y-%m-%d"),
            "cum": round(float(predict["累计净值"]), 5),
            "val": round(float(predict["估值分位"]), 5),
        }, ensure_ascii=False)
    else:
        predict_js = "null"

    # 估值结论 7 档 → 粗分类（仅用于配色）
    coarse = ("over" if signal in ("严重高估", "高估")
              else "under" if signal in ("低估", "严重低估")
              else "fair")

    # 指数估值补充信息（仅指数/ETF 基金有）
    index_line = ""
    if index_val:
        index_line = (f"｜ 指数估值({index_val['index']}) PE：<b>{index_val['pe']}</b> "
                      f"｜ PE分位：<b>{index_val['pe_pct']}</b>（越大越便宜）")

    chart_js = (
        "var DATA = __DATA__;"
        "var INFO = __INFO__;"
        "var PREDICT = __PREDICT__;"
        "var navChart = echarts.init(document.getElementById('navChart'));"
        "var valChart = echarts.init(document.getElementById('valChart'));"
        "var navOption = {"
        "  title: { text: INFO.name + '（' + INFO.code + '）净值相关', left: 'center' },"
        "  tooltip: { trigger: 'axis' },"
        "  legend: { top: 28, data: ['累计净值','单位净值','MA20','MA120'] },"
        "  grid: { left: 64, right: 24, top: 64, bottom: 80 },"
        "  xAxis: { type: 'time' },"
        "  yAxis: { type: 'value', scale: true },"
        "  dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 18 }],"
        "  series: ["
        "    { name: '累计净值', type: 'line', showSymbol: false, data: DATA.cum, lineStyle:{width:2} },"
        "    { name: '单位净值', type: 'line', showSymbol: false, data: DATA.unit, lineStyle:{width:1, opacity:0.6} },"
        "    { name: 'MA20', type: 'line', showSymbol: false, data: DATA.ma20 },"
        "    { name: 'MA120', type: 'line', showSymbol: false, data: DATA.ma120 }"
        "  ]"
        "};"
        "var valOption = {"
        "  title: { text: '估值分位（越往上越贵 / 越往下越便宜）', left: 'center' },"
        "  tooltip: { trigger: 'axis' },"
        "  legend: { top: 28, data: ['全历史分位','高估线','低估线','近60日(短期)'] },"
        "  grid: { left: 64, right: 24, top: 64, bottom: 80 },"
        "  xAxis: { type: 'time' },"
        "  yAxis: { type: 'value', scale: true, inverse: true, min: 0, max: 1 },"
        "  dataZoom: [{ type: 'inside', xAxisIndex: 0 }, { type: 'slider', xAxisIndex: 0, bottom: 18 }],"
        "  series: ["
        "    { name: '全历史分位', type: 'line', showSymbol: false, data: DATA.val, lineStyle:{width:2} },"
        "    { name: '高估线', type: 'line', showSymbol: false, data: DATA.over, lineStyle:{type:'dashed', color:'#e74c3c'} },"
        "    { name: '低估线', type: 'line', showSymbol: false, data: DATA.under, lineStyle:{type:'dashed', color:'#27ae60'} },"
        "    { name: '近60日(短期)', type: 'line', showSymbol: false, data: DATA.p60 }"
        "  ]"
        "};"
        "if (PREDICT) {"
        "  navOption.series.push({ name: '今日预测', type: 'scatter', symbolSize: 12, itemStyle:{color:'#e74c3c'}, data: [[PREDICT.date, PREDICT.cum]] });"
        "  valOption.series.push({ name: '今日预测', type: 'scatter', symbolSize: 12, itemStyle:{color:'#e74c3c'}, data: [[PREDICT.date, PREDICT.val]] });"
        "  navOption.legend.data.push('今日预测');"
        "  valOption.legend.data.push('今日预测');"
        "}"
        "navChart.setOption(navOption);"
        "valChart.setOption(valOption);"
        "try { echarts.connect([navChart, valChart]); } catch(e){}"
        "var MIN_TS = new Date('__MINDATE__').getTime();"
        "var MAX_TS = new Date('__MAXDATE__').getTime();"
        "function tsOf(s){ return s ? new Date(s).getTime() : null; }"
        "function applyRange(){"
        "  var f = tsOf(document.getElementById('fromDate').value);"
        "  var t = tsOf(document.getElementById('toDate').value);"
        "  navChart.dispatchAction({type:'dataZoom', startValue: (f!=null?f:MIN_TS), endValue: (t!=null?t:MAX_TS)});"
        "}"
        "function resetRange(){"
        "  navChart.dispatchAction({type:'dataZoom', startValue: MIN_TS, endValue: MAX_TS});"
        "  document.getElementById('fromDate').value='';"
        "  document.getElementById('toDate').value='';"
        "}"
        "window.addEventListener('resize', function(){ navChart.resize(); valChart.resize(); });"
    )
    chart_js = chart_js.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    chart_js = chart_js.replace("__INFO__", json.dumps(info, ensure_ascii=False))
    chart_js = chart_js.replace("__PREDICT__", predict_js)
    chart_js = chart_js.replace("__MINDATE__", first_date)
    chart_js = chart_js.replace("__MAXDATE__", last_date)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name}（{fund_code}）走势图</title>
<style>
 body {{ font-family: "Microsoft YaHei", Arial, sans-serif; margin: 0; background: #fafafa; color: #222; }}
 header {{ padding: 16px 20px; background: #fff; border-bottom: 1px solid #eee; }}
 header h1 {{ margin: 0 0 6px; font-size: 20px; }}
 .meta {{ font-size: 13px; color: #555; line-height: 1.7; }}
 .meta b {{ color: #111; }}
 .tag {{ display:inline-block; padding:2px 10px; border-radius: 10px; margin-right:6px; font-size:12px; }}
 .over {{ background:#fdecea; color:#c0392b; }}
 .under {{ background:#eafaf1; color:#1e8449; }}
 .fair {{ background:#eef4fb; color:#2471a3; }}
 .filter {{ padding: 10px 20px; background:#fff; border-bottom:1px solid #eee; font-size:13px; }}
 .filter input {{ margin:0 4px; padding:2px 4px; }}
 .filter button {{ margin-left:6px; padding:2px 10px; cursor:pointer; }}
 .filter .hint {{ color:#888; margin-left:8px; }}
 #navChart, #valChart {{ width: 100%; height: 380px; background:#fff; }}
 .chart-box {{ padding: 8px 12px 8px; }}
 .note {{ padding: 4px 20px 20px; font-size: 12px; color:#888; }}
</style>
</head>
<body>
<header>
  <h1>{name}（{fund_code}）</h1>
  <div class="meta">
    类型：<b>{fund_type or '-'}</b> ｜ 最新累计净值：<b>{latest_nav if latest_nav is not None else '-'}</b>
    ｜ 估值结论：<span class="tag {coarse}">{signal}</span>
    ｜ 净值估值分位：<b>{valuation if valuation is not None else '-'}</b>
    ｜ 近一年最大回撤：<b>{drawdown if drawdown is not None else '-'}</b>
    <br>{index_line}
  </div>
</header>
<div class="filter">
  <b>日期筛选：</b>从
  <input type="date" id="fromDate" min="{first_date}" max="{last_date}">
  到
  <input type="date" id="toDate" min="{first_date}" max="{last_date}">
  <button onclick="applyRange()">应用</button>
  <button onclick="resetRange()">全部</button>
  <span class="hint">默认展示全部历史；上下两图日期滑块联动同步，也可拖动下方滑块 / 滚轮缩放</span>
</div>
<div class="chart-box"><div id="navChart"></div></div>
<div class="chart-box"><div id="valChart"></div></div>
<div class="note">
  上图＝净值相关（累计净值 / 单位净值 / MA20 / MA120）；下图＝估值分位（全历史分位 + 近60日短期分位 + 高/低估线）。
  估值分位 = 历史上净值「高于」今日的交易日占比：值越大越便宜、越小越贵。长期上涨的基金全历史分位常偏低（总显贵），此时看“近60日(短期)”更准。
  图表库 ECharts 经 CDN 加载，首次查看需联网；断网时可用同目录「历史趋势.png」。
</div>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<script>{chart_js}</script>
</body>
</html>
"""
    with open(os.path.join(folder, "走势图.html"), "w", encoding="utf-8") as f:
        f.write(html)


def analyze_signals(df: pd.DataFrame, fund_code: str, name: str, fund_type: str = "", predict_today: Optional[float] = None, index_val: Optional[dict] = None) -> pd.DataFrame:
    """
    打信号、统计连续天数，并落盘 CSV / HTML / PNG。
    - 落盘的 CSV/HTML/图均基于“真实历史”（不含预测行），保证历史数据干净、不会重复累加预测。
    - 若给定 predict_today，仅在走势图上叠加一个红色“今日预测”点用于直观参考。
    """
    df = _assign_signals(df, fund_type)
    df["信号段"] = (df["信号"] != df["信号"].shift()).cumsum()
    df["信号连续天数"] = df.groupby("信号段").cumcount() + 1
    df = df.drop(columns=["信号段"]).sort_values("净值日期", ascending=False).reset_index(drop=True)

    d = resolve_fund_dir(fund_code, name)
    os.makedirs(d, exist_ok=True)
    df.to_csv(os.path.join(d, "历史净值.csv"), encoding="utf-8-sig", index=False, float_format="%.5f")
    _save_html(df, os.path.join(d, "历史净值.html"))
    predict_point = _predict_row(df, predict_today) if predict_today is not None else None
    _save_png(df, fund_code, name, d, predict=predict_point)

    latest = df.iloc[0]
    signal = latest["估值结论"]
    valuation = None if pd.isna(latest["估值分位"]) else round(float(latest["估值分位"]), 4)
    drawdown = None if pd.isna(latest["年最大回撤"]) else round(float(latest["年最大回撤"]), 4)
    _save_interactive_html(df, fund_code, name, fund_type, signal, valuation, drawdown, predict_point, d, index_val=index_val)
    return df


# ----------------------------------------------------------------------------
# 6) 对外总入口
# ----------------------------------------------------------------------------
def run_fund(
    fund_code: str,
    name: Optional[str] = None,
    offline: bool = False,
    predict_today: Optional[float] = None,
    with_holdings: bool = True,
) -> dict:
    """
    跑完一只基金的全部流程，返回摘要 dict。

    参数：
        fund_code     基金代码（6 位）
        name          已知名称（可选，联网时会自动补全并识别类型）
        offline       离线模式：True 时不联网，仅用本地缓存（断网查看旧数据用）
        predict_today 该基金“今日预测涨幅(%)”，None 表示不追加（临时展示，不影响历史数据）
        with_holdings 是否抓取持仓（债券/货币类无持仓，可关掉省时间）
    """
    code = str(fund_code).zfill(6)
    basic: dict = {}
    try:
        basic = get_fund_basic(code)
        name = basic.get("基金名称") or name or code
        fund_type = basic.get("基金类型", "")
    except Exception as e:  # noqa
        print(f"[{code}] 基本信息抓取失败：{e}")
        name, fund_type = (name or code), ""

    # 指数/ETF 类基金额外抓“跟踪指数”的市盈率分位（主动基金无统一 PE，返回 None）
    index_val = None
    try:
        index_val = fetch_index_valuation(fund_type, basic)
    except Exception as e:  # noqa
        print(f"[{code}] 指数估值抓取失败（可忽略）：{e}")

    if with_holdings:
        try:
            get_holdings(code, name)
        except Exception as e:  # noqa
            print(f"[{code}] 持仓抓取失败（可忽略）：{e}")

    nav = fetch_nav(code, offline=offline)                   # 真实历史（不含预测）
    analyzed = analyze_signals(nav, code, name, fund_type=fund_type, predict_today=predict_today, index_val=index_val)

    latest = analyzed.iloc[0]
    signal = latest["估值结论"]          # 统一估值结论（高估/低估/合理），所有类型一致
    detail = latest["信号"]              # 细节（动能/回撤/极端涨跌等），仅作参考
    valuation = None if pd.isna(latest["估值分位"]) else round(float(latest["估值分位"]), 4)

    # 若设了今日预测：用临时叠加行算出一个“含预测的当日结论/分位”仅用于展示
    if predict_today is not None:
        temp = _assign_signals(_append_predict(nav, predict_today), fund_type)
        signal = temp.iloc[-1]["估值结论"]
        detail = temp.iloc[-1]["信号"]
        valuation = None if pd.isna(temp.iloc[-1]["估值分位"]) else round(float(temp.iloc[-1]["估值分位"]), 4)

    return {
        "code": code,
        "name": name,
        "type": fund_type,
        "updated": str(pd.to_datetime(latest["净值日期"]).date()),
        "latest_nav": float(latest["单位净值"]),
        "signal": signal,
        "detail": detail,
        "valuation": valuation,
        "drawdown": None if pd.isna(latest["年最大回撤"]) else round(float(latest["年最大回撤"]), 4),
        "index_val": index_val,
        "dir": resolve_fund_dir(code, name),
    }


if __name__ == "__main__":
    import sys
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 1000)
    test_code = sys.argv[1] if len(sys.argv) > 1 else "012414"
    res = run_fund(test_code)
    print(json.dumps(res, ensure_ascii=False, indent=2))
