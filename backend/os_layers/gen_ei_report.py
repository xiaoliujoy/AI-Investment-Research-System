#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成多账户 Belief Execution Engine（信念兑现引擎）视图 HTML 报告。

读取 backend/os_layers/../mt5_raw/execution_intelligence.json
写入 mt5_raw/execution_intelligence.html

品牌调性（用户锁定）：深绿黑渐变底 #0d1410→#16241c + 品牌绿 #2E7D52
"""
import os, json

HERE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(HERE, "..", "..", "mt5_raw", "execution_intelligence.json")
OUT_PATH = os.path.join(HERE, "..", "..", "mt5_raw", "execution_intelligence.html")

BG0, BG1, GREEN, GREEN_D = "#0d1410", "#16241c", "#2E7D52", "#1f5a3a"


def pct(x):
    return f"{x*100:.1f}%"


def money(x):
    return f"{x:+,.0f}"


def badge(rel):
    if rel == "reliable":
        return '<span class="badge ok">可靠</span>'
    return '<span class="badge warn">近似/保守</span>'


def abcd_block(title, a, econ, rel, mfe_src, extra=""):
    total = a["total"] or 1
    rows = []
    rows.append(("A 方向错·正常止损", a["A"], a["A"]/total))
    rows.append(("B 方向对·正常盈利", a["B"], a["B"]/total))
    rows.append(("C 方向对·提前小赚", a["C"], a["C"]/total))
    rows.append(("D 方向对·盈利后倒亏", a["D"], a["D"]/total))
    cls_bar = "".join(
        f'<div class="seg s{name.split()[0]}" style="width:{v*100:.1f}%" title="{label} {pct(v)}"></div>'
        for label, n, v, name in [
            ("A", a["A"], a["A"]/total, "A 方向错"),
            ("B", a["B"], a["B"]/total, "B 方向对盈利"),
            ("C", a["C"], a["C"]/total, "C 方向对小赚"),
            ("D", a["D"], a["D"]/total, "D 方向对倒亏"),
        ]
    )
    pf = f'{econ["profit_factor"]:.2f}' if econ.get("profit_factor") else "NA"
    html = f"""
    <div class="card">
      <div class="card-h">{title} {badge(rel)}</div>
      <div class="mfe-src">MFE 源：{mfe_src}</div>
      <div class="bar">{cls_bar}</div>
      <table class="t">
        <tr><th>分类</th><th>笔数</th><th>占比</th></tr>
        {''.join(f'<tr><td>{l}</td><td>{n}</td><td>{pct(v)}</td></tr>' for l,n,v in rows)}
      </table>
      <div class="metrics">
        <div><span>逻辑存活率(方向正确率)</span><b>{pct(a['thesis_survival_rate'])}</b></div>
        <div><span>利润捕获率(中位)</span><b>{a['capture_median']:.2f}</b></div>
        <div><span>提前退出率(C+D/方向对)</span><b>{pct(a['premature_exit_rate'])}</b></div>
        <div><span>★ 信念兑现率</span><b class="hl">{pct(a['belief_fulfillment_rate'])}</b></div>
        <div><span>C+D 合计</span><b>{pct(a['cd_rate'])}</b></div>
      </div>
      <div class="econ">
        经济：胜率 {pct(econ['win_rate'])} ｜ 盈亏比 PF={pf} ｜ 净盈亏 <b>{money(econ['net_pnl'])}</b>
        ｜ 均持仓 {econ['avg_hold_days']:.1f}天 ｜ 同日平仓率 {pct(econ['same_day_rate'])}
      </div>
      {extra}
    </div>"""
    return html


CSS = f"""
* {{ box-sizing: border-box; }}
body {{ margin:0; font-family:-apple-system,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;
  background:linear-gradient(160deg,{BG0},{BG1}); color:#d7e4dc; padding:28px; }}
.wrap {{ max-width:1080px; margin:0 auto; }}
h1 {{ color:{GREEN}; font-size:26px; margin:0 0 4px; letter-spacing:1px; }}
.sub {{ color:#7d9388; font-size:13px; margin-bottom:18px; }}
.legend {{ font-size:12px; color:#9fb3a8; margin-bottom:18px; }}
.badge {{ font-size:11px; padding:2px 8px; border-radius:10px; margin-left:8px; vertical-align:middle; }}
.badge.ok {{ background:rgba(46,125,82,.25); color:#7fe0b0; border:1px solid {GREEN}; }}
.badge.warn {{ background:rgba(180,140,40,.18); color:#e6c878; border:1px solid #8a6d28; }}
.card {{ background:rgba(255,255,255,.035); border:1px solid rgba(46,125,82,.25);
  border-radius:12px; padding:18px 20px; margin-bottom:16px; }}
.card-h {{ font-size:17px; font-weight:600; color:#eaf3ee; margin-bottom:4px; }}
.mfe-src {{ font-size:11px; color:#7d9388; margin-bottom:10px; }}
.bar {{ display:flex; height:22px; border-radius:6px; overflow:hidden; margin-bottom:12px; background:#0a0f0c; }}
.seg {{ height:100%; }}
.sA {{ background:#5b6b63; }} .sB {{ background:{GREEN}; }} .sC {{ background:#c79a3a; }} .sD {{ background:#b5524a; }}
table.t {{ width:100%; border-collapse:collapse; font-size:13px; margin-bottom:12px; }}
table.t th {{ text-align:left; color:#7d9388; font-weight:500; padding:4px 6px; border-bottom:1px solid rgba(255,255,255,.08); }}
table.t td {{ padding:4px 6px; border-bottom:1px solid rgba(255,255,255,.04); }}
.metrics {{ display:grid; grid-template-columns:repeat(5,1fr); gap:8px; margin-bottom:10px; }}
.metrics > div {{ background:rgba(0,0,0,.25); border-radius:8px; padding:8px; text-align:center; }}
.metrics span {{ display:block; font-size:10px; color:#7d9388; margin-bottom:4px; }}
.metrics b {{ font-size:16px; color:#eaf3ee; }}
.metrics b.hl {{ color:#7fe0b0; }}
.econ {{ font-size:12px; color:#bcd0c6; background:rgba(0,0,0,.18); padding:8px 10px; border-radius:8px; }}
.econ b {{ color:#eaf3ee; }}
.uview {{ width:100%; border-collapse:collapse; font-size:13px; margin-top:6px; }}
.uview th, .uview td {{ padding:8px 10px; border-bottom:1px solid rgba(255,255,255,.06); text-align:center; }}
.uview th {{ color:#7d9388; font-weight:500; }}
.uview td:first-child {{ text-align:left; }}
.concl {{ background:rgba(46,125,82,.12); border-left:3px solid {GREEN}; padding:14px 16px;
  border-radius:8px; font-size:13.5px; line-height:1.7; color:#dcebe3; margin-top:8px; }}
.prod {{ font-size:12px; color:#bcd0c6; margin-top:8px; }}
.prod span {{ display:inline-block; margin:2px 8px 2px 0; }}
.foot {{ font-size:11px; color:#6b8076; margin-top:20px; line-height:1.6; }}
"""


def main():
    with open(JSON_PATH, encoding="utf-8") as f:
        r = json.load(f)
    s, fz, m = r["stock"], r["futures"], r["mt5"]

    def _pf(pe):
        return f'{pe["profit_factor"]:.2f}' if pe.get("profit_factor") else "NA"

    # 期货按品种经济
    prod_html = "".join(
        f'<span>{p}: <b>{money(pe["net_pnl"])}</b> (胜{pct(pe["win_rate"])}·PF{_pf(pe)})</span>'
        for p, pe in sorted(fz["by_product"].items(), key=lambda x: x[1]["net_pnl"])
    )

    fut_extra = (
        f'<div class="prod">按品种净盈亏（全部合约，可靠）：{prod_html}</div>'
        f'<div class="prod">期权经济净盈亏：<b>{money(fz["opt_econ"]["net_pnl"])}</b> '
        f'（n={fz["opt_econ"]["n"]}，非线性的，不计入 MFE）</div>'
        f'<div class="mfe-src" style="margin-top:8px">⚠ 期货 A/B/C/D 仅 au/ag/cu 三个品种可用日线连续收盘近似，'
        f'且为保守下界（日内 scalp 占 {pct(fz["econ"]["same_day_rate"])}，日线收盘无法捕捉盘中有利波动，'
        f'故方向正确率被低估）。可靠信号请看上方经济画像。</div>'
    )

    fut_abcd_block = (
        abcd_block("期货（A/B/C/D 近似）", fz["abcd"], fz["econ"], "proxy",
                   fz["mfe_source"], fut_extra)
        if fz["abcd"]["total"] else
        f'<div class="card"><div class="card-h">期货（A/B/C/D）</div>'
        f'<div class="mfe-src">无可用 MFE 源，A/B/C/D = N/A；经济画像见下。</div>'
        f'{fut_extra}</div>'
    )

    mt5_block = f"""
    <div class="card">
      <div class="card-h">MT5 黄金 XAUUSD {badge('reliable')}</div>
      <div class="mfe-src">MFE 源：既有 MT5 分析（210 笔，已验证，tick/M1 级）</div>
      <div class="metrics">
        <div><span>逻辑存活率</span><b>{pct(m['thesis_survival_rate'])}</b></div>
        <div><span>利润捕获率(中位)</span><b>{m['capture_median']:.2f}</b></div>
        <div><span>提前退出率</span><b>{pct(m['premature_exit_rate'])}</b></div>
        <div><span>★ 信念兑现率</span><b class="hl">{pct(m['belief_fulfillment_rate'])}</b></div>
        <div><span>C+D 合计</span><b>{pct(m['cd_rate'])}</b></div>
      </div>
      <div class="econ">经济：净盈亏 <b>+9.01 USD</b> ｜ A=14 B=23 C=40 D=133（来源：{m['source']}）</div>
    </div>"""

    uview = f"""
    <div class="card">
      <div class="card-h">统一视图 · 跨账户稳定行为</div>
      <table class="uview">
        <tr><th>账户</th><th>可靠性</th><th>方向正确率</th><th>信念兑现率</th><th>C+D%</th><th>净盈亏</th></tr>
        <tr><td>股票（A股）</td><td>可靠</td><td>{pct(s['abcd']['thesis_survival_rate'])}</td>
            <td>{pct(s['abcd']['belief_fulfillment_rate'])}</td><td>{pct(s['abcd']['cd_rate'])}</td>
            <td>{money(s['econ']['net_pnl'])}</td></tr>
        <tr><td>期货（近似）</td><td>保守近似</td>
            <td>{pct(fz['abcd']['thesis_survival_rate']) if fz['abcd']['total'] else 'NA'}</td>
            <td>{pct(fz['abcd']['belief_fulfillment_rate']) if fz['abcd']['total'] else 'NA'}</td>
            <td>{pct(fz['abcd']['cd_rate']) if fz['abcd']['total'] else 'NA'}</td>
            <td>{money(fz['econ']['net_pnl'])}</td></tr>
        <tr><td>MT5 黄金</td><td>可靠</td><td>{pct(m['thesis_survival_rate'])}</td>
            <td>{pct(m['belief_fulfillment_rate'])}</td><td>{pct(m['cd_rate'])}</td><td>+9.01</td></tr>
      </table>
      <div class="concl">
        <b>跨账户结论：</b>股票 + MT5 两个<b>可靠口径</b>账户，方向正确率均高（98.5% / 93.3%）、信念兑现率均低
        （20.1% / 11.7%）→ 漏损在<b>执行/持有层</b>，不在判断层。期货经济画像（净 −7.25 万、盈亏比 PF 0.69&lt;1、
        同日平仓率 {pct(fz['econ']['same_day_rate'])}）是一套<b>亏损的高频 scalp 系统</b>，与 MT5「方向对 93% 却只兑现 11.7%」
        同构。三个账户指向同一条稳定行为：<b>懂且拿得住的（股票黄金ETF、MT5 黄金）赚钱；高频折腾、卖期权、提前平的（期货）亏钱。</b>
        瓶颈一致 = <b>持仓/兑现</b>，非预测。
      </div>
    </div>"""

    html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>多账户 Belief Execution Engine 视图</title><style>{CSS}</style></head>
<body><div class="wrap">
  <h1>多账户 Belief Execution Engine 视图</h1>
  <div class="sub">信念兑现引擎 · A/B/C/D + 信念兑现率 · 股票 / 期货 / MT5 三账户统一 · 生成于 2026-08-06</div>
  <div class="legend">可靠性图例：🟢 <b>可靠</b> = 真实 OHLC 或已验证分析；🟡 <b>近似/保守</b> = 数据受限下的保守下界，仅作方向参考。</div>

  {abcd_block("股票 A股（A/B/C/D 可靠）", s["abcd"], s["econ"], "reliable", s["mfe_source"])}
  {fut_abcd_block}
  {mt5_block}
  {uview}

  <div class="foot">
    数据来源与口径：<br>
    · 股票：tonghuashun_stock_trade（233 笔）→ FIFO 重建 136 round-trips；MFE 用 stock_daily 真实 OHLC（2000~2026）。<br>
    · 期货：tonghuashun_futures_trade（2586 笔，文华对账单权威口径）→ FIFO 重建 1340 round-trips；净额 −72,490.81 与对账单核对一致。<br>
    · 期货 MFE：具体合约已过期，本地 WH6 / TDX / westock 均无历史 OHLC；commodity_daily 仅主力连续且无高低点，
      故 au/ag/cu 用日线<b>收盘</b>做保守近似（close≤真实高低点，为有利波动下界；换月跳空未修正）；si/ps/FG/PK/jm 与期权无路径数据，A/B/C/D = N/A，仅给经济画像。<br>
    · MT5：沿用 trading_discipline_engine 已验证分析（210 笔 XAUUSD，tick/M1 级 MFE）。<br>
    · A/B/C/D 定义与 trading_discipline_engine.abcd_analysis 一致：A 方向错(mfe≤0) / B 方向对且 capture≥0.5 /
      C 方向对提前小赚 / D 方向对倒亏；信念兑现率 = 方向对且 capture≥0.5 ÷ 方向对。<br>
    · 诚实 NULL &gt; 伪精确：期货 A/B/C/D 为数据受限下的保守近似，不构成精确结论。
  </div>
</div></body></html>"""

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print("✅ 报告已生成:", os.path.abspath(OUT_PATH))


if __name__ == "__main__":
    main()
