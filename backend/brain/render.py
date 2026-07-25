# -*- coding: utf-8 -*-
"""
render：把 orchestrator 的 report 渲染为 brain_report.html。

视觉遵循现看板：红涨绿跌、卡片网格、badge。
结构：
  · 顶部 L0 叙事带（总指挥定调一句话）
  · 决策结论卡（can_buy 徽章 + 总置信度仪表 + 仓位护栏 + 决策依据）
  · 跨层冲突警示区
  · 推理链时间线（L0 定调 → L1…L8 串联，含上游输入/输出/风险点）
"""
import os

DIR_COLOR = {
    "bullish": "#1ba784", "neutral_bullish": "#52c41a",
    "neutral": "#8a8a8a", "neutral_bearish": "#d48806",
    "bearish_weak": "#e6a23c", "bearish": "#e23c3c", "human": "#409eff",
}
DIR_LABEL = {
    "bullish": "偏多", "neutral_bullish": "中性偏多", "neutral": "中性",
    "neutral_bearish": "中性偏空", "bearish_weak": "偏空", "bearish": "空",
    "human": "归你人工",
}
CANBUY = {
    "YES": ("#1ba784", "可以买 · YES"),
    "NO": ("#e23c3c", "不宜买 · NO"),
    "CAUTION": ("#e6a23c", "谨慎 · CAUTION"),
}

CSS = """
* { box-sizing: border-box; }
body { margin:0; background:#f5f6f8; color:#222;
  font-family:-apple-system,"PingFang SC","Microsoft YaHei",Segoe UI,sans-serif; }
.wrap { max-width:1080px; margin:0 auto; padding:24px 20px 60px; }
.hd h1 { font-size:24px; margin:0 0 6px; }
.hd .sub { font-size:13px; color:#888; font-weight:400; margin-left:8px; }
.meta { color:#666; font-size:13px; }
.l0-band { margin:18px 0; padding:18px 20px; border-radius:12px;
  background:linear-gradient(135deg,#1f2a44,#33415c); color:#fff; box-shadow:0 4px 14px rgba(0,0,0,.12); }
.l0-head { font-size:20px; font-weight:700; line-height:1.4; }
.l0-body { margin-top:8px; font-size:14px; color:#cdd6e6; line-height:1.7; }
.decision { display:flex; gap:18px; margin:18px 0; }
.decision > div { background:#fff; border:1px solid #e5e7eb; border-radius:12px; padding:18px; }
.dec-left { width:240px; display:flex; flex-direction:column; align-items:center; gap:14px; }
.cb { color:#fff; font-size:18px; font-weight:700; padding:12px 18px; border-radius:10px; text-align:center; }
.gauge { text-align:center; width:100%; }
.g-num { font-size:40px; font-weight:800; line-height:1; }
.g-lab { font-size:12px; color:#888; margin:4px 0 8px; }
.g-bar { height:8px; background:#eee; border-radius:6px; overflow:hidden; }
.g-bar i { display:block; height:100%; border-radius:6px; }
.dec-right { flex:1; }
.pos { font-size:15px; }
.pos b { font-size:18px; color:#1ba784; }
.hard { display:inline-block; margin-left:8px; padding:2px 8px; border-radius:6px;
  background:#fde8e8; color:#e23c3c; font-size:12px; font-weight:600; }
.why { margin:12px 0 6px; font-size:13px; color:#888; font-weight:600; }
.reasons { margin:0; padding-left:18px; }
.reasons li { margin:4px 0; line-height:1.6; }
.vote { margin-top:12px; font-size:12px; color:#999; }
.cf-box { background:#fff7ed; border:1px solid #f6c177; border-radius:10px; padding:14px 16px; margin:14px 0; }
.cf-title { font-weight:700; color:#c0620a; margin-bottom:8px; }
.cf { font-size:13px; padding:6px 10px; border-radius:8px; margin:6px 0; line-height:1.5; }
.cf-high { background:#fde8e8; border-left:3px solid #e23c3c; }
.cf-med  { background:#fff5e6; border-left:3px solid #e6a23c; }
.cf-low  { background:#eef4ff; border-left:3px solid #409eff; }
.sec-title { font-size:16px; font-weight:700; margin:22px 0 12px; }
.timeline { position:relative; padding-left:30px; }
.timeline::before { content:''; position:absolute; left:10px; top:4px; bottom:4px; width:2px; background:#d8dde6; }
.node { position:relative; margin-bottom:14px; }
.node::before { content:''; position:absolute; left:-24px; top:16px; width:13px; height:13px;
  border-radius:50%; background:#1ba784; border:3px solid #fff; box-shadow:0 0 0 1px #cdd3dd; }
.card { background:#fff; border:1px solid #e5e7eb; border-radius:10px; padding:12px 14px; }
.card-h { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.layer { font-weight:800; color:#334155; font-size:13px; }
.title { font-weight:600; font-size:14px; }
.dir { color:#fff; font-size:11px; padding:2px 8px; border-radius:6px; }
.conf { margin-left:auto; font-size:12px; font-weight:700; }
.up { margin:8px 0 2px; font-size:12px; color:#8a94a6; background:#f5f7fa; padding:5px 8px; border-radius:6px; }
.out { margin-top:6px; font-size:14px; line-height:1.65; }
.risk { margin-top:8px; font-size:12px; color:#c0620a; background:#fff5e6;
  border-left:3px solid #e6a23c; padding:5px 9px; border-radius:6px; }
.lf-box { background:#eef7f0; border:1px solid #a5d6b0; border-radius:10px; padding:14px 16px; margin:14px 0; }
.lf-box.pending { background:#f5f6f8; border:1px dashed #cbd2dc; }
.lf-title { font-weight:700; color:#159a70; margin-bottom:8px; }
.lf-box.pending .lf-title { color:#8a94a6; }
.lf-note { font-size:13px; padding:3px 0; line-height:1.6; color:#3a6b52; }
.lf-box.pending .lf-note { color:#8a94a6; }
.l0-card { background:#fff; border:1px solid #c3cee0; border-left:4px solid #33415c; border-radius:10px; padding:12px 14px; }
.l0-tag { font-size:12px; color:#5b6b86; font-weight:600; }
.l0-head { font-size:15px; font-weight:700; margin-top:4px; line-height:1.5; }
.l0-body { font-size:13px; color:#555; margin-top:4px; line-height:1.6; }
.narrative-section { margin: 22px 0; }
.narrative-section .sec-title { font-size: 16px; font-weight: 700; margin: 22px 0 12px; }
.narr-grid { display: grid; gap: 14px; }
.narr-card { background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 16px 18px; }
.narr-card.driver { border-left: 4px solid #6366f1; }
.narr-card.counter { border-left: 4px solid #f59e0b; background: #fffbeb; }
.narr-card.consensus { border-left: 4px solid #10b981; }
.narr-q { font-size: 13px; font-weight: 700; color: #6366f1; margin-bottom: 6px; }
.narr-a { font-size: 15px; font-weight: 600; line-height: 1.5; color: #1f2937; }
.narr-detail { font-size: 13px; color: #6b7280; margin-top: 4px; line-height: 1.6; }
.narr-driver { font-size: 13px; color: #6366f1; margin-top: 6px; font-weight: 500; }
.narr-table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 13px; }
.narr-table th { text-align: left; padding: 6px 10px; background: #f3f4f6; color: #374151; font-weight: 600; border-radius: 6px 6px 0 0; }
.narr-table td { padding: 6px 10px; border-bottom: 1px solid #f0f0f0; }
.narr-table tr:last-child td { border-bottom: none; }
.narr-tag { display: inline-block; padding: 1px 8px; border-radius: 6px; font-size: 11px; font-weight: 600; }
.narr-tag.fact { background: #d1fae5; color: #065f46; }
.narr-tag.infer { background: #fef3c7; color: #92400e; }
.narr-chain { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; margin-top: 8px; font-size: 13px; }
.narr-chain .step { background: #f3f4f6; padding: 4px 10px; border-radius: 6px; font-weight: 500; }
.narr-chain .arrow { color: #9ca3af; font-size: 12px; }
.narr-chain .conf { font-size: 10px; color: #6b7280; }
.narr-chain .conf-low { color: #ef4444; font-weight: 600; }
.narr-weakest { background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 10px 12px; margin-top: 10px; font-size: 13px; line-height: 1.6; }
.narr-weakest b { color: #dc2626; }
.narr-flow { background: #fffbeb; border-radius: 8px; padding: 10px 12px; margin-top: 8px; font-size: 13px; line-height: 1.6; color: #92400e; }
.narr-moves { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.narr-move { padding: 4px 10px; border-radius: 8px; font-size: 12px; font-weight: 600; }
.narr-move.up { background: #fef2f2; color: #dc2626; }
.narr-move.down { background: #f0fdf4; color: #16a34a; }
.narr-move.flat { background: #f3f4f6; color: #6b7280; }
/* 事件驱动日历 */
.catalyst-card { grid-column: 1 / -1; }
.catalyst-list { margin-top: 10px; }
.catalyst-row { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-radius: 8px; margin-bottom: 6px; font-size: 13px; }
.catalyst-row.high { background: #eff6ff; border: 1px solid #bfdbfe; }
.catalyst-row.medium { background: #f9fafb; border: 1px solid #e5e7eb; }
.catalyst-row.low { background: #f9fafb; }
.catalyst-date { font-weight: 700; min-width: 100px; color: #1e40af; }
.catalyst-name { font-weight: 600; min-width: 130px; }
.catalyst-days { min-width: 60px; }
.catalyst-days .badge { display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; }
.catalyst-days .badge.soon { background: #dc2626; color: #fff; }
.catalyst-days .badge.week { background: #e6a23c; color: #fff; }
.catalyst-days .badge.later { background: #6b7280; color: #fff; }
.catalyst-fields { color: #666; font-size: 12px; }
.catalyst-flag { font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 700; }
.catalyst-flag.US { background: #1e3a5f; color: #fff; }
.catalyst-flag.CN { background: #b91c1c; color: #fff; }
.catalyst-section-title { font-size: 14px; font-weight: 700; margin: 14px 0 6px; color: #1e40af; }
.footer { margin-top:30px; font-size:12px; color:#9aa3b2; text-align:center;
  border-top:1px solid #e5e7eb; padding-top:14px; }
/* 研究员备忘录 */
.memo-section { margin: 22px 0; }
.memo-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.memo-card { background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 16px 18px; }
.memo-card.p1 { border-left: 4px solid #33415c; }
.memo-card.p2 { border-left: 4px solid #6366f1; }
.memo-card.p3 { border-left: 4px solid #1ba784; }
.memo-card.p4 { border-left: 4px solid #e23c3c; }
.memo-part-num { display: inline-block; font-size: 12px; font-weight: 700; color: #fff;
  background: #33415c; padding: 2px 8px; border-radius: 6px; margin-bottom: 4px; }
.memo-card.p2 .memo-part-num { background: #6366f1; }
.memo-card.p3 .memo-part-num { background: #1ba784; }
.memo-card.p4 .memo-part-num { background: #e23c3c; }
.memo-part-title { font-size: 15px; font-weight: 700; margin: 6px 0 10px; }
.memo-gold { font-size: 16px; font-weight: 700; color: #1f2937; line-height: 1.5;
  background: #fefce8; border: 1px solid #fde68a; border-radius: 8px; padding: 10px 14px; margin-bottom: 10px; }
.memo-content { margin: 10px 0; }
.memo-q { font-size: 12px; font-weight: 600; color: #8a94a6; margin-bottom: 4px; text-transform: uppercase; }
.memo-a { font-size: 14px; line-height: 1.65; color: #374151; }
.memo-highlight { color: #d97706; font-weight: 600; }
.memo-flow { background: #f5f7fa; padding: 8px 12px; border-radius: 8px; font-size: 13px; }
.memo-pattern { margin-top: 6px; font-size: 12px; color: #8a94a6; }
.memo-no-leader { color: #9ca3af; font-style: italic; margin-top: 4px; }
.memo-table { width: 100%; border-collapse: collapse; margin-top: 6px; font-size: 12px; }
.memo-table th { text-align: left; padding: 4px 8px; background: #f3f4f6; color: #6b7280; font-weight: 600; font-size: 11px; }
.memo-table td { padding: 4px 8px; border-bottom: 1px solid #f3f4f6; }
.ms-name { font-weight: 600; }
.ms-desc { color: #6b7280; font-size: 11px; }
.ms-persist { font-size: 11px; }
.memo-list { margin: 4px 0; padding-left: 18px; }
.memo-list li { font-size: 13px; line-height: 1.6; margin: 3px 0; }
.memo-risk { color: #dc2626; font-weight: 600; background: #fef2f2; padding: 8px 12px; border-radius: 8px; }
.memo-position { margin-top: 6px; font-size: 13px; font-weight: 600; color: #159a70; }
.cat-high { font-weight: 600; color: #1e40af; }
.cat-norm { color: #374151; }
.cat-flag { font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 700; margin-right: 4px; }
.cat-flag.US { background: #1e3a5f; color: #fff; }
.cat-flag.CN { background: #b91c1c; color: #fff; }
.cat-date { font-weight: 600; }
.cat-days { text-align: right; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; }
.badge.soon { background: #dc2626; color: #fff; }
.badge.week { background: #e6a23c; color: #fff; }
.badge.later { background: #6b7280; color: #fff; }

/* ── CIO 投资决策备忘录 ── */
.cio-header { background: linear-gradient(135deg, #1e293b, #334155); color: #fff; padding: 16px 20px; border-radius: 10px 10px 0 0; }
.cio-title { font-size: 18px; font-weight: 700; margin-bottom: 4px; }
.cio-date { font-size: 13px; opacity: .85; }
.cio-dec { font-weight: 700; padding: 1px 8px; border-radius: 4px; }
.cio-dec-YES { background: #16a34a; }
.cio-dec-NO { background: #dc2626; }
.cio-dec-CAUTION { background: #e6a23c; color: #333; }

.cio-thesis { background: #fff; border: 2px solid #1e293b; border-radius: 0; padding: 20px; margin: 0; }
.cio-gold { font-size: 17px; font-weight: 700; line-height: 1.7; color: #1e293b; margin-bottom: 8px; }
.cio-conviction { display: inline-block; font-size: 12px; padding: 2px 10px; background: #1e293b; color: #fff; border-radius: 12px; margin-bottom: 8px; }
.cio-explain { font-size: 13px; color: #64748b; line-height: 1.6; }
.cio-global-link { margin-top: 12px; padding: 10px 14px; background: #eff6ff; border-left: 4px solid #3b82f6; border-radius: 4px; font-size: 13px; color: #1e40af; line-height: 1.6; }

.cio-section-title { font-size: 15px; font-weight: 700; color: #1e293b; padding: 12px 0 8px 0; border-bottom: 2px solid #e2e8f0; margin-bottom: 12px; }

.cio-evidence { background: #fff; padding: 16px 20px; border: 1px solid #e2e8f0; }
.cio-claim { padding: 8px 0; border-bottom: 1px solid #f1f5f9; }
.cio-claim-type { font-size: 11px; padding: 1px 6px; border-radius: 3px; font-weight: 600; }
.cio-claim-type.verified { background: #dcfce7; color: #166534; }
.cio-claim-type.inferred { background: #fef3c7; color: #92400e; }
.cio-claim-text { font-size: 13px; color: #334155; }
.cio-claim-evidence { font-size: 12px; color: #94a3b8; padding-left: 12px; margin-top: 2px; }
.cio-uncertain { background: #fff7ed; border-left: 3px solid #f97316; padding: 8px 12px; margin-top: 10px; border-radius: 4px; font-size: 12px; color: #9a3412; }
.cio-conflict-item { color: #dc2626; }

.cio-money { background: #fff; padding: 16px 20px; border: 1px solid #e2e8f0; }
.cio-pattern { font-size: 14px; margin-bottom: 8px; color: #334155; }
.cio-migration { font-size: 13px; color: #64748b; margin-bottom: 12px; }
.cio-inflection { font-size: 12px; color: #e6a23c; padding: 8px 0 0 0; }

.cio-tbl { width: 100%; border-collapse: collapse; font-size: 13px; margin: 8px 0; }
.cio-tbl th { background: #f8fafc; padding: 7px 10px; text-align: left; font-weight: 600; border-bottom: 2px solid #e2e8f0; }
.cio-tbl td { padding: 6px 10px; border-bottom: 1px solid #f1f5f9; }
.cio-stars { color: #e6a23c; font-size: 13px; white-space: nowrap; }
.cio-sector { font-weight: 600; }
.cio-chain { font-size: 12px; color: #6366f1; }

.cio-bars { padding: 10px 0; }
.cio-bar-row { display: flex; align-items: center; gap: 8px; margin: 4px 0; }
.cio-bar-label { font-size: 12px; font-weight: 600; width: 40px; color: #475569; }
.cio-bar-track { flex: 1; height: 14px; background: #f1f5f9; border-radius: 7px; overflow: hidden; }
.cio-bar-fill { height: 100%; background: linear-gradient(90deg, #3b82f6, #6366f1); border-radius: 7px; }
.cio-bar-val { font-size: 12px; font-weight: 600; color: #475569; width: 30px; text-align: right; }

.cio-mainlines { background: #fff; padding: 16px 20px; border: 1px solid #e2e8f0; }

.cio-trading { background: #fff; padding: 16px 20px; border: 1px solid #e2e8f0; }
.cio-no-opp { font-size: 16px; font-weight: 700; color: #dc2626; margin-bottom: 8px; }
.cio-no-opp-reason { font-size: 13px; color: #64748b; line-height: 1.6; }
.cio-opp-card { padding: 12px; margin: 8px 0; border-radius: 6px; border: 1px solid #e2e8f0; }
.cio-tier-A { border-left: 4px solid #16a34a; background: #f0fdf4; }
.cio-tier-B { border-left: 4px solid #e6a23c; background: #fffbeb; }
.cio-tier-C { border-left: 4px solid #6b7280; background: #f9fafb; }
.cio-opp-tier { font-size: 14px; margin-bottom: 4px; }
.cio-opp-cond { font-size: 12px; color: #166534; }
.cio-opp-giveup { font-size: 12px; color: #dc2626; }
.cio-opp-rationale { font-size: 12px; color: #6b7280; margin-top: 4px; }

.cio-risk { background: #fff; padding: 16px 20px; border: 1px solid #e2e8f0; }
.cio-big-risk { font-size: 14px; color: #dc2626; margin-bottom: 12px; line-height: 1.6; }
.cio-fals-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.cio-fals { background: #fef2f2; border-left: 3px solid #dc2626; padding: 8px 12px; border-radius: 4px; font-size: 12px; line-height: 1.5; }
.cio-events { margin-top: 12px; font-size: 12px; color: #6366f1; padding: 8px 12px; background: #eef2ff; border-radius: 4px; }

.cio-historical { background: #fff; padding: 16px 20px; border: 1px solid #e2e8f0; }
.cio-hist-conclusion { font-size: 13px; color: #475569; line-height: 1.6; }
.cio-hist-stats { font-size: 14px; margin-top: 8px; color: #1e293b; }

.cio-footer { font-size: 11px; color: #94a3b8; text-align: center; padding: 12px 0; border-top: 1px solid #e2e8f0; margin-top: 8px; }

.cio-memo { border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; margin: 16px 0; }
.cio-memo > div:not(.cio-header) { border-top: 1px solid #e2e8f0; }
"""


def _conf_color(c):
    if c is None:
        return "#8a8a8a"
    if c >= 70:
        return "#1ba784"
    if c >= 50:
        return "#e6a23c"
    return "#e23c3c"


def _render_narrative(gn):
    """渲染 Market Narrative Intelligence 板块。"""
    if not gn or not gn.get("headline") or "不可用" in gn.get("headline", ""):
        return ""

    nid = gn.get("narrative_id")
    if not nid:
        # 无明确叙事 — 简短展示
        moves = gn.get("raw_changes") or {}
        move_html = ""
        if moves:
            labels = {"oil": "原油", "gold": "黄金", "btc": "BTC", "usd": "美元", "equity": "美股", "dxy": "DXY", "copper": "铜"}
            parts = ""
            for k, v in moves.items():
                if v is None:
                    continue
                cls = "up" if v > 0 else "down" if v < 0 else "flat"
                parts += f"<span class='narr-move {cls}'>{labels.get(k, k)} {v:+.2f}%</span>"
            move_html = f"<div class='narr-moves'>{parts}</div>" if parts else ""
        return f"""<div class='narrative-section'>
          <div class='sec-title'>Market Narrative Intelligence · 市场叙事引擎</div>
          <div class='narr-grid'>
            <div class='narr-card'>
              <div class='narr-q'>① 今天市场在交易什么叙事？</div>
              <div class='narr-a'>{gn.get('headline', '无明确叙事')}</div>
              <div class='narr-detail'>{gn.get('headline_detail', '').replace(chr(10), '<br>')}</div>
              {move_html}
            </div>
          </div>
        </div>"""

    # 有明确叙事 — 完整渲染
    # ① 叙事定调
    headline = gn.get("headline", "")
    headline_detail = gn.get("headline_detail", "").replace("\n", "<br>")
    true_driver = gn.get("true_driver", "")
    match_score = gn.get("match_score", 0)

    # 资产变动
    raw_changes = gn.get("raw_changes") or {}
    labels = {"oil": "原油", "gold": "黄金", "btc": "BTC", "usd": "美元", "equity": "美股", "dxy": "DXY", "copper": "铜"}
    move_parts = ""
    for k, v in raw_changes.items():
        if v is None:
            continue
        cls = "up" if v > 0 else "down" if v < 0 else "flat"
        move_parts += f"<span class='narr-move {cls}'>{labels.get(k, k)} {v:+.2f}%</span>"
    move_html = f"<div class='narr-moves'>{move_parts}</div>" if move_parts else ""

    # ② 事实 vs 推断表
    decomposition = gn.get("decomposition") or []
    table_rows = ""
    for d in decomposition:
        tag_cls = "fact" if d.get("type") in ("event", "data") else "infer"
        tag_label = d.get("type_label", "")
        conf = d.get("confidence", 0)
        conf_pct = int(conf * 100) if isinstance(conf, float) else conf
        conf_cls = "conf-low" if conf_pct < 70 else ""
        table_rows += (
            f"<tr>"
            f"<td>{d.get('step', '')}</td>"
            f"<td><span class='narr-tag {tag_cls}'>{tag_label}</span></td>"
            f"<td>{d.get('verifiable_label', '')}</td>"
            f"<td class='{conf_cls}'>{conf_pct}%</td>"
            f"</tr>"
        )
    table_html = (
        f"<table class='narr-table'>"
        f"<tr><th>环节</th><th>类型</th><th>可验证</th><th>置信度</th></tr>"
        f"{table_rows}</table>"
    ) if table_rows else ""

    # 因果链
    conf_chain = gn.get("confidence_chain") or []
    chain_parts = ""
    for i, link in enumerate(conf_chain):
        conf = link.get("confidence", 0)
        conf_pct = int(conf * 100) if isinstance(conf, float) else 0
        conf_cls = "conf-low" if conf_pct < 70 else ""
        chain_parts += f"<span class='step'>{link.get('step', '')}</span>"
        chain_parts += f"<span class='conf {conf_cls}'>[{conf_pct}%]</span>"
        if i < len(conf_chain) - 1:
            chain_parts += "<span class='arrow'>→</span>"
    chain_html = f"<div class='narr-chain'>{chain_parts}</div>" if chain_parts else ""

    # 最弱环节
    weakest = gn.get("weakest_link", "")
    weakest_reason = gn.get("weakest_reason", "")
    weakest_html = ""
    if weakest:
        weakest_html = (
            f"<div class='narr-weakest'>"
            f"<b>⚠ 最弱环节：{weakest}</b><br>"
            f"{weakest_reason}"
            f"</div>"
        )

    # ③ 共识阶段
    consensus_stage = gn.get("consensus_stage", "")
    consensus_note = gn.get("consensus_note", "")

    # ④⑤ 反事实
    cf = gn.get("counterfactual") or {}
    cf_condition = cf.get("condition", "")
    cf_flow = cf.get("flow", "")

    # 事件驱动日历
    upcoming = gn.get("upcoming_catalysts") or []
    fals_cats = gn.get("falsification_catalysts") or []
    next_hi = gn.get("next_high_impact")

    catalyst_html = ""
    if upcoming or fals_cats:
        # 证伪窗口（最相关的 catalyst）
        fals_rows = ""
        for c in fals_cats[:6]:
            d = c.get("days_until", -1)
            if d < 0:
                continue
            date_str = c.get("expected_date", "")
            try:
                import datetime as _dt2
                parsed = _dt2.datetime.fromisoformat(date_str).date()
                date_cn = f"{parsed.month}月{parsed.day}日"
            except Exception:
                date_cn = date_str
            if d == 0:
                badge = "<span class='badge soon'>今日</span>"
            elif d == 1:
                badge = "<span class='badge soon'>明日</span>"
            elif d <= 7:
                badge = f"<span class='badge soon'>{d}天后</span>"
            elif d <= 14:
                badge = f"<span class='badge week'>{d}天后</span>"
            else:
                badge = f"<span class='badge later'>{d}天后</span>"
            country = c.get("country", "")
            flag = f"<span class='catalyst-flag {country}'>{country}</span>" if country else ""
            fields = "、".join(c.get("watch_fields", [])[:2])
            fals_rows += (
                f"<div class='catalyst-row {c.get('importance','')}'>"
                f"<span class='catalyst-flag {country}'>{country}</span>"
                f"<span class='catalyst-date'>{date_cn}</span>"
                f"<span class='catalyst-name'>{c.get('name','')}</span>"
                f"<span class='catalyst-days'>{badge}</span>"
                f"<span class='catalyst-fields'>关注：{fields}</span>"
                f"</div>"
            )

        # 全部事件日历
        all_rows = ""
        for c in upcoming[:8]:
            d = c.get("days_until", -1)
            if d < 0:
                continue
            date_str = c.get("expected_date", "")
            try:
                import datetime as _dt3
                parsed = _dt3.datetime.fromisoformat(date_str).date()
                date_cn = f"{parsed.month}月{parsed.day}日"
            except Exception:
                date_cn = date_str
            if d == 0:
                badge = "<span class='badge soon'>今日</span>"
            elif d <= 7:
                badge = f"<span class='badge soon'>{d}天后</span>"
            elif d <= 14:
                badge = f"<span class='badge week'>{d}天后</span>"
            else:
                badge = f"<span class='badge later'>{d}天后</span>"
            country = c.get("country", "")
            fields = "、".join(c.get("watch_fields", [])[:2])
            all_rows += (
                f"<div class='catalyst-row {c.get('importance','')}'>"
                f"<span class='catalyst-flag {country}'>{country}</span>"
                f"<span class='catalyst-date'>{date_cn}</span>"
                f"<span class='catalyst-name'>{c.get('name','')}</span>"
                f"<span class='catalyst-days'>{badge}</span>"
                f"<span class='catalyst-fields'>关注：{fields}</span>"
                f"</div>"
            )

        next_hi_html = ""
        if next_hi and next_hi.get("days_until", -1) >= 0:
            nd = next_hi["days_until"]
            nd_str = "今日" if nd == 0 else f"{nd}天后"
            next_hi_html = f"<div style='font-size:13px;margin-bottom:8px'>最近高影响事件：<b>{next_hi['name']}</b> · {nd_str}</div>"

        catalyst_html = f"""
        <div class='narr-card catalyst-card'>
          <div class='narr-q'>事件驱动日历 · Catalyst Calendar</div>
          {next_hi_html}
          <div class='catalyst-section-title'>证伪窗口（与当前叙事最相关）</div>
          <div class='catalyst-list'>{fals_rows or '<div class=\"catalyst-row low\">近期无相关事件</div>'}</div>
          <div class='catalyst-section-title'>未来 14 天全部事件</div>
          <div class='catalyst-list'>{all_rows or '<div class=\"catalyst-row low\">近期无事件</div>'}</div>
        </div>"""

    # A 股影响
    a_impact = gn.get("a_share_impact", "")

    # 备选叙事
    alternatives = gn.get("alternatives") or []
    alt_html = ""
    if alternatives:
        alt_parts = ""
        for a in alternatives:
            alt_parts += f"<span class='narr-move flat'>{a.get('name', '')} ({int(a.get('score', 0)*100)}%)</span>"
        alt_html = f"<div class='narr-detail' style='margin-top:8px'>备选叙事：{alt_parts}</div>"

    return f"""<div class='narrative-section'>
      <div class='sec-title'>Market Narrative Intelligence · 市场叙事引擎</div>
      <div class='narr-grid'>

        <div class='narr-card'>
          <div class='narr-q'>① 今天市场在交易什么叙事？</div>
          <div class='narr-a'>{headline}</div>
          <div class='narr-detail'>{headline_detail}</div>
          {move_html}
          {alt_html}
        </div>

        <div class='narr-card'>
          <div class='narr-q'>② 证据有哪些？哪些只是推断？</div>
          {table_html}
          <div class='narr-detail' style='margin-top:8px'>定价链（含置信度）：</div>
          {chain_html}
          {weakest_html}
        </div>

        <div class='narr-card driver'>
          <div class='narr-q'>真正的驱动变量</div>
          <div class='narr-driver'>{true_driver}</div>
          {"<div class='narr-detail' style='margin-top:6px'>A 股影响：" + a_impact + "</div>" if a_impact else ""}
        </div>

        <div class='narr-card consensus'>
          <div class='narr-q'>③ 市场共识走到什么阶段？</div>
          <div class='narr-a'>{consensus_stage}</div>
          <div class='narr-detail'>{consensus_note}</div>
        </div>

        <div class='narr-card counter'>
          <div class='narr-q'>④ 这个叙事最可能被什么证伪？</div>
          <div class='narr-a'>{cf_condition}</div>
          <div class='narr-q' style='margin-top:12px'>⑤ 如果叙事失效，资金流向哪里？</div>
          <div class='narr-flow'>{cf_flow}</div>
        </div>

        {catalyst_html}

      </div>
    </div>"""


def _render_flow(results):
    """渲染 Capital Flow Engine（资金情报中心）板块。"""
    fr = results.get("FLOW")
    if not fr:
        return ""
    raw = fr.get("raw") or {}
    intel = raw.get("intelligence") or {}
    fs = raw.get("flow_score") or {}
    comm = raw.get("commodity") or {}
    etf_sum = raw.get("etf_flow") or {}
    inst = raw.get("institution") or {}

    overall = fs.get("overall", 0)
    stars = fs.get("overall_stars", 0)
    star_str = "★" * stars + "☆" * (5 - stars)
    badge_color = "#1ba784" if overall >= 65 else ("#8a8a8a" if overall >= 45 else "#e23c3c")

    # 5-layer scores
    layer_rows = ""
    for key, label in [("m1_global", "M1 全球流动性"), ("m2_cross_asset", "M2 跨资产"),
                        ("m3_etf", "M3 ETF资金"), ("m4_sector", "M4 板块资金"), ("m5_individual", "M5 个股资金")]:
        layer = fs.get(key) or {}
        sc = layer.get("score", 0)
        sc_color = "#1ba784" if sc >= 65 else ("#e23c3c" if sc < 40 else "#8a8a8a")
        l_stars = "★" * layer.get("stars", 0) + "☆" * (5 - layer.get("stars", 0))
        layer_rows += f"<tr><td>{label}</td><td style='color:{sc_color};font-weight:700'>{sc}</td><td>{l_stars}</td><td style='font-size:12px;color:#888'>{layer.get('detail','')}</td></tr>"

    # ETF top inflow/outflow
    ti = etf_sum.get("top_inflow") or []
    to_ = etf_sum.get("top_outflow") or []
    etf_rows = ""
    max_len = max(len(ti), len(to_))
    for i in range(min(max_len, 5)):
        left = ti[i] if i < len(ti) else {}
        right = to_[i] if i < len(to_) else {}
        l_name = left.get("name", "")[:12] if left else ""
        l_code = left.get("code", "") if left else ""
        l_amt = f"{left.get('amount',0)/1e8:.1f}亿" if left and left.get("amount") else ""
        r_name = right.get("name", "")[:12] if right else ""
        r_code = right.get("code", "") if right else ""
        r_amt = f"{right.get('amount',0)/1e8:.1f}亿" if right and right.get("amount") else ""
        etf_rows += f"<tr><td style='color:#1ba784'>{l_code} {l_name}</td><td>{l_amt}</td><td style='color:#e23c3c'>{r_code} {r_name}</td><td>{r_amt}</td></tr>"

    # Commodity key items
    comm_items = []
    for cat_key in ("energy", "precious", "industrial", "agriculture"):
        for item in (comm.get(cat_key) or []):
            comm_items.append(item)
    comm_rows = ""
    for item in comm_items[:8]:
        chg = item.get("change_pct", 0)
        c_color = "#e23c3c" if chg > 0 else "#1ba784"
        comm_rows += f"<tr><td>{item.get('name_cn','')}</td><td style='color:{c_color}'>{chg:+.2f}%</td><td style='font-size:11px;color:#888'>{item.get('a_share_link','')}</td></tr>"

    # Institution
    hsgt = inst.get("hsgt") or {}
    south = hsgt.get("south_net", 0)
    north = hsgt.get("north_net", 0)
    inst_html = ""
    if south or north:
        s_color = "#e23c3c" if south > 0 else "#1ba784"
        n_color = "#e23c3c" if north > 0 else "#1ba784"
        inst_html = f"<span style='margin-right:20px'>南向 <b style='color:{s_color}'>{south:.0f}亿</b></span><span>北向 <b style='color:{n_color}'>{north:.0f}亿</b></span>"

    gaps = fr.get("gaps") or []
    gaps_str = ", ".join(gaps) if gaps else "无"

    return f"""
  <div style='margin:18px 0;background:#fff;border:1px solid #e5e7eb;border-radius:12px;overflow:hidden'>
    <div style='background:linear-gradient(135deg,#0d47a1,#1565c0);color:#fff;padding:14px 20px;display:flex;align-items:center;justify-content:space-between'>
      <div><span style='font-size:16px;font-weight:700'>资金情报中心</span>
      <span style='font-size:12px;opacity:.8;margin-left:8px'>Capital Flow Intelligence</span></div>
      <div style='text-align:right'>
        <span style='font-size:28px;font-weight:800'>{overall}</span><span style='font-size:14px;opacity:.7'>/100</span>
        <span style='font-size:16px;margin-left:8px;color:#ffd700'>{star_str}</span>
      </div>
    </div>
    <div style='padding:16px 20px'>
      <div style='font-size:14px;color:#333;margin-bottom:12px;padding:8px 12px;background:#f0f7ff;border-radius:8px'>
        {intel.get('one_liner', '')}
      </div>

      <div style='display:flex;gap:20px;margin-bottom:16px'>
        <table style='flex:1;border-collapse:collapse;font-size:13px'>
          <tr style='background:#f5f5f5'><th style='padding:6px 8px;text-align:left'>层级</th><th>评分</th><th>星级</th><th style='font-size:11px'>详情</th></tr>
          {layer_rows}
        </table>
        <table style='flex:1;border-collapse:collapse;font-size:12px'>
          <tr style='background:#f5f5f5'><th style='padding:6px 8px;text-align:left'>净流入TOP</th><th>成交</th><th style='text-align:left'>净流出TOP</th><th>成交</th></tr>
          {etf_rows}
        </table>
      </div>

      <div style='display:flex;gap:20px'>
        <div style='flex:1'>
          <div style='font-size:13px;font-weight:600;color:#1565c0;margin-bottom:6px'>商品行情</div>
          <table style='width:100%;border-collapse:collapse;font-size:12px'>
            <tr style='background:#f5f5f5'><th style='padding:4px 8px;text-align:left'>品种</th><th>涨跌</th><th>A股关联</th></tr>
            {comm_rows}
          </table>
        </div>
        <div style='flex:1'>
          <div style='font-size:13px;font-weight:600;color:#1565c0;margin-bottom:6px'>机构资金</div>
          <div style='font-size:13px;padding:4px 0'>{inst_html or '<span style="color:#999">暂无数据</span>'}</div>
          <div style='font-size:12px;color:#666;margin-top:8px'><b>五问摘要</b></div>
          <div style='font-size:11px;color:#555;line-height:1.6;margin-top:4px'>
            <b>Q1全球:</b> {(intel.get("q1_global","")[:80] + "...") if len(intel.get("q1_global","")) > 80 else intel.get("q1_global","")}<br>
            <b>Q3 ETF:</b> {(intel.get("q3_etf","")[:80] + "...") if len(intel.get("q3_etf","")) > 80 else intel.get("q3_etf","")}<br>
            <b>Q5 A股:</b> {(intel.get("q5_a_share","")[:80] + "...") if len(intel.get("q5_a_share","")) > 80 else intel.get("q5_a_share","")}
          </div>
        </div>
      </div>

      <div style='font-size:11px;color:#e65100;margin-top:10px'>数据缺口: {gaps_str}</div>
    </div>
  </div>"""


def _render_memo(memo):
    """渲染CIO七段投资决策备忘录（HTML）。"""
    if not memo:
        return ""

    t = memo.thesis
    e = memo.evidence
    mm = memo.money_map
    ml = memo.main_lines
    tp = memo.trading_plan
    r = memo.risk
    h = memo.historical

    def _s(n):
        return "★" * n + "☆" * (5 - n)

    # ① 核心观点
    thesis_html = f"""<div class='cio-thesis'>
      <div class='cio-gold'>💡 {t.headline}</div>
      {"<div class='cio-conviction'>确信度：" + t.conviction + "</div>" if t.conviction else ""}
      <div class='cio-explain'>{t.explanation}</div>
      {"<div class='cio-global-link'>" + t.global_a_share_link + "</div>" if t.global_a_share_link else ""}
    </div>"""

    # ② 证据链
    claim_items = ""
    for c in e.claims[:4]:
        claim_items += (
            f"<div class='cio-claim'>"
            f"<span class='cio-claim-type {'verified' if c['type'] == '数据支持' else 'inferred'}'>[{c['type']}]</span> "
            f"<span class='cio-claim-text'>{c['claim']}</span>"
            f"<div class='cio-claim-evidence'>→ {c['evidence']}</div>"
            f"</div>"
        )
    uncert_html = ""
    if e.cross_layer_conflicts:
        cf_items = "".join(f"<li class='cio-conflict-item'>{cf}</li>" for cf in e.cross_layer_conflicts[:2])
        uncert_html += f"<div class='cio-uncertain'><strong>跨层矛盾</strong><ul>{cf_items}</ul></div>"
    if e.uncertainty:
        uncert_html += f"<div class='cio-uncertain'><strong>不确定</strong><ul><li>{e.uncertainty[0]}</li></ul></div>"

    evidence_html = f"""<div class='cio-evidence'>
      <div class='cio-section-title'>② 证据链 · Evidence Chain</div>
      {claim_items}
      {uncert_html}
    </div>"""

    # ③ 资金地图
    td_rows = ""
    for td in mm.time_dimension[:5]:
        sig = " ⚡拐点" if td.get("inflection") else ""
        td_rows += f"<tr><td>{td['sector']}</td><td>{td.get('net_today',''):+.1f}亿</td><td>{td.get('net_5d',''):+.0f}亿</td><td>{td['trend_5d']}{sig}</td><td>{td.get('trend_20d','')}</td></tr>"
    if_sigs = "".join(f"<li>{s}</li>" for s in mm.inflection_signals[:3]) if mm.inflection_signals else ""

    money_html = f"""<div class='cio-money'>
      <div class='cio-section-title'>③ 资金地图 · Money Map</div>
      <div class='cio-pattern'>模式：<strong>{mm.pattern}</strong> — {mm.pattern_explanation}</div>
      <div class='cio-migration'>{mm.migration_narrative}</div>
      <table class='cio-tbl'>
        <tr><th>板块</th><th>今日净流入</th><th>5日累计</th><th>趋势</th><th>20日</th></tr>
        {td_rows}
      </table>
      {f"<ul class='cio-inflection'>{if_sigs}</ul>" if if_sigs else ""}
    </div>"""

    # ④ 投资主线
    ml_rows = ""
    for m in ml[:6]:
        chain = f" ({m.chain_position})" if m.chain_position else ""
        inflection = " ⚡拐点" if m.inflection else ""
        ml_rows += (f"<tr><td class='cio-stars'>{_s(m.star_rating)}</td>"
                    f"<td class='cio-sector'>{m.sector}</td>"
                    f"<td>{m.stage}</td>"
                    f"<td>{m.persistence}{inflection}</td>"
                    f"<td class='cio-chain'>{chain}</td></tr>")
    conf_bars = ""
    if memo.confidence_bars:
        bars = []
        for layer, score in sorted(memo.confidence_bars.items()):
            bar_width = score
            bars.append(f"<div class='cio-bar-row'><span class='cio-bar-label'>{layer}</span><div class='cio-bar-track'><div class='cio-bar-fill' style='width:{min(bar_width,100)}%'></div></div><span class='cio-bar-val'>{score}</span></div>")
        conf_bars = "<div class='cio-bars'>" + "".join(bars) + "</div>"

    mainlines_html = f"""<div class='cio-mainlines'>
      <div class='cio-section-title'>④ 投资主线 · Main Lines</div>
      <table class='cio-tbl'>
        <tr><th>评级</th><th>板块</th><th>阶段</th><th>持续性</th><th>产业链</th></tr>
        {ml_rows}
      </table>
      {conf_bars}
    </div>"""

    # ⑤ 交易计划
    if tp.no_opportunity:
        tp_html = f"""<div class='cio-trading'>
          <div class='cio-section-title'>⑤ 交易计划 · Trading Plan</div>
          <div class='cio-no-opp'>🚫 今日无交易机会</div>
          <div class='cio-no-opp-reason'>{tp.no_opportunity_reason}</div>
        </div>"""
    else:
        op_items = ""
        emojis = {"A": "🔥", "B": "📋", "C": "⚡"}
        for op in tp.opportunities[:4]:
            em = emojis.get(op["tier"], "")
            conds = "｜".join(op["conditions"][:2])
            giveup = "｜".join(op["give_up"][:2])
            rationale = op.get("rationale", "")
            op_items += (
                f"<div class='cio-opp-card cio-tier-{op['tier']}'>"
                f"<div class='cio-opp-tier'>{em} {op['tier']}级机会：<strong>{op['name']}</strong></div>"
                f"<div class='cio-opp-cond'>✅ 条件：{conds}</div>"
                f"<div class='cio-opp-giveup'>❌ 放弃：{giveup}</div>"
                f"{'<div class=cio-opp-rationale>💡 ' + rationale + '</div>' if rationale else ''}"
                f"</div>"
            )
        tp_html = f"""<div class='cio-trading'>
          <div class='cio-section-title'>⑤ 交易计划 · Trading Plan</div>
          {op_items}
        </div>"""

    # ⑥ 风险与反例
    fals_items = ""
    for f in r.falsification[:4]:
        fals_items += (
            f"<div class='cio-fals'>"
            f"<strong>如果</strong>「{f['if_condition']}」<br>"
            f"<strong>→</strong> {f['then_conclusion']}"
            f"</div>"
        )
    events_str = ""
    high_cats = [c for c in r.upcoming_events if c.get("impact") == "high"]
    if high_cats:
        cat_strs = [f"{c['date']}({c['days_until']}天后) {c['name']}" for c in high_cats[:3]]
        events_str = f"<div class='cio-events'>📅 关键事件：{'、'.join(cat_strs)}</div>"

    risk_html = f"""<div class='cio-risk'>
      <div class='cio-section-title'>⑥ 风险与反例 · Risk & Counter</div>
      <div class='cio-big-risk'>{r.biggest_risk}</div>
      <div class='cio-fals-grid'>{fals_items}</div>
      {events_str}
    </div>"""

    # ⑦ 历史经验
    hist_html = f"""<div class='cio-historical'>
      <div class='cio-section-title'>⑦ 历史经验 · Historical Context</div>
      <div class='cio-hist-conclusion'>{h.conclusion}</div>
      {f"<div class='cio-hist-stats'>回测胜率：<strong>{h.win_rate:.0f}%</strong>（{h.sample_count}个交易日）</div>" if h.backtest_available and h.win_rate is not None else ""}
    </div>"""

    return f"""<div class='cio-memo'>
  <div class='cio-header'>
    <div class='cio-title'>📊 投资决策备忘录 · Investment Decision Memo</div>
    <div class='cio-date'>{memo.trade_date} | 决策 <span class='cio-dec cio-dec-{memo.can_buy}'>{memo.can_buy}</span> | 置信度 {memo.confidence_overall}%</div>
  </div>
  {thesis_html}
  {evidence_html}
  {money_html}
  {mainlines_html}
  {tp_html}
  {risk_html}
  {hist_html}
  <div class='cio-footer'>CIO Agent · 仅供研究不构成投资建议 · {memo.generated_at[:16]}</div>
</div>"""


def render_html(report, path):
    gen = report.get("generated_at", "")
    date = report.get("trade_date", "")
    l0 = report.get("L0", {})
    dec = report.get("decision", {})
    conf = report.get("confidence", {})
    conflicts = report.get("conflicts", [])
    chain = report.get("chain", [])
    results = report.get("results", {})
    feedback = report.get("learning_feedback", {}) or {}

    cb = dec.get("can_buy", "CAUTION")
    cb_color, cb_text = CANBUY.get(cb, CANBUY["CAUTION"])
    conf_overall = conf.get("overall", 0)
    reasons = "".join(f"<li>{r}</li>" for r in dec.get("reasons", []))
    hard = dec.get("hard_no") or []
    hard_html = "".join(f"<span class='hard'>{h}</span>" for h in hard) if hard else ""

    l0_head = l0.get("headline", "")
    l0_body = l0.get("body", "")

    # ── 全球跨资产叙事引擎 ──
    gn = l0.get("global_narrative") or {}
    narrative_html = _render_narrative(gn) if gn else ""

    # ── 资金情报中心（Capital Flow Engine）──
    flow_html = _render_flow(results)

    # ── CIO 投资决策备忘录（七段）──
    memo_html = ""
    try:
        # CIO memo 由 orchestrator 嵌入 brain_report.json，
        # 这里直接调用 produce_cio() 读取磁盘（零额外计算）
        from brain.cio_agent import produce as produce_cio
        memo = produce_cio()
        memo_html = _render_memo(memo)
    except Exception:
        pass

    conflict_html = ""
    if conflicts:
        items = ""
        for cf in conflicts:
            sev = cf.get("severity")
            cls = "cf-high" if sev == "HIGH" else ("cf-med" if sev == "MEDIUM" else "cf-low")
            items += (f"<div class='cf {cls}'><b>[{sev}] {cf.get('rule', '')}</b> · "
                      f"{cf.get('desc', '')}</div>")
        conflict_html = (f"<div class='cf-box'><div class='cf-title'>⚠ 跨层冲突检测"
                         f"（{len(conflicts)} 处）</div>{items}</div>")

    # 学习反哺区（Learning OS ──▶ Decision OS）
    applied = feedback.get("applied")
    lf_notes = "".join(f"<div class='lf-note'>· {n}</div>" for n in feedback.get("notes", []))
    if applied:
        lf_head = (f"🔄 学习反哺已生效（{feedback.get('count', 0)} 笔样本 · "
                   f"整体胜率 {feedback.get('win_rate')}% · 置信度净调整 "
                   f"{feedback.get('conf_delta', 0):+.1f} · 仓位缩放 ×{feedback.get('pos_scale', 1)}）")
        lf_cls = "lf-box"
    else:
        lf_head = f"🔄 学习反哺（{feedback.get('status', '待录入')}）"
        lf_cls = "lf-box pending"
    lf_html = f"<div class='{lf_cls}'><div class='lf-title'>{lf_head}</div>{lf_notes}</div>"

    nodes = ""
    for layer in chain:
        r = results.get(layer)
        if not r:
            continue
        if layer == "L0":
            nodes += f"""<div class='node'>
              <div class='l0-card'>
                <div class='l0-tag'>L0 · 市场叙事（总指挥定调）</div>
                <div class='l0-head'>{l0_head}</div>
                <div class='l0-body'>{l0_body}</div>
              </div>
            </div>"""
            continue
        if layer == "FLOW":
            continue  # 已有专属资金情报板块
        d = r.get("signal", {}).get("direction", "neutral")
        dcolor = DIR_COLOR.get(d, "#8a8a8a")
        dlabel = DIR_LABEL.get(d, "中性")
        conf_c = _conf_color(r.get("confidence"))
        upstream = r.get("upstream", "")
        risk = r.get("risk_note", "")
        risk_html = f"<div class='risk'>⚠ 该层风险：{risk}</div>" if risk else ""
        up_html = f"<div class='up'>↑ 输入：{upstream}</div>" if upstream else ""
        nodes += f"""<div class='node'>
          <div class='card'>
            <div class='card-h'>
              <span class='layer'>{r.get('layer', '')}</span>
              <span class='title'>{r.get('title', '')}</span>
              <span class='dir' style='background:{dcolor}'>{dlabel}</span>
              <span class='conf' style='color:{conf_c}'>置信 {r.get('confidence')}</span>
            </div>
            {up_html}
            <div class='out'>{r.get('output', '')}</div>
            {risk_html}
          </div>
        </div>"""

    html = f"""<!doctype html><html lang=zh><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>每日决策简报 · {date}</title><style>{CSS}</style></head>
<body><div class='wrap'>
  <div class='hd'>
    <h1>每日决策简报<span class='sub'>Decision OS · 推理链总指挥</span></h1>
    <div class='meta'>交易日 <b>{date}</b> · 生成 {gen}</div>
  </div>

  <div class='l0-band'>
    <div class='l0-head'>{l0_head}</div>
    <div class='l0-body'>{l0_body}</div>
  </div>

  {narrative_html}

  {flow_html}

  {memo_html}

  <div class='decision'>
    <div class='dec-left'>
      <div class='cb' style='background:{cb_color}'>{cb_text}</div>
      <div class='gauge'>
        <div class='g-num' style='color:{_conf_color(conf_overall)}'>{conf_overall}</div>
        <div class='g-lab'>总置信度</div>
        <div class='g-bar'><i style='width:{conf_overall}%;background:{_conf_color(conf_overall)}'></i></div>
      </div>
    </div>
    <div class='dec-right'>
      <div class='pos'>仓位护栏：<b>{dec.get('position_pct', '')}</b>{hard_html}</div>
      <div class='why'>决策依据</div>
      <ul class='reasons'>{reasons}</ul>
      <div class='vote'>方向投票：偏多 {dec.get('bull', 0)} · 偏空 {dec.get('bear', 0)}　|　冲突惩罚 ×{conf.get('penalty', 1)}{("　|　学习净调整 " + format(conf.get('learning_delta'), '+.1f')) if conf.get('learning_delta') else ""}</div>
    </div>
  </div>

  {conflict_html}

  {lf_html}

  <div class='sec-title'>推理链（L0 定调 → L1…L8 串联）</div>
  <div class='timeline'>{nodes}</div>

  <div class='footer'>系统只做「定方向 + 验证 + 决策建议」，价格行为/图形/个股硬过滤由你人工定。红线：不替你下单。</div>
</div></body></html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path
