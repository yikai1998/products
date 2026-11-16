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
from html import escape as html_escape   # 用别名，避免被模板里的局部变量 html 遮蔽

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

# ----------------------------------------------------------------------------
# 估值分位阈值（可配置）：高估线=估值分位序列的 over 分位(小→贵)，低估线=under 分位(大→便宜)。
# 默认 0.10 / 0.90。若要调整，在项目目录建 fund_config.json：
#   {"valuation_quantiles": {"over": 0.10, "under": 0.90}}
# 例如长期上涨的 QDII 全历史分位常偏低，可自行改成 over=0.15 / under=0.85 再用回测验证。
# 修改后需重启程序生效。
# ----------------------------------------------------------------------------
def _load_val_quantiles():
    over, under = 0.10, 0.90
    path = os.path.join(BASE_DIR, "fund_config.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                vq = json.load(f).get("valuation_quantiles", {})
            over = float(vq.get("over", over))
            under = float(vq.get("under", under))
            if not (0 < over < under < 1):
                raise ValueError("需满足 0 < over < under < 1")
        except Exception:
            pass  # 配置非法则静默用默认
    return over, under


VAL_OVER_Q, VAL_UNDER_Q = _load_val_quantiles()

# ----------------------------------------------------------------------------
# 个人持仓成本（独立文件 持仓成本.json，默认不入库）
#   cost   = 成本单价，按【单位净值】口径 —— 申购按当日单位净值确认份额，成交价就是单位净值
#   shares = 持有份额，可选；填了才能算浮动盈亏金额
#   note   = 备注，可选
# 注意：累计净值 = 单位净值 + 历史累计分红，是「业绩口径」，用于画走势消除分红除权造成的假跌，
#       不是成交价，不能当成本。二者混用会把分红当成收益，凭空虚增盈亏。
# ----------------------------------------------------------------------------
COST_PATH = os.path.join(BASE_DIR, "持仓成本.json")


def load_costs() -> dict:
    """读取个人持仓成本；文件不存在 / 损坏时返回空 dict（绝不因缺成本中断分析）。"""
    if not os.path.exists(COST_PATH):
        return {}
    try:
        with open(COST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {str(k).zfill(6): v for k, v in data.items()
                if str(k).isdigit() and isinstance(v, dict)}
    except Exception:
        return {}


def save_costs(data: dict) -> None:
    """写回个人持仓成本（GUI「💰 设成本」调用）。"""
    with open(COST_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_cost(code: str) -> Optional[dict]:
    """取某只基金的成本信息；未填或数值非法时返回 None。"""
    it = load_costs().get(str(code).zfill(6))
    if not it:
        return None
    try:
        c = float(it.get("cost"))
        if c <= 0 or c != c:
            return None
    except (TypeError, ValueError):
        return None
    out = {"cost": c}
    try:
        s = float(it.get("shares"))
        if s > 0 and s == s:
            out["shares"] = s
    except (TypeError, ValueError):
        pass
    if it.get("note"):
        out["note"] = str(it["note"])
    return out

# 中文字体：给出跨平台候选列表（Mac=PingFang/Heiti，Win=雅黑/SimHei，Linux=文泉驿），
# matplotlib 会依次尝试，保证 Mac 与 Windows 上中文都能正常显示。
plt.rcParams["font.sans-serif"] = [
    "PingFang SC", "Heiti SC", "Microsoft YaHei", "SimHei",
    "Arial Unicode MS", "WenQuanYi Micro Hei", "sans-serif",
]
plt.rcParams["axes.unicode_minus"] = False


# ----------------------------------------------------------------------------
# 所有基金产物统一收进「基金报告/」，根目录只留代码与配置。
# 之前雷达抓净值时调用 resolve_fund_dir(code) 不带名称 → 建纯数字目录；
# 分析时带名称 → 又建一个「名称_基金代码code」目录，同一只基金出现两个文件夹。
# 现在无名称时自动从名单/候选池补名称，双口径归一，从根上杜绝重复建目录。
FUND_ROOT = os.path.join(BASE_DIR, "基金报告")


def _lookup_fund_name(code: str) -> str:
    """从 funds.json / radar_pool.json 按代码查名称，供不带 name 的调用统一命名。"""
    for fn in ("funds.json", "radar_pool.json"):
        path = os.path.join(BASE_DIR, fn)
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for it in json.load(f):
                    if str(it.get("code", "")).zfill(6) == code and it.get("name"):
                        return str(it["name"]).strip()
        except Exception:
            pass
    return ""


def _safe_folder_name(s: str) -> str:
    """去掉 Windows/macOS 文件名非法字符，避免新建目录失败。"""
    return re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", s).strip().rstrip(".")


def resolve_fund_dir(fund_code: str, name: Optional[str] = None) -> str:
    """定位（或创建）基金专属目录，统一放在 基金报告/ 下。

    查找顺序：① 基金报告/ 里「*基金代码code」命名目录 → ② 纯数字 code 目录（兼容旧缓存）
    → ③ 都没有则在 基金报告/ 下新建。新建时名称优先取参数，其次从名单/候选池补齐。
    """
    code = str(fund_code).zfill(6)
    root = FUND_ROOT
    os.makedirs(root, exist_ok=True)
    if os.path.isdir(root):
        entries = [e for e in os.listdir(root) if os.path.isdir(os.path.join(root, e))]
        # ① 带名称的规范目录（改名后也能命中，只要代码后缀不变）
        for entry in entries:
            if entry.endswith(f"基金代码{code}"):
                return os.path.join(root, entry)
        # ② 兼容历史纯数字目录，直接复用，不再新建第二个
        if code in entries:
            return os.path.join(root, code)
    nm = _safe_folder_name(str(name or _lookup_fund_name(code) or ""))
    folder_name = f"{nm}_基金代码{code}" if nm else code
    return os.path.join(root, folder_name)


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
    df["高估线"] = df["估值分位"].rolling(win, min_periods=250).quantile(VAL_OVER_Q).shift(1)
    df["低估线"] = df["估值分位"].rolling(win, min_periods=250).quantile(VAL_UNDER_Q).shift(1)

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


def _price_reference(df: pd.DataFrame, window: int = 250) -> Optional[dict]:
    """近端「价格通道」：用最近 window 个交易日的累计净值分布，给出相对低位/高位区。

    为什么不能用全历史反推（旧实现的 bug）：
      估值分位 = 截至当日「历史净值高于今日」的占比。对长期创新高的基金
      （如成立十余年的债基 050011），价格中枢从 1.0 一路升到 3.6+，
      于是「分位大（便宜）」的日子几乎全部集中在成立初期 2009 年附近。
      旧实现拿**最新一条**高低估线去筛**全历史**样本，得到买区 1.02~1.09、
      卖区 1.13~3.11，而今日净值 3.63 —— 区间整体停在十几年前的价格水平，
      既够不着也卖不掉，纯属误导。且最新 rolling 线套到 2009 年数据上本身是口径错配。

    现在只描述「近期价格分布」，不做全历史外推、不预测未来价格：
      近 window 日净值的 15%~35% 分位 = 相对低位区；65%~85% 分位 = 相对高位区。
      取分位带而非 min/max，避免单日尖峰把区间撑歪。

    双口径（计算逻辑完全相同，只是换一列重算一遍）：
      · 累计净值（主口径，用来判断相对位置）：＝ 单位净值 ＋ 历史每份累计分红的
        「简单加回」，**没有按除权日再投算复利**，并非严格意义上的复权净值。
        好处是分红除权不会让它向下跳空，适合看「当前价落在近期分布的哪一段」。
      · 单位净值（副口径，用来对照成本）：实际成交价、App 里看到的数字、
        「我的成本」都是这个口径。但期间一旦分红，曲线会向下跳空，通道会失真，
        所以只作数字对照，不拿来判高低。
    """
    try:
        asc = df.sort_values("净值日期").reset_index(drop=True)
        cum = pd.to_numeric(asc["累计净值"], errors="coerce").dropna()
        if len(cum) < 60:
            return None
        tail = cum.tail(window)
        n = len(tail)
        if n < 60:
            return None

        def _channel(s: pd.Series) -> dict:
            cur = float(s.iloc[-1])
            bl, bh = float(s.quantile(0.15)), float(s.quantile(0.35))
            sl, sh = float(s.quantile(0.65)), float(s.quantile(0.85))
            if cur < bl:
                pos = "below_buy"
            elif cur <= bh:
                pos = "in_buy"
            elif cur < sl:
                pos = "mid"
            elif cur <= sh:
                pos = "in_sell"
            else:
                pos = "above_sell"
            return {"cur": cur, "buy_low": bl, "buy_high": bh,
                    "sell_low": sl, "sell_high": sh, "position": pos}

        main = _channel(tail)
        dates = asc.loc[tail.index, "净值日期"]

        # 同一批交易日上的单位净值；缺列或样本不足时只给累计口径
        unit = pd.to_numeric(asc.loc[tail.index, "单位净值"], errors="coerce").dropna()
        unit_ch = _channel(unit) if len(unit) >= 60 else None
        # gap = 累计分红沉淀；gap_span > 0 说明窗口内发生过分红/份额折算
        gap_series = (
            pd.to_numeric(asc.loc[tail.index, "累计净值"], errors="coerce")
            - pd.to_numeric(asc.loc[tail.index, "单位净值"], errors="coerce")
        ).dropna()
        gap = float(gap_series.iloc[-1]) if len(gap_series) else 0.0
        gap_span = float(gap_series.max() - gap_series.min()) if len(gap_series) else 0.0

        return {
            **main, "window": n,
            "start": pd.to_datetime(dates.iloc[0]).strftime("%Y-%m-%d"),
            "end": pd.to_datetime(dates.iloc[-1]).strftime("%Y-%m-%d"),
            "lo": float(tail.min()), "hi": float(tail.max()),
            "unit": unit_ch, "gap": gap, "gap_span": gap_span,
        }
    except Exception:
        return None


def backtest_valuation(df: pd.DataFrame, horizons=(20, 60, 120)) -> Optional[dict]:
    """轻量回测：验证“低估区买入并持有 N 日”是否比“任意日买入”更划算。

    方法（用累计净值＝单位净值＋历史每份累计分红，简单加回、未复利，不受除权跳空干扰）：
      - 买入信号：某日估值分位跨过/位于低估线之上（val >= under）且前一日不在低估区 → 记为一次买点；
        若低估区持续多日，只在“首次进入”记一次，避免重复计数。
      - 对每个买点，计算持有 h 个交易日后的累计净值收益率。
      - 基准：全样本中所有交易日买入并持有 h 日的平均收益（买入并持有/择时对比）。
      - 输出：买点数、各持有期的平均/中位收益、胜率(收益>0占比)、基准平均收益、超额。
    说明：样本内统计、未计交易成本，仅验证信号方向是否成立，绝非未来收益承诺。
    """
    try:
        asc = df.sort_values("净值日期").reset_index(drop=True)
        cum = pd.to_numeric(asc["累计净值"], errors="coerce").values
        val = pd.to_numeric(asc["估值分位"], errors="coerce").values
        under = pd.to_numeric(asc["低估线"], errors="coerce").values
        n = len(cum)
        if n < 60:
            return None
        # 买点：进入低估区（今日 val>=under 且 昨日 val<under）；under 为 NaN 的日子跳过
        # i=0 也算：若首日即在低估区，视为一个买点（无“昨日”则默认昨日不在低估区）。
        buys = []
        for i in range(n):
            if pd.isna(under[i]) or pd.isna(val[i]) or pd.isna(cum[i]):
                continue
            prev_in = (i > 0 and (not pd.isna(under[i - 1])) and
                       (not pd.isna(val[i - 1])) and (val[i - 1] >= under[i - 1]))
            if val[i] >= under[i] and not prev_in:
                buys.append(i)
        if not buys:
            return None

        def fwd_ret(i, h):
            if i + h >= n or pd.isna(cum[i]) or pd.isna(cum[i + h]) or cum[i] <= 0:
                return None
            return float(cum[i + h] / cum[i] - 1.0)

        out = {"buy_count": len(buys), "horizons": {}}
        for h in horizons:
            sig_rets = [r for i in buys if (r := fwd_ret(i, h)) is not None]
            base_rets = [r for i in range(n - h) if (r := fwd_ret(i, h)) is not None]
            if not sig_rets or not base_rets:
                continue
            s = pd.Series(sig_rets)
            out["horizons"][str(h)] = {
                "count": len(sig_rets),
                "avg": round(float(s.mean()), 4),
                "median": round(float(s.median()), 4),
                "win_rate": round(float((s > 0).mean()), 4),
                "base_avg": round(float(pd.Series(base_rets).mean()), 4),
                "excess": round(float(s.mean() - pd.Series(base_rets).mean()), 4),
            }
        return out if out["horizons"] else None
    except Exception:
        return None


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

    # 把“今日预测”用红色虚线连到最后一个真实数据点，避免孤立红点挡住走势
    def _connect(ax, last_x, last_y, pdate, pval, label):
        if last_x is not None and pdate is not None:
            ax.plot([last_x, pdate], [last_y, pval], color="red", linestyle="--",
                    linewidth=1.5, zorder=4)
        ax.scatter([pdate], [pval], color="red", zorder=5, s=36, label=label)
        ax.legend(loc="upper left")

    fig, axes = plt.subplots(nrows=2, ncols=2, figsize=(22, 8), constrained_layout=True)
    ax1, ax2, ax3, ax4 = axes[0, 0], axes[0, 1], axes[1, 0], axes[1, 1]

    ax1.plot(df_plot["净值日期"], df_plot["累计净值"], color="blue", linewidth=2)
    ax1.set_xlabel("日期"); ax1.set_ylabel("累计净值"); ax1.set_title("全历史累计净值走势")
    ax1.tick_params(axis="x", rotation=40); ax1.margins(y=0.1)
    if predict:
        _connect(ax1, df_plot["净值日期"].iloc[-1], df_plot["累计净值"].iloc[-1],
                 predict["date"], predict["累计净值"], "今日预测")

    ax2.plot(df_plot["净值日期"], df_plot["估值分位"], color="blue", linewidth=2)
    ax2.plot(df_plot["净值日期"], df_plot["高估线"], color="red", linestyle="--", linewidth=1.8, label="高估线")
    ax2.plot(df_plot["净值日期"], df_plot["低估线"], color="green", linestyle="--", linewidth=1.8, label="低估线")
    ax2.set_xlabel("日期"); ax2.set_ylabel("估值分位"); ax2.set_title("全历史估值分位 + 高/低估线")
    ax2.tick_params(axis="x", rotation=40); ax2.margins(y=0.1); ax2.invert_yaxis()
    ax2.legend(loc="lower right", fontsize=8, framealpha=0.8)
    if predict and not pd.isna(predict["估值分位"]):
        _connect(ax2, df_plot["净值日期"].iloc[-1], df_plot["估值分位"].iloc[-1],
                 predict["date"], predict["估值分位"], "今日预测")

    tail = df_plot.tail(250)
    ax3.plot(tail["净值日期"], tail["累计净值"], color="blue", linewidth=2)
    ax3.set_xlabel("日期"); ax3.set_ylabel("累计净值"); ax3.set_title("近250日累计净值走势")
    ax3.tick_params(axis="x", rotation=40); ax3.margins(y=0.1)
    if predict:
        _connect(ax3, tail["净值日期"].iloc[-1], tail["累计净值"].iloc[-1],
                 predict["date"], predict["累计净值"], "今日预测")

    ax4.plot(tail["净值日期"], tail["近60日估值分位"], color="blue", linewidth=2)
    ax4.set_xlabel("日期"); ax4.set_ylabel("近60日估值分位"); ax4.set_title("近250日估值分位(60日窗口)")
    ax4.tick_params(axis="x", rotation=40); ax4.margins(y=0.1); ax4.invert_yaxis()
    if predict and not pd.isna(predict["估值分位"]):
        _connect(ax4, tail["净值日期"].iloc[-1], tail["近60日估值分位"].iloc[-1],
                 predict["date"], predict["估值分位"], "今日预测")

    fig.suptitle(f"{name}（{fund_code}）走势仪表盘", fontsize=14)
    fig.savefig(os.path.join(folder, "历史趋势.png"), dpi=200)
    plt.close(fig)


def _save_interactive_html(df, fund_code, name, fund_type, signal, valuation, drawdown, predict, folder, index_val=None, price_ref=None, backtest=None, cost=None):
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

    def _last_num(col):
        """取某指标最后一个有效值（dfp 已按日期升序）。"""
        if col not in dfp.columns:
            return None
        s = pd.to_numeric(dfp[col], errors="coerce").dropna()
        return float(s.iloc[-1]) if len(s) else None

    long_val = _last_num("估值分位")          # 全历史口径
    short_val = _last_num("近60日估值分位")   # 近端口径
    unit_now = _last_num("单位净值")          # 成本/盈亏必须用单位净值（成交价口径）

    # ---- 个人持仓成本：卡片 + 口径说明 + 图上成本水平线 ----
    cost_card = ""
    cost_note = ""
    cost_js = {"cost": None, "line": []}
    if cost and cost.get("cost") and unit_now is not None:
        c = float(cost["cost"])
        pnl = unit_now / c - 1
        shares = cost.get("shares")
        amt = (unit_now - c) * shares if shares else None
        # 中国习惯：盈利红、亏损绿
        col = "#c0392b" if pnl >= 0 else "#1e8449"
        amt_txt = f" ／ {amt:+,.0f} 元" if amt is not None else ""
        note_txt = f" ｜ {html_escape(str(cost['note']))}" if cost.get("note") else ""
        cost_card = (
            f"<div class='card'><div class='k'>我的成本（单位净值）</div><div class='v'>{c:.4f}</div></div>"
            f"<div class='card'><div class='k'>浮动盈亏</div>"
            f"<div class='v'><span style='color:{col};font-weight:700'>{pnl*100:+.2f}%{amt_txt}</span></div></div>"
        )
        cost_note = (
            f"<br><b>关于成本：</b>盈亏按<b>单位净值</b>计算（申购按单位净值确认份额，成交价就是单位净值）；"
            f"累计净值＝单位净值＋历史累计分红，是业绩口径，<b>不能当成本</b>。"
            f"此处未计手续费与现金分红，红利再投后请更新份额。{note_txt}"
        )
        cost_js = {"cost": c, "line": [[first_date, c], [last_date, c]]}

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
    # 最后一个真实数据点（用于把“今日预测”连到历史走势上，避免孤立红点）
    try:
        _last_date = dates[-1]
        _lc = dfp["累计净值"].iloc[-1]
        _lv = dfp["估值分位"].iloc[-1]
        last_real = [_last_date, None if pd.isna(_lc) else round(float(_lc), 5)]
        last_real_val = [_last_date, None if pd.isna(_lv) else round(float(_lv), 5)]
    except Exception:
        last_real, last_real_val = [None, None], [None, None]
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

    # 指数估值补充信息（仅指数/ETF 基金有）——做成一张卡片
    index_card = ""
    if index_val:
        index_card = (f"<div class='card'><div class='k'>指数估值 · {index_val['index']}</div>"
                      f"<div class='v'>PE {index_val['pe']} ｜ PE分位 {index_val['pe_pct']}</div></div>")

    # 近期价格通道：近 250 交易日的相对低位/高位区（双口径并列，不是未来目标价）
    if price_ref:
        def _fmt(x):
            return "-" if x is None else f"{x:.4f}"
        pos_tip = {
            "below_buy": ("#1e8449", "当前价低于近端低位区：正处在回撤 / 下行段，通道只描述过去，不代表已经见底。"),
            "in_buy": ("#1e8449", "当前价落在近端低位区（相对便宜的一段）。"),
            "mid": ("#2471a3", "当前价处于近端通道中部。"),
            "in_sell": ("#c0392b", "当前价落在近端高位区（相对贵的一段）。"),
            "above_sell": ("#c0392b", "当前价高于近端高位区：处于创新高段，历史通道已不适用，别按上界机械卖出。"),
        }
        pos_color, pos_text = pos_tip.get(price_ref["position"], ("#555", ""))

        def _row(label, ch, hint=""):
            return (
                f"<div class='row'><span class='lbl'>{label}</span>"
                f"<span class='buy'>相对低位区 {_fmt(ch['buy_low'])}~{_fmt(ch['buy_high'])}</span>"
                f" ｜ <span class='sell'>相对高位区 {_fmt(ch['sell_low'])}~{_fmt(ch['sell_high'])}</span>"
                f" ｜ 当前 <b>{_fmt(ch['cur'])}</b>{hint}</div>"
            )

        rows_html = _row("累计净值 · 判断相对位置", price_ref)
        gap = price_ref.get("gap", 0.0)
        gap_span = price_ref.get("gap_span", 0.0)
        unit = price_ref.get("unit")
        notes = []
        if unit is None:
            notes.append("缓存缺少单位净值数据，本次只给累计口径。")
        elif abs(gap) < 1e-6:
            notes.append("该基金无分红，单位净值与累计净值数值一致，可直接对照成本价。")
        else:
            rows_html += _row(
                "单位净值 · 对照成本价", unit,
                " <span style='color:#8e44ad;font-size:12px'>← 可直接与「我的成本」对比</span>",
            )
            notes.append(
                f"两种口径相差 <b>{gap:+.4f}</b>（累计净值 − 单位净值；正常情况即历史每份累计分红）。"
                "累计净值只是把分红简单加回、<b>未按除权日再投复利</b>，不是严格复权净值；"
                "但它不会因分红除权跳空，所以判断相对高低以累计口径为准，"
                "单位净值那行只用来和你在 App 里看到的价格 / 成本价对照。"
            )
            if gap_span > 1e-6:
                notes.append(
                    "⚠ 近端窗口内发生过分红或份额折算，单位净值曲线存在向下跳空，"
                    "该行仅供看数字，不宜据此判断高低位。"
                )
            if gap < -1e-6:
                notes.append(
                    "⚠ 数据源里该基金累计净值低于单位净值（多见于做过份额折算的老基金），"
                    "绝对数值可能失真，通道只看相对位置。"
                )

        # 长短周期口径分歧：全历史分位 vs 近60日分位方向相反时，明确提示以短周期为主
        if long_val is not None and short_val is not None and (
            (long_val <= 0.20 and short_val >= 0.80) or (long_val >= 0.80 and short_val <= 0.20)
        ):
            notes.append(
                f"⚠ 长短周期口径分歧：全历史估值分位 {long_val:.2f}、近60日估值分位 {short_val:.2f}。"
                "该基金长期创新高，全历史分位会天然趋近 0（显得偏贵）；"
                "这类品种请以近60日分位 + 趋势为主，全历史分位只作背景。"
            )
        notes.append(
            "这是「过去一段时间价格落在哪个区间」的统计，<b>不是未来目标价、不是买卖指令</b>；"
            "区间随行情滚动变化。全历史样本不能用来反推买区——长期上涨基金十几年前 1 元附近的价位，"
            "对今天毫无参考意义。"
        )
        notes_html = "".join(f"<div class='tip'>{t}</div>" for t in notes)
        price_ref_html = (
            f"<div class='pricebar'>"
            f"<div class='ttl'>📌 <b>近期价格通道</b>"
            f"（近 {price_ref['window']} 个交易日 {price_ref['start']} ~ {price_ref['end']}，"
            f"两种净值口径、算法完全相同）</div>"
            f"{rows_html}"
            f"<div class='tip' style='color:{pos_color}'>{pos_text}</div>"
            f"{notes_html}</div>"
        )
    else:
        price_ref_html = ""

    # 回测小结：低估买入持有 N 日 vs 任意日买入（样本内统计，非未来收益承诺）
    backtest_html = ""
    if backtest and backtest.get("horizons"):
        def pct(x):
            return f"{x*100:+.1f}%"
        rows = []
        for h, m in backtest["horizons"].items():
            cls = "up" if m["excess"] > 0 else "down"
            rows.append(
                f"<tr><td>持有 {h} 个交易日</td>"
                f"<td>{pct(m['avg'])}</td>"
                f"<td>{pct(m['win_rate'])}</td>"
                f"<td>{pct(m['base_avg'])}</td>"
                f"<td class='{cls}'>{pct(m['excess'])}</td></tr>"
            )
        backtest_html = (
            f"<div class='pricebar' style='background:#f4f9ff;border-color:#c9dff5'>"
            f"📊 <b>信号回测</b>（历史低估买入，共 {backtest['buy_count']} 个买点；样本内统计、未计成本，非收益承诺）："
            f"<table class='bt'><tr><th>持有期</th><th>低估买入平均</th><th>胜率</th><th>任意日买入</th><th>超额</th></tr>"
            f"{''.join(rows)}</table>"
            f"<div style='color:#5a6672;font-size:12px;line-height:1.7;margin-top:6px'>"
            f"<b>这张表怎么看：</b>比较“低估买入平均”和“任意日买入”两列——前者更高，说明<b>按低估信号买、历史上确实更划算</b>；"
            f"“超额”就是两者之差（<span style='color:#c0392b'>红=正、有效</span>，<span style='color:#1e8449'>绿=负、不如随便买</span>），"
            f"“胜率”是赚钱次数占比。比如“持有60日 超额+5.2%”＝历史上在低估区买入并拿60天，平均比任意日买多赚约5.2%。"
            f"<br><b>你要做什么：</b>什么都不用做，这块由程序自动算。它只是帮你验证“低估值不值得买”的历史依据，"
            f"是统计参考、不是未来收益承诺。想调整判断标准可在项目目录建 fund_config.json（见示例文件）。</div></div>"
        )

    chart_js = (
        "var DATA = __DATA__;"
        "var INFO = __INFO__;"
        "var COST = __COST__;"
        "var PREDICT = __PREDICT__;"
        "var LAST_REAL = __LASTREAL__;"
        "var LAST_REAL_VAL = __LASTREALVAL__;"
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
        "  var baseNav = (LAST_REAL[0] && LAST_REAL[1]!=null) ? [[LAST_REAL[0], LAST_REAL[1]], [PREDICT.date, PREDICT.cum]] : [[PREDICT.date, PREDICT.cum]];"
        "  navOption.series.push({ name:'今日预测', type:'line', showSymbol:true, symbol:'circle', symbolSize:9,"
        "     lineStyle:{color:'#e74c3c', type:'dashed', width:2}, itemStyle:{color:'#e74c3c'},"
        "     data: baseNav, label:{show:true, formatter:'预测 '+PREDICT.cum, position:'top', color:'#e74c3c', fontSize:10} });"
        "  navOption.legend.data.push('今日预测');"
        "  var baseVal = (LAST_REAL_VAL[0] && LAST_REAL_VAL[1]!=null) ? [[LAST_REAL_VAL[0], LAST_REAL_VAL[1]], [PREDICT.date, PREDICT.val]] : [[PREDICT.date, PREDICT.val]];"
        "  valOption.series.push({ name:'今日预测', type:'line', showSymbol:true, symbol:'circle', symbolSize:9,"
        "     lineStyle:{color:'#e74c3c', type:'dashed', width:2}, itemStyle:{color:'#e74c3c'},"
        "     data: baseVal, label:{show:true, formatter:'预测 '+PREDICT.val, position:'bottom', color:'#e74c3c', fontSize:10} });"
        "  valOption.legend.data.push('今日预测');"
        "}"
        "if (COST && COST.cost) {"
        "  navOption.series.push({ name:'我的成本(单位净值)', type:'line', showSymbol:false,"
        "     data: COST.line, lineStyle:{color:'#8e44ad', type:'dashed', width:2},"
        "     label:{show:true, formatter:'成本 '+COST.cost, position:'insideEndTop',"
        "             color:'#8e44ad', fontSize:10} });"
        "  navOption.legend.data.push('我的成本(单位净值)');"
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
    chart_js = chart_js.replace("__COST__", json.dumps(cost_js, ensure_ascii=False))
    chart_js = chart_js.replace("__LASTREAL__", json.dumps(last_real, ensure_ascii=False))
    chart_js = chart_js.replace("__LASTREALVAL__", json.dumps(last_real_val, ensure_ascii=False))
    chart_js = chart_js.replace("__MINDATE__", first_date)
    chart_js = chart_js.replace("__MAXDATE__", last_date)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name}（{fund_code}）走势图</title>
<style>
 * {{ box-sizing: border-box; }}
 body {{ font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif; margin: 0; background:#f5f6f8; color:#1f2329; }}
 header {{ padding:16px 20px 14px; background:#fff; border-bottom:1px solid #e6e6e6; }}
 header h1 {{ margin:0 0 12px; font-size:22px; }}
 .cards {{ display:flex; flex-wrap:wrap; gap:10px; }}
 .card {{ flex:1 1 150px; min-width:140px; background:#f8f9fb; border:1px solid #e6e8eb; border-radius:10px; padding:10px 12px; }}
 .card .k {{ font-size:12px; color:#8a9099; margin-bottom:5px; }}
 .card .v {{ font-size:18px; font-weight:600; color:#1f2329; word-break:break-all; }}
 .tag {{ display:inline-block; padding:3px 12px; border-radius:12px; font-size:16px; font-weight:600; }}
 .over {{ background:#fdecea; color:#c0392b; }}
 .under {{ background:#eafaf1; color:#1e8449; }}
 .fair {{ background:#eef4fb; color:#2471a3; }}
 .pricebar {{ margin-top:12px; padding:12px 16px; border-radius:10px; background:#fffdf4; border:1px solid #f0e2b0; font-size:14px; line-height:1.9; }}
 .pricebar .ttl {{ margin-bottom:2px; }}
 .pricebar .row {{ white-space:normal; }}
 .pricebar .lbl {{ display:inline-block; min-width:168px; color:#6b7280; font-size:12px; font-weight:700; }}
 .pricebar .buy {{ color:#1e8449; font-weight:700; font-size:16px; }}
 .pricebar .sell {{ color:#c0392b; font-weight:700; font-size:16px; }}
 .pricebar .tip {{ color:#8a6d1b; font-size:12.5px; line-height:1.65; margin-top:2px; }}
 table.bt {{ border-collapse:collapse; margin:10px 0 6px; font-size:14px; width:100%; max-width:560px; }}
 table.bt th, table.bt td {{ border:1px solid #d7e3f0; padding:6px 10px; text-align:center; }}
 table.bt th {{ background:#e8f1fb; color:#2471a3; }}
 table.bt td.up {{ color:#c0392b; font-weight:700; }}
 table.bt td.down {{ color:#1e8449; font-weight:700; }}
 .filter {{ padding:10px 20px; background:#fff; border-bottom:1px solid #eee; font-size:14px; overflow-x:auto; white-space:nowrap; }}
 .filter input {{ margin:0 4px; padding:4px 6px; font-size:14px; }}
 .filter button {{ margin-left:6px; padding:4px 12px; font-size:14px; cursor:pointer; }}
 .filter .hint {{ color:#98a0aa; margin-left:8px; font-size:13px; }}
 #navChart, #valChart {{ width:100%; height:420px; background:#fff; }}
 .chart-box {{ padding:10px 14px; }}
 .note {{ padding:2px 20px 24px; font-size:13px; color:#7a828c; line-height:1.8; }}
</style>
</head>
<body>
<header>
  <h1>{name}（{fund_code}）</h1>
  <div class="cards">
    <div class="card"><div class="k">类型</div><div class="v">{fund_type or '-'}</div></div>
    <div class="card"><div class="k">最新累计净值</div><div class="v">{latest_nav if latest_nav is not None else '-'}</div></div>
    <div class="card"><div class="k">估值结论</div><div class="v"><span class="tag {coarse}">{signal}</span></div></div>
    <div class="card"><div class="k">净值估值分位</div><div class="v">{valuation if valuation is not None else '-'}</div></div>
    <div class="card"><div class="k">近一年最大回撤</div><div class="v">{drawdown if drawdown is not None else '-'}</div></div>
    {index_card}
    {cost_card}
  </div>
  {price_ref_html}
  {backtest_html}
</header>
<div class="filter">
  <b>日期筛选：</b>从
  <input type="date" id="fromDate" min="{first_date}" max="{last_date}">
  到
  <input type="date" id="toDate" min="{first_date}" max="{last_date}">
  <button onclick="applyRange()">应用</button>
  <button onclick="resetRange()">全部</button>
  <span class="hint">默认全部历史；两图滑块联动，可拖动下方滑块 / 滚轮缩放</span>
</div>
<div class="chart-box"><div id="navChart"></div></div>
<div class="chart-box"><div id="valChart"></div></div>
<div class="note">
  上图＝净值（累计/单位/MA20/MA120）；下图＝估值分位，<b>数值越大越便宜、越小越贵</b>（长期上涨基金全历史分位偏低属正常，可看"近60日短期"）。图表库经 CDN 加载，断网请看同目录「历史趋势.png」。{cost_note}
</div>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<script>{chart_js}</script>
</body>
</html>
"""
    with open(os.path.join(folder, "走势图.html"), "w", encoding="utf-8") as f:
        f.write(html)


def analyze_signals(df: pd.DataFrame, fund_code: str, name: str, fund_type: str = "", predict_today: Optional[float] = None, index_val: Optional[dict] = None, cost: Optional[dict] = None) -> pd.DataFrame:
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
    price_ref = _price_reference(df)
    backtest = backtest_valuation(df)
    _save_interactive_html(df, fund_code, name, fund_type, signal, valuation, drawdown, predict_point, d,
                           index_val=index_val, price_ref=price_ref, backtest=backtest, cost=cost)
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

    # 今日预测仅在“今日真实净值尚未发布”时叠加展示：
    #   - 最新净值日期 < 今天（盘中 / 收盘前，今日 NAV 还没出）→ 展示预测，延伸走势；
    #   - 最新净值日期 == 今天（今日 NAV 已出）→ 预测已无意义，自动不展示、不写图、并标记过期。
    today = datetime.date.today()
    try:
        latest_nav_date = pd.to_datetime(nav["净值日期"]).max().date()
    except Exception:
        latest_nav_date = None
    show_predict = (predict_today is not None) and (latest_nav_date is not None) and (latest_nav_date < today)
    prediction_obsolete = bool(predict_today is not None and not show_predict)

    analyzed = analyze_signals(
        nav, code, name, fund_type=fund_type,
        predict_today=(predict_today if show_predict else None), index_val=index_val,
        cost=get_cost(code),
    )

    latest = analyzed.iloc[0]
    signal = latest["估值结论"]          # 统一估值结论（高估/低估/合理），所有类型一致
    detail = latest["信号"]              # 细节（动能/回撤/极端涨跌等），仅作参考
    valuation = None if pd.isna(latest["估值分位"]) else round(float(latest["估值分位"]), 4)

    # 仅当预测仍有效（今日 NAV 未出）时，用临时叠加行算“含预测的当日结论/分位”用于展示
    if show_predict:
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
        "prediction_applied": show_predict,
        "prediction_obsolete": prediction_obsolete,
    }


# ----------------------------------------------------------------------------
# 盘中估值（自动抓“估算增长率%”替代手填预测）—— 双源降级：新浪财经（主）→ 东方财富（备）。
# 东财批量接口盘后常回 {"Data":null}，akshare 内部直接下标访问会抛 TypeError，故改以新浪为主源。
# 注意：仅在交易时段(约 9:30-15:00)发起请求。A 股/境内基金估值参考价值较高；
# QDII(纳指/标普/港股)因对应市场时差不同，即使拿到估值也仅供参考。估值≠真实净值。
# ----------------------------------------------------------------------------
LAST_INTRADAY_REASON = ""   # 最近一次抓取的具体原因（空=成功），供 GUI 精确提示
LAST_INTRADAY_SOURCE = ""   # 实际用上的数据源名，供 GUI 标注


def _fetch_from_sina(codes: list, today, timeout: int = 15) -> tuple:
    """备用源：新浪财经基金批量估值 https://hq.sinajs.cn/list=f_代码1,f_代码2...

    东财的批量估值接口在盘后/故障时返回 {"Data":null}，akshare 会直接抛异常。
    新浪这条接口一次可查多只，且响应里自带估值日期，能挡住上一交易日的残留。
    响应为 GBK 编码的 JS 变量赋值，形如：
      var hq_str_f_012414="招商中证白酒指数C,0.5818,0.6668,0.5771,2026-11-16,236.666";
    字段依次为：名称 / 估算单位净值 / 估算累计净值 / 最新公布单位净值 / 估值日期 / 规模。
    增长率 = (估算单位净值 ÷ 最新公布单位净值 − 1) × 100。

    返回 (结果 dict, 说明字符串)：说明为空表示成功，否则是失败原因（供继续尝试东财）。
    """
    result = {}
    try:
        url = "https://hq.sinajs.cn/list=" + ",".join(f"f_{c}" for c in codes)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
            "Referer": "https://finance.sina.com.cn/",
        }
        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code != 200:
            return result, f"新浪接口 HTTP {r.status_code}"
        r.encoding = "gbk"
        for line in r.text.splitlines():
            m = re.search(r'hq_str_f_(\d{6})="([^"]*)"', line)
            if not m:
                continue
            p = m.group(2).split(",")
            if len(p) < 5:
                continue
            # 关键：估值日期必须是今天。有些基金当日无估算，接口会原样返回上一交易日数据。
            if p[4].strip() != today.isoformat():
                continue
            try:
                est, base = float(p[1]), float(p[3])
            except (TypeError, ValueError):
                continue
            if base <= 0:
                continue
            rate = (est / base - 1) * 100
            if not (-100 < rate < 100):   # 极端脏值保护
                continue
            result[m.group(1)] = round(rate, 4)
        if not result:
            return result, "新浪接口未返回今日估算（数据源尚未更新或池内基金无估值）"
        return result, ""
    except Exception as e:  # noqa
        return result, f"新浪接口异常：{type(e).__name__}: {str(e)[:100]}"


def fetch_intraday_estimation(codes: list, timeout: int = 30) -> dict:
    """批量抓取盘中估值增长率(%)。双数据源，按序降级：

      1) 新浪财经（主）：批量接口，盘后仍保留当日估算，自带估值日期可校验；
      2) 东方财富（备）：akshare fund_value_estimation_em / fund_em_value_estimation。

    返回 {6位基金代码: 估算增长率(float, 如 3.71 表示涨3.71%)}；
    抓不到 / 非交易时段 / 当日无估算的基金不会出现在结果里（QDII 估值仅供参考）。
    实际用上的源记在 LAST_INTRADAY_SOURCE，失败原因记在 LAST_INTRADAY_REASON。
    """
    global LAST_INTRADAY_REASON, LAST_INTRADAY_SOURCE
    LAST_INTRADAY_REASON = ""
    LAST_INTRADAY_SOURCE = ""
    codes = [str(c).zfill(6) for c in codes]
    result = {}
    last_err = None
    now = datetime.datetime.now()
    today = now.date()
    # 周末无交易：直接返回空，避免把上周五的残留估算当成“今日预测”填进去。
    if today.weekday() >= 5:
        LAST_INTRADAY_REASON = f"今天是周末（{today:%Y-%m-%d}），A股不开盘"
        print(f"[盘中估值] {LAST_INTRADAY_REASON}，已跳过。")
        return result
    # 真正的交易时段判断：此前缺失，导致盘后接口异常被笼统提示成"不在时间范围"。
    # 盘前/盘后直接跳过，既避免无谓请求，也能给出准确原因。
    if not (datetime.time(9, 30) <= now.time() <= datetime.time(15, 0)):
        LAST_INTRADAY_REASON = (
            f"当前 {now:%H:%M} 不在 A股交易时段（9:30-15:00，现在为盘前或盘后）"
        )
        print(f"[盘中估值] {LAST_INTRADAY_REASON}，已跳过。")
        return result

    # ---- 源1：新浪财经 ----
    sina_result, sina_note = _fetch_from_sina(codes, today, timeout)
    if sina_result:
        LAST_INTRADAY_SOURCE = "新浪财经"
        print(f"[盘中估值] 新浪财经抓到 {len(sina_result)} 只当日估值。")
        return sina_result

    # ---- 源2：东方财富（akshare）----
    available = [n for n in ("fund_value_estimation_em", "fund_em_value_estimation")
                 if getattr(ak, n, None) is not None]
    if not available:
        LAST_INTRADAY_REASON = (f"新浪：{sina_note}；" if sina_note else "") + "当前 akshare 版本没有可用的估值接口"
        print(f"[盘中估值] {LAST_INTRADAY_REASON}。")
        return result
    for fn_name in available:
        fn = getattr(ak, fn_name, None)
        if fn is None:
            continue
        try:
            df = fn()
            if df is None or getattr(df, "empty", True):
                last_err = f"{fn_name} 返回空数据（数据源暂不可用或接口限流）"
                continue
            # 定位代码列
            code_col = None
            for cand in ("基金代码", "代码"):
                if cand in df.columns:
                    code_col = cand
                    break
            if code_col is None:
                last_err = f"{fn_name} 返回结构异常（找不到基金代码列）"
                continue
            # 定位增长率列（按包含匹配）
            rate_col = None
            for c in df.columns:
                if "估算增长率" in str(c):
                    rate_col = c
                    break
            if rate_col is None:
                for c in df.columns:
                    if "估算涨跌" in str(c) or "涨跌幅" in str(c):
                        rate_col = c
                        break
            if rate_col is None:
                last_err = f"{fn_name} 返回结构异常（找不到估算增长率列）"
                continue
            # 关键：校验估算数据的“日期”必须是今天。东财列名形如
            #   “2026-05-12-估算数据-估算增长率”，非交易时段/周末接口常仍返回上一交易日
            #   的残留数据（列名日期是上一交易日）。若日期≠今天，整批丢弃，不再填入预测。
            m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(rate_col))
            if m:
                data_day = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                if data_day != today:
                    last_err = (f"数据源返回的估算数据日期为 {data_day}（今日 {today}），"
                                f"尚未更新到今天，已丢弃以免误填旧值")
                    continue
            work = df[[code_col, rate_col]].copy()
            work[code_col] = work[code_col].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
            work = work[work[code_col].isin(codes)]
            for _, row in work.iterrows():
                v = row[rate_col]
                try:
                    fv = float(str(v).replace("%", "").strip())
                except (TypeError, ValueError):
                    continue
                if fv == fv:  # 过滤 NaN
                    result[row[code_col]] = round(fv, 4)
            # 成功，但自选池可能一只都没匹配上（QDII / 债券 / 场外基金常见）
            if not result:
                LAST_INTRADAY_REASON = (
                    (f"新浪：{sina_note}；" if sina_note else "")
                    + f"东财返回正常，但自选池 {len(codes)} 只均无当日估算"
                    "（QDII / 债券 / 场外基金本就没有盘中估算，属正常）"
                )
            else:
                LAST_INTRADAY_SOURCE = "东方财富"
            return result  # 成功（哪怕部分基金无估值）
        except Exception as e:  # noqa
            last_err = f"{fn_name} 接口异常：{type(e).__name__}: {str(e)[:120]}"
            continue
    # 所有源都失败：返回空，由调用方显示具体原因（不抛异常，避免打断批量流程）
    LAST_INTRADAY_REASON = (f"新浪：{sina_note}；" if sina_note else "") + (last_err or "数据源暂不可用")
    print(f"[盘中估值] 抓取失败：{LAST_INTRADAY_REASON}")
    return result


if __name__ == "__main__":
    import sys
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 1000)
    test_code = sys.argv[1] if len(sys.argv) > 1 else "012414"
    res = run_fund(test_code)
    print(json.dumps(res, ensure_ascii=False, indent=2))
