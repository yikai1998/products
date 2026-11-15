# -*- coding: utf-8 -*-
"""
低估雷达（MVP-2）
================
扫描一个“代表性基金候选池”（radar_pool.json，宽基/行业/QDII/主题，通常包含你没关注的基金），
联网抓历史净值、按“估值分位”从便宜到贵排序，生成一张对比报告——帮你会发现池子外被低估的机会。

为什么是“候选池”而不是“你自己的自选池”：
  - 扫自己已选的基金等于把已知的东西重排一遍，发现不了新机会；
  - 全市场几千只盲扫又会被限流、且主动基金分位意义有限；
  - 所以内置一份几十只的代表性被动指数基金清单，数量可控、口径与主程序一致
    （共用 fetch_nav → _build_indicators → 估值分位），既能看到没关注的，又不爆量。

缓存：抓过的基金历史净值由 analysis.fetch_nav 落到「基金报告/{名称}_基金代码{代码}/历史净值.csv」，
      下次扫描可用 --cache 直接读缓存、不联网（秒出）。默认联网抓最新。

「★已自选 / 🆕新发现」怎么来的：
  启动时读 funds.json（就是 GUI 自选池那份唯一权威清单）取代码集合；
  候选池里代码在 funds.json → ★已自选，不在 → 🆕新发现。
  报告是生成那一刻的快照，GUI 里改了自选后需重新扫描才会更新标注。

报告筛选：生成的是纯前端 HTML，可按 关键字(代码/名称) / 分类 / 是否自选 /
  估值结论(含低估区、高估区、具体7档) 实时筛选，点表头可排序，右侧显示「显示 N / 总数」。

候选池维护：直接编辑 radar_pool.json 增删基金（code/name/category 三个字段），
            雷达抓取时会用真实名称/类型覆盖 name/type。

用法：
  python radar.py                # 联网抓最新估值 → 生成 基金报告/雷达报告.html
  python radar.py --cache        # 只读本地缓存生成（快，数据可能旧）
  或在 gui.py 里点“📡 低估雷达”按钮（后台线程，默认联网抓最新）。
"""

from __future__ import annotations

import os
import json
import time
import html
import datetime
import argparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIST_PATH = os.path.join(BASE_DIR, "funds.json")         # 你的自选池（用于标注“已自选”）
POOL_PATH = os.path.join(BASE_DIR, "radar_pool.json")    # 候选池（扫描对象）
REPORT_NAME = os.path.join("基金报告", "雷达报告.html")

# 估值结论 → 配色（与主程序 SIGNAL_COLORS 同口径）
SIGNAL_COLOR = {
    "严重高估": "#c0392b", "高估": "#e74c3c", "估值偏高": "#e67e22",
    "合理": "#2471a3", "估值偏低": "#2980b9",
    "低估": "#1e8449", "严重低估": "#00695c", "数据不足": "#7f8c8d",
    "抓取失败": "#95a5a6",
}


def _brief_err(e, limit: int = 90) -> str:
    """把异常压成一行、去掉 HTML 噪音，避免把 <doctype html> 整段刷进日志。

    akshare 偶发返回网页而非 JSON，解析报 "... SyntaxError: Unexpected token '<'"，
    原始 str(e) 带换行 + 整段 HTML，日志里很难看。这里统一折叠成一行友好提示。
    """
    s = " ".join(str(e).split())  # 折叠所有空白/换行为单行
    low = s.lower()
    if "unexpected token '<'" in s or "<!doctype html" in low or "<html" in low:
        return "数据源返回网页而非数据（接口临时异常/被限流），已跳过该只"
    if "timeout" in low or "timed out" in low:
        return "请求超时，已跳过该只"
    if "connection" in low or "connectionerror" in low:
        return "网络连接失败，已跳过该只"
    if len(s) > limit:
        s = s[:limit] + "…"
    return s


def load_own_codes():
    """你的自选池代码集合（用于给候选池标注“★已自选”）。"""
    if not os.path.exists(LIST_PATH):
        return set()
    try:
        with open(LIST_PATH, encoding="utf-8") as f:
            items = json.load(f)
        return {str(it.get("code", "")).zfill(6) for it in items if isinstance(it, dict) and it.get("code")}
    except Exception:
        return set()


def load_pool():
    """读取候选池 radar_pool.json。每行需有 code，可带 name / category。"""
    if not os.path.exists(POOL_PATH):
        return []
    try:
        with open(POOL_PATH, encoding="utf-8") as f:
            items = json.load(f)
        out, seen = [], set()
        for it in items:
            if not isinstance(it, dict) or not it.get("code"):
                continue
            code = str(it["code"]).strip().zfill(6)
            if code in seen:
                continue
            seen.add(code)
            out.append({"code": code, "name": it.get("name", code),
                        "category": it.get("category", "其它")})
        return out
    except Exception:
        return []


def refresh_valuations(items, progress=None, offline=False):
    """抓每只候选基金的估值分位/信号/最新净值（复用 analysis 主引擎，口径一致）。

    offline=False：联网抓最新（fetch_nav 会写本地缓存）；True：只读本地缓存（快，数据可能旧）。
    为防限流，每只之间轻微 sleep。抓失败的保留原值并标注，不中断整体扫描。
    """
    import analysis
    import pandas as pd
    out = []
    total = len(items)
    for idx, it in enumerate(items):
        code = it["code"]
        try:
            # akshare 偶发返回 HTML 错误页（json 解析报 "Unexpected token '<'"），联网时重试 3 次。
            # 页面类故障多是瞬时限流，稍等再试通常能恢复，避免一只基金拖累整份报告。
            df = None
            last_err = None
            attempts = 1 if offline else 3
            for attempt in range(attempts):
                try:
                    df = analysis.fetch_nav(code, offline=offline)
                    break
                except Exception as e:
                    last_err = e
                    if attempt < attempts - 1:
                        time.sleep(0.6 * (attempt + 1))  # 0.6s / 1.2s 递增退避
                    else:
                        raise
            if df is None or df.empty:
                raise RuntimeError(f"无净值数据（{_brief_err(last_err) if last_err else '空数据'}）")
            # 抓取时顺便取真实名称/类型，纠正候选池里手填的旧名字
            try:
                basic = analysis.get_fund_basic(code)
                if basic.get("基金名称"):
                    it["name"] = basic["基金名称"]
                if basic.get("基金类型"):
                    it["type"] = basic["基金类型"]
            except Exception:
                pass
            df = analysis._assign_signals(df, it.get("type", ""))
            # 关键：_build_indicators 返回“日期升序”df，最新一天在最后一行。
            # 必须按日期排序后取 iloc[-1]；旧代码取 iloc[0]（最老一天），估值分位/高低估线必为 NaN → 全判“数据不足”。
            latest = (df.sort_values("净值日期").iloc[-1]
                      if "净值日期" in df.columns and len(df) else None)
            if latest is not None:
                val = latest.get("估值分位")
                it["valuation"] = None if pd.isna(val) else round(float(val), 4)
                it["signal"] = latest.get("估值结论", it.get("signal", "-"))
                it["latest_nav"] = None if pd.isna(latest.get("单位净值")) else round(float(latest["单位净值"]), 4)
                it["updated"] = str(pd.to_datetime(latest["净值日期"]).date())
        except Exception as e:  # noqa
            it.setdefault("valuation", None)
            it["signal"] = "抓取失败"
            it["err"] = _brief_err(e)
            if progress:
                progress(f"✘ {code} 抓取失败：{it['err']}")
        if progress:
            progress(f"[{idx+1}/{total}] {code} {it.get('name','')} → 估值={it.get('valuation')} {it.get('signal','')}")
        out.append(it)
        if not offline and idx < total - 1:
            time.sleep(0.3)  # 轻微限速，避免被数据源限流
    return out


def _f(x, nd=4):
    if x is None or x in ("", "-"):
        return "-"
    try:
        return f"{float(x):.{nd}f}"
    except (TypeError, ValueError):
        return str(x)


def scan(refresh: bool = True, progress=None) -> str:
    """扫描候选池并生成报告，返回报告文件绝对路径。
    refresh=True：联网抓最新估值（默认，能发现新机会但较慢）；
    refresh=False：只读本地缓存（快，但数据可能旧）。"""
    items = load_pool()
    own = load_own_codes()
    overlap_codes = sorted({it["code"] for it in items} & own)
    for it in items:
        it["is_own"] = it["code"] in own
        it.setdefault("type", "-")
        it.setdefault("valuation", None)
        it.setdefault("latest_nav", None)
        it.setdefault("updated", "-")
        it.setdefault("signal", "-")

    if progress:
        mode = "联网抓最新" if refresh else "读本地缓存"
        progress(f"📡 低估雷达开始扫描 {len(items)} 只候选基金（{mode}）……")
    items = refresh_valuations(items, progress=progress, offline=(not refresh))

    # 排序：估值分位越大越便宜 → 降序（最便宜在前）；无估值的沉底
    with_val = [it for it in items if isinstance(it.get("valuation"), (int, float))]
    no_val = [it for it in items if not isinstance(it.get("valuation"), (int, float))]
    with_val.sort(key=lambda it: float(it["valuation"]), reverse=True)
    ranked = with_val + no_val

    cheap = [it for it in with_val if float(it["valuation"]) >= 0.80]
    expensive = [it for it in with_val if float(it["valuation"]) <= 0.20]
    new_cheap = [it for it in cheap if not it.get("is_own")]   # 你没关注的低估基金 = 雷达的核心价值
    failed = [it for it in items if it.get("signal") == "抓取失败"]

    # 筛选选项（来自本次扫描实际出现的分类 / 估值结论）
    cat_list = sorted({it.get("category", "-") or "-" for it in items})
    cat_options = "".join(f'<option value="{html.escape(c)}">{html.escape(c)}</option>' for c in cat_list)
    sig_order = ["严重低估", "低估", "估值偏低", "合理", "估值偏高", "高估", "严重高估",
                 "数据不足", "抓取失败"]
    sig_present = {it.get("signal", "-") or "-" for it in items}
    sig_list = [s for s in sig_order if s in sig_present] + sorted(sig_present - set(sig_order))
    sig_options = "".join(f'<option value="{html.escape(s)}">{html.escape(s)}</option>' for s in sig_list)

    rows = []
    for rank, it in enumerate(ranked, 1):
        val = it.get("valuation")
        sig = it.get("signal", "-")
        color = SIGNAL_COLOR.get(sig, "#333")
        if isinstance(val, (int, float)):
            pct = float(val) * 100
            bar = (f"<div class='bar'><span style='width:{pct:.1f}%;background:{color}'></span></div>")
            val_txt = f"{pct:.1f}%"
            val_num = f"{float(val):.6f}"
        else:
            bar, val_txt, val_num = "", "-", ""
        own = "1" if it.get("is_own") else "0"
        own_txt = "已自选" if own == "1" else "新发现"
        own_tag = ("<span style='color:#c0392b;font-weight:700'>★已自选</span>" if own == "1"
                   else "<span style='color:#1a73e8;font-weight:700'>新发现</span>")
        # data-* 属性供前端筛选：可搜索代码/名称，按分类/自选/估值结论/区间过滤，按分位排序可恢复默认
        rows.append(
            f'<tr data-code="{it.get("code","")}" data-name="{html.escape(str(it.get("name","")))}" '
            f'data-cat="{html.escape(str(it.get("category","-") or "-"))}" data-own="{own}" '
            f'data-val="{val_num}" data-sig="{html.escape(str(sig))}" data-rank="{rank}">'
            f"<td class='rk'>{rank}</td>"
            f"<td>{it.get('code','')}</td>"
            f"<td class='nm'>{html.escape(str(it.get('name','')))}</td>"
            f"<td>{html.escape(str(it.get('category','-') or '-'))}</td>"
            f"<td>{own_tag}</td>"
            f"<td class='num'>{_f(it.get('latest_nav'))}</td>"
            f"<td class='num'>{val_txt}{bar}</td>"
            f"<td style='color:{color};font-weight:600'>{html.escape(str(sig))}</td>"
            f"<td>{it.get('updated','-')}</td>"
            f"</tr>"
        )

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    data_src = "联网抓最新" if refresh else "本地缓存（可能旧）"
    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>低估雷达</title>
<style>
 * {{ box-sizing:border-box; }}
 body {{ font-family:"Microsoft YaHei","PingFang SC",Arial,sans-serif; margin:0; background:#f5f6f8; color:#1f2329; }}
 header {{ padding:18px 22px; background:#fff; border-bottom:1px solid #e6e6e6; }}
 h1 {{ margin:0 0 6px; font-size:24px; }}
 .sub {{ color:#7a828c; font-size:13px; }}
 .stats {{ display:flex; flex-wrap:wrap; gap:12px; margin-top:14px; }}
 .stat {{ flex:1 1 160px; min-width:150px; padding:12px 16px; border-radius:10px; background:#f8f9fb; border:1px solid #e6e8eb; }}
 .stat .k {{ font-size:12px; color:#8a9099; }}
 .stat .v {{ font-size:22px; font-weight:700; margin-top:4px; }}
 .wrap {{ padding:16px 22px 40px; overflow-x:auto; }}
 table {{ border-collapse:collapse; width:100%; background:#fff; font-size:14px; border-radius:10px; overflow:hidden; }}
 th,td {{ padding:9px 10px; text-align:center; border-bottom:1px solid #eef0f2; white-space:nowrap; }}
 th {{ background:#eef4fb; color:#2471a3; position:sticky; top:0; }}
 tr:hover td {{ background:#fafcff; }}
 td.nm {{ text-align:left; font-weight:600; }}
 td.rk {{ color:#8a9099; }}
 td.num {{ font-variant-numeric:tabular-nums; }}
 .bar {{ height:5px; background:#eef0f2; border-radius:3px; margin-top:4px; min-width:70px; }}
 .bar span {{ display:block; height:100%; border-radius:3px; }}
 .note {{ color:#7a828c; font-size:13px; line-height:1.8; margin-top:14px; }}
 .filters {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; padding:12px 0 4px; }}
 .filters input, .filters select {{ font-size:13px; padding:6px 9px; border:1px solid #d7dde3; border-radius:7px; background:#fff; color:#1f2329; }}
 .filters input {{ min-width:180px; }}
 .filters button {{ font-size:13px; padding:6px 14px; border:1px solid #2471a3; border-radius:7px; background:#2471a3; color:#fff; cursor:pointer; }}
 .filters button:hover {{ background:#1a5276; }}
 .fcount {{ margin-left:auto; color:#7a828c; font-size:13px; }}
 th.sortable {{ cursor:pointer; user-select:none; }}
 th.sortable:hover {{ background:#dfeaf6; }}
</style></head>
<body>
<header>
  <h1>📡 低估雷达</h1>
  <div class="sub">扫描<b>代表性基金候选池</b>（含你没关注的），按估值分位从便宜到贵排序（越大越便宜）｜ 生成时间：{now} ｜ 数据：{data_src}</div>
  <div class="stats">
    <div class="stat"><div class="k">候选池基金</div><div class="v">{len(items)}</div></div>
    <div class="stat"><div class="k">🆕 新发现的低估（你没买）</div><div class="v" style="color:#1a73e8">{len(new_cheap)}</div></div>
    <div class="stat"><div class="k">低估区（分位≥80%）</div><div class="v" style="color:#1e8449">{len(cheap)}</div></div>
    <div class="stat"><div class="k">高估区（分位≤20%）</div><div class="v" style="color:#c0392b">{len(expensive)}</div></div>
    <div class="stat"><div class="k">无估值数据</div><div class="v" style="color:#7f8c8d">{len(no_val)}</div></div>
    {f'<div class="stat"><div class="k">抓取失败（短暂故障）</div><div class="v" style="color:#95a5a6">{len(failed)}</div></div>' if failed else ''}
  </div>
</header>
<div class="wrap">
  <div class="filters">
    <input id="fKw" type="text" placeholder="🔍 搜代码 / 名称" oninput="applyFilter()">
    <select id="fCat" onchange="applyFilter()"><option value="">全部分类</option>{cat_options}</select>
    <select id="fOwn" onchange="applyFilter()">
      <option value="">自选：全部</option>
      <option value="1">★ 只看已自选</option>
      <option value="0">🆕 只看新发现</option>
    </select>
    <select id="fSig" onchange="applyFilter()">
      <option value="">估值结论：全部</option>
      <option value="__cheap">低估区（分位≥80%）</option>
      <option value="__expensive">高估区（分位≤20%）</option>
      <option value="__nodata">无估值 / 抓取失败</option>
      <optgroup label="按具体结论">{sig_options}</optgroup>
    </select>
    <button onclick="resetFilter()">重置</button>
    <span class="fcount" id="fCount"></span>
  </div>
  <table id="fundTable">
    <thead><tr>
      <th class="sortable" onclick="sortBy('rank',this)">#</th>
      <th class="sortable" onclick="sortBy('code',this)">代码</th>
      <th class="sortable" onclick="sortBy('name',this)">名称</th>
      <th class="sortable" onclick="sortBy('cat',this)">分类</th>
      <th class="sortable" onclick="sortBy('own',this)">是否自选</th>
      <th>最新净值</th>
      <th class="sortable" onclick="sortBy('val',this)">估值分位</th>
      <th class="sortable" onclick="sortBy('sig',this)">估值结论</th>
      <th>更新</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  <div class="note">
    <b>标注怎么来的：</b>启动时读取 <code>funds.json</code>（就是 tkinter 自选池那份唯一权威清单）取代码集合，
    候选池里代码在其中 → <b>★已自选</b>，不在 → <b>🆕 新发现</b>。本次交集为 <b>{len(overlap_codes)}</b> 只。
    {f'本次候选池与你自选池<b>完全不重叠</b>，所以全是「新发现」，★已自选不会出现——这是正常的：候选池就是刻意选在自选池之外的。' if not overlap_codes else f'重叠代码：{", ".join(overlap_codes)}。'}
    <br>报告是<b>生成那一刻的快照</b>：在 GUI 里增删自选后，需重新点「📡 低估雷达」才会刷新标注。
    <br>估值分位＝历史上净值高于当前的比例，<b>越大越便宜、越小越贵</b>；可用上方筛选按关键字 / 分类 / 是否自选 / 估值结论过滤，点表头排序。
    <br>候选池在 <code>radar_pool.json</code>，可直接编辑增删基金代码（下次扫描生效）。长期上涨基金全历史分位偏低属正常，
    可结合报告里的“近60日短期分位”判断。统计参考、非投资建议。命令行 <code>python radar.py --cache</code> 可秒出（读旧缓存，不联网）。
  </div>
</div>
<script>
(function () {{
  var tbody = document.querySelector('#fundTable tbody');
  var allRows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
  function applyFilter() {{
    var kw = document.getElementById('fKw').value.trim().toLowerCase();
    var cat = document.getElementById('fCat').value;
    var own = document.getElementById('fOwn').value;
    var sig = document.getElementById('fSig').value;
    var shown = 0;
    allRows.forEach(function (tr) {{
      var d = tr.dataset;
      var ok = true;
      if (kw && (d.code.indexOf(kw) < 0) && (d.name.toLowerCase().indexOf(kw) < 0)) ok = false;
      if (cat && d.cat !== cat) ok = false;
      if (own && d.own !== own) ok = false;
      if (sig === '__cheap' && (d.val === '' || parseFloat(d.val) < 0.80)) ok = false;
      if (sig === '__expensive' && (d.val === '' || parseFloat(d.val) > 0.20)) ok = false;
      if (sig === '__nodata' && d.val !== '') ok = false;
      if (sig && sig.indexOf('__') !== 0 && d.sig !== sig) ok = false;
      tr.style.display = ok ? '' : 'none';
      if (ok) shown++;
    }});
    document.getElementById('fCount').textContent = '显示 ' + shown + ' / ' + allRows.length + ' 只';
  }}
  window.applyFilter = applyFilter;
  window.resetFilter = function () {{
    document.getElementById('fKw').value = '';
    document.getElementById('fCat').value = '';
    document.getElementById('fOwn').value = '';
    document.getElementById('fSig').value = '';
    applyFilter();
  }};
  window.sortBy = function (key, th) {{
    var asc = th.dataset.asc !== '1';
    th.dataset.asc = asc ? '1' : '0';
    var dir = asc ? 1 : -1;
    allRows.sort(function (a, b) {{
      var av = a.dataset[key], bv = b.dataset[key];
      if (key === 'val') {{ av = av === '' ? -1 : parseFloat(av); bv = bv === '' ? -1 : parseFloat(bv); }}
      if (key === 'rank') {{ av = parseFloat(av); bv = parseFloat(bv); }}
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return 0;
    }});
    allRows.forEach(function (r) {{ tbody.appendChild(r); }});
  }};
  applyFilter();
}})();
</script>
</body></html>"""
    path = os.path.join(BASE_DIR, REPORT_NAME)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="低估雷达：扫描候选池，按估值分位排序生成对比报告")
    ap.add_argument("--cache", action="store_true", help="只读本地缓存生成（快，数据可能旧）；默认联网抓最新")
    args = ap.parse_args()
    p = scan(refresh=(not args.cache), progress=lambda m: print(m))
    print(f"雷达报告已生成：{p}")
