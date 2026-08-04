# backend/build_monthly_cio.py
"""
Monthly CIO Report v0.1 — 模板定义 + 草稿生成

本周范围（用户 2026-08-04）：只"定义模板 + 出 v0.1 草稿"，完整 v1.0 留待下月。
固定四段结构（用户给定）：
  1. Executive Summary   一页，回答"现在是什么环境 / 建议是什么"
  2. Regime Analysis      市场状态 + 四维宏观（Growth/Inflation/Liquidity/RiskAppetite）
  3. Asset Ranking        资产评分排序表
  4. Portfolio Recommendation  加 / 减 / 持

仅消费现有数据（regime_history + asset_intelligence_history）。
全球资产（标普500/纳指100/恒生科技/黄金ETF/国债ETF）目前库里没有 -> 诚实标"待接入数据"。
四维宏观目前库里没有 -> 诚实标"待接入宏观数据"。
"""
import sqlite3, json, os
from cio_decision_engine import produce_decision, REGIME_LABEL

DB = os.path.join(os.path.dirname(__file__), 'database', 'vibe_research.db')
OUT = os.path.join(os.path.dirname(__file__), 'output')

# 全球资产（待接入数据，诚实留空，不编造评分）
GLOBAL_ASSETS = [
    ('US_EQ', 'SPX', '标普500'),
    ('US_EQ', 'NDX', '纳指100'),
    ('HK_EQ', 'HSTECH', '恒生科技'),
    ('GOLD', 'GLD', '黄金ETF'),
    ('BOND', 'AGG', '国债ETF'),
]


def _conn():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def generate(as_of=None):
    con = _conn()
    cur = con.cursor()
    if not as_of:
        as_of = cur.execute('SELECT MAX(date) FROM regime_history').fetchone()[0]
    cur.execute(
        'SELECT risk_state,risk_score,risk_drivers,commodity_states '
        'FROM regime_history WHERE date=?', (as_of,))
    rg = cur.fetchone()
    cur.execute(
        'SELECT asset_class,symbol,name,score,state,trend,confidence '
        'FROM asset_intelligence_history WHERE date=? ORDER BY score DESC', (as_of,))
    aip = [dict(r) for r in cur.fetchall()]
    con.close()

    dec = produce_decision(as_of)

    # 1. Executive Summary
    if dec:
        exec_summary = (
            f"当前环境：{dec['risk_state']}（映射 {dec['regime_class']} {REGIME_LABEL[dec['regime_class']]}），"
            f"risk_score={dec['risk_score']}。建议：{dec['action']}；"
            f"核心配置 股{dec['allocation']['equity']}/金{dec['allocation']['gold']}/"
            f"债{dec['allocation']['bond']}/现{dec['allocation']['cash']}。置信度 {dec['confidence']}。"
            f"本建议仅作 CIO 决策参考，不自动交易。"
        )
    else:
        exec_summary = "暂无 regime 数据，无法生成摘要。"

    # 2. Regime Analysis（四维宏观诚实留空）
    regime_analysis = {
        'risk_state': rg['risk_state'] if rg else None,
        'risk_score': rg['risk_score'] if rg else None,
        'macro_drivers': rg['risk_drivers'] if rg else None,
        'growth': '待接入宏观数据',
        'inflation': '待接入宏观数据',
        'liquidity': '待接入宏观数据',
        'risk_appetite': rg['risk_state'] if rg else None,
    }

    # 3. Asset Ranking
    ranking = []
    for a in aip:
        ranking.append({
            'asset': a['name'], 'symbol': a['symbol'], 'score': a['score'],
            'state': a['state'], 'source': 'AIP(现有)',
        })
    for _, sy, na in GLOBAL_ASSETS:
        ranking.append({
            'asset': na, 'symbol': sy, 'score': None,
            'state': '待接入数据', 'source': '待接入',
        })

    # 4. Portfolio Recommendation
    if dec:
        port_rec = {
            'recommended_allocation': dec['allocation'],
            'action': dec['action'],
            'add': '权益' if dec['allocation']['equity'] > 60 else '黄金/债券(防御)',
            'reduce': '权益' if dec['allocation']['equity'] < 60 else '无',
            'hold': '现金缓冲' if dec['allocation']['cash'] > 0 else '—',
            'reasons': dec['reasons'],
            'note': dec['note'],
        }
    else:
        port_rec = None

    return {
        'report': 'Monthly CIO Report v0.1',
        'as_of': as_of,
        'executive_summary': exec_summary,
        'regime_analysis': regime_analysis,
        'asset_ranking': ranking,
        'portfolio_recommendation': port_rec,
    }


def _to_markdown(rep):
    L = []
    L.append(f"# Monthly CIO Report v0.1 — {rep['as_of']}\n")
    L.append("## 1. Executive Summary\n")
    L.append(rep['executive_summary'] + "\n")
    L.append("## 2. Regime Analysis\n")
    ra = rep['regime_analysis']
    L.append(f"- 市场状态: {ra['risk_state']}（risk_score={ra['risk_score']}）")
    L.append(f"- 宏观驱动: {ra['macro_drivers']}")
    L.append(f"- Growth: {ra['growth']}")
    L.append(f"- Inflation: {ra['inflation']}")
    L.append(f"- Liquidity: {ra['liquidity']}")
    L.append(f"- Risk Appetite: {ra['risk_appetite']}\n")
    L.append("## 3. Asset Ranking\n")
    L.append("| 资产 | 代码 | 评分 | 状态 | 来源 |")
    L.append("| --- | --- | ---: | --- | --- |")
    for r in rep['asset_ranking']:
        sc = r['score'] if r['score'] is not None else "—"
        L.append(f"| {r['asset']} | {r['symbol']} | {sc} | {r['state']} | {r['source']} |")
    L.append("")
    L.append("## 4. Portfolio Recommendation\n")
    pr = rep['portfolio_recommendation']
    if pr:
        a = pr['recommended_allocation']
        L.append(f"- 建议配置: 股 {a['equity']} / 金 {a['gold']} / 债 {a['bond']} / 现 {a['cash']}")
        L.append(f"- 动作: {pr['action']}")
        L.append(f"- 加配: {pr['add']}　减配: {pr['reduce']}　持有: {pr['hold']}")
        L.append("- 理由:")
        for x in pr['reasons']:
            L.append(f"  - {x}")
        L.append(f"- 备注: {pr['note']}")
    else:
        L.append("（无配置建议）")
    L.append("")
    L.append("> 模板 v0.1：全球资产与四维宏观为待接入项，随数据接入自动补全。")
    return "\n".join(L)


if __name__ == '__main__':
    rep = generate()
    os.makedirs(OUT, exist_ok=True)
    pj = os.path.join(OUT, f"monthly_cio_{rep['as_of']}.json")
    pm = os.path.join(OUT, f"monthly_cio_{rep['as_of']}.md")
    json.dump(rep, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    open(pm, 'w', encoding='utf-8').write(_to_markdown(rep))
    print("written:")
    print(" ", pj)
    print(" ", pm)
    print()
    print(_to_markdown(rep))
