# -*- coding: utf-8 -*-
"""
批量抓取自选池的历史持仓 + 股票行业缓存 + 指数/QDII 底层持仓，并离线重跑每只基金报告，
让"持仓变化"与"跟踪指数成分股"区块生效。

用法（项目虚拟环境）：
    python batch_holdings.py

只联网抓持仓明细和行业分类；净值用本地缓存（offline=True），不会重复抓净值。
抓完自动对每只基金重跑一次报告。耗时主要在逐季度请求，约几分钟。
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analysis

BASE = os.path.dirname(os.path.abspath(__file__))


def load_funds():
    with open(os.path.join(BASE, "funds.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def offline_patch():
    """离线重跑：基本信息读各目录 meta.json，指数估值/持仓抓取置空，避免联网。"""
    meta_cache = {}

    def get_meta(code, name):
        d = analysis.resolve_fund_dir(code, name)
        p = os.path.join(d, "meta.json")
        if p not in meta_cache:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    meta_cache[p] = json.load(f)
            except Exception:
                meta_cache[p] = {}
        return meta_cache[p]

    def fake_basic(code, name=None):
        m = get_meta(code, name)
        return {
            "基金名称": m.get("name") or (name or code),
            "基金类型": m.get("type", ""),
        }

    analysis.get_fund_basic = fake_basic
    analysis.fetch_index_valuation = lambda *a, **k: None
    analysis.get_holdings = lambda *a, **k: None
    analysis.get_holdings_history = lambda *a, **k: None
    analysis.get_index_constituents = lambda *a, **k: None


def main():
    funds = load_funds()
    total = len(funds)
    print(f"自选池 {total} 只，开始抓历史持仓 + 行业分类 ……\n")
    ok, fail = [], []
    for i, it in enumerate(funds, 1):
        code, name = str(it["code"]).zfill(6), it.get("name", "")
        try:
            df = analysis.get_holdings_history(code, name)
            n = df["季度"].nunique() if not df.empty else 0
            print(f"[{i:>2}/{total}] {code} {name}: {len(df)} 行 / {n} 个季度")
            if n:
                ok.append(code)
            else:
                fail.append((code, name, "无持仓数据（指数/债券/QDII 常见）"))
        except Exception as e:  # noqa
            print(f"[{i:>2}/{total}] {code} {name}: 失败 {e}")
            fail.append((code, name, str(e)))

    print(f"\n持仓历史：{len(ok)} 只有数据，{len(fail)} 只无/失败")
    print(f"行业缓存条目：{len(analysis.load_industry_map())}")

    # 指数基金 / ETF联接 / QDII：抓跟踪指数或底层 ETF 的成分股
    idx_map = analysis.load_index_map()
    print(f"\n开始抓指数/QDII 底层持仓（映射 {len(idx_map)} 只）……")
    idx_ok, idx_fail = [], []
    for i, it in enumerate(funds, 1):
        code, name = str(it["code"]).zfill(6), it.get("name", "")
        if code not in idx_map:
            continue
        try:
            r = analysis.get_index_constituents(code, name)
            if r:
                idx_ok.append(code)
                print(f"[{i:>2}/{total}] {code} {name[:22]}: {r['rows']} 只 · {r['index_name']}")
            else:
                idx_fail.append((code, name, "无成分股数据"))
                print(f"[{i:>2}/{total}] {code} {name[:22]}: 无数据")
        except Exception as e:  # noqa
            idx_fail.append((code, name, str(e)))
            print(f"[{i:>2}/{total}] {code} {name[:22]}: 失败 {e}")
    print(f"指数/QDII 成分股：{len(idx_ok)} 只成功，{len(idx_fail)} 只失败")

    print("\n开始离线重跑报告（让持仓变化/成分股区块生效）……")
    offline_patch()
    ok2, fail2 = [], []
    for i, it in enumerate(funds, 1):
        code, name = str(it["code"]).zfill(6), it.get("name", "")
        try:
            analysis.run_fund(code, name=name, offline=True, with_holdings=False)
            ok2.append(code)
            print(f"[{i:>2}/{total}] {code} {name}: OK")
        except Exception as e:  # noqa
            fail2.append((code, name, str(e)))
            print(f"[{i:>2}/{total}] {code} {name}: 重跑失败 {e}")

    print(f"\n完成：报告重跑成功 {len(ok2)}/{total}，失败 {len(fail2)}")
    if fail2:
        print("失败清单：")
        for c, n, e in fail2:
            print(f"  {c} {n}: {e}")


if __name__ == "__main__":
    main()
