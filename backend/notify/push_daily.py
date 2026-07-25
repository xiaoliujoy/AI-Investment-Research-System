# -*- coding: utf-8 -*-
"""推送每日投资决策备忘录到 微信公众号（唯一对外渠道）。

2026-07-17 起：企微 / 飞书 / Server酱 已取消，仅保留微信公众号(mp)。
HTML 本地备忘录由 notify/os2_report.py 生成（Trading OS 2.0 压缩版）。

用法：
  python notify/push_daily.py                # CIO Agent 输出 → 所有已配置渠道
  python notify/push_daily.py --dry-run      # 只构建消息体，不真正发送

配置（backend/.env 或环境变量）：
  WECHAT_WEBHOOK_URL   企业微信机器人 webhook
  FEISHU_WEBHOOK_URL / FEISHU_SECRET   飞书机器人 webhook(+签名)
  SERVERCHAN_SENDKEY   Server酱 sendkey（微信推送）
  MP_APPID / MP_APPSECRET / MP_AUTHOR_NAME   公众号
"""
import os
import sys
import json
import argparse
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "output")
sys.path.insert(0, ROOT)

from notify import config
from notify.research_memo import write_memo_html  # 仅作 OS2 写出失败时的回退
from notify.os2_report import write as write_os2, write_wechat, render_push  # Trading OS 2.0 压缩版日报 + 公众号内联版 + 推送文本
from brain.cio_agent import produce  # CIO memo 由 orchestrator 嵌入 brain_report，这里直接读取


def push_all(memo, dry_run=False):
    results = {}
    enabled = config.channel_enabled()
    if not enabled:
        results["_note"] = "未配置任何推送渠道（在 backend/.env 填入 WECHAT_WEBHOOK_URL / FEISHU_WEBHOOK_URL / SERVERCHAN_SENDKEY 等）"
        return True, results

    # 仅微信公众号（mp）对外发布；企微/飞书/Server酱 已于 2026-07-17 取消。
    for ch in enabled:
        try:
            if ch == "mp":
                if dry_run:
                    results[ch] = {"ok": True, "dry": True,
                                   "article_title": f"每日研投看板 {memo.trade_date}"}
                    continue
                from notify.mp import push_memo
                ok, info = push_memo(memo, config.get("MP_APPID"), config.get("MP_APPSECRET"),
                                     author=config.get("MP_AUTHOR_NAME", ""))
                results[ch] = {"ok": ok, "info": info}
            else:
                results[ch] = {"ok": False, "error": f"未启用渠道: {ch}"}
        except Exception as e:
            results[ch] = {"ok": False, "error": repr(e)[:200]}

    overall = all(r.get("ok", False) for r in results.values() if isinstance(r, dict))
    return overall, results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只构建消息体，不真正发送")
    args = ap.parse_args()

    print("CIO Agent 正在生成投资决策备忘录...")
    memo = produce()

    # 始终写出本地 HTML 备忘录（Trading OS 2.0 压缩版；对外发布仅微信公众号）
    html_path = os.path.join(OUT, f"memo_{memo.trade_date}.html")
    try:
        write_os2(memo, html_path)
        print(f"本地 HTML 备忘录（Trading OS 2.0）已写出：{html_path}")
    except Exception as ex:
        print(f"⚠️ OS2 备忘录写出失败，回退旧版：{ex}")
        try:
            write_memo_html(memo, html_path)
        except Exception as ex2:
            print(f"⚠️ 旧版备忘录写出也失败：{ex2}")

    # 同时写出公众号内联版（与发布内容一致，可手动粘贴到公众号编辑器兜底）
    try:
        wx_path = os.path.join(OUT, f"memo_{memo.trade_date}_wechat.html")
        write_wechat(memo, wx_path)
        print(f"公众号内联版已写出：{wx_path}")
    except Exception as e:
        print(f"⚠️ 公众号内联版写出失败（不影响本地备忘录）：{e}")

    if args.dry_run:
        print("\n=== 压缩版推送文本（公众号预览）===\n")
        print(render_push(memo))
        from notify.os2_report import compute_weighted_score, resolve_decision, compute_executive_summary
        _sc = compute_weighted_score(memo)
        _decision = resolve_decision(memo, _sc)
        _es = compute_executive_summary(memo, _sc, _decision)
        print(f"\nOS2 裁决: {_sc['verdict']}（{_sc['decision']}） 综合分 {_sc['composite']}/100  权重来源: {_sc['weight_src']}")
        print(f"IC 原裁决: {memo.can_buy}  置信度: {memo.confidence_overall}%  （与 OS2 一致={_sc['ic_agree']}）")
        print(f"市场状态: {_es['market_state']}  仓位护栏: {_es['position']}")
        print(f"核心观点: {memo.thesis.headline[:120]}")
        print(f"交易机会: {'无' if memo.trading_plan.no_opportunity else len(memo.trading_plan.opportunities)}个")
        return

    overall, results = push_all(memo)
    log = {"at": datetime.datetime.now().isoformat(timespec="seconds"),
           "trade_date": memo.trade_date,
           "can_buy": memo.can_buy,
           "confidence": memo.confidence_overall,
           "dry_run": False,
           "enabled": config.channel_enabled(),
           "overall_ok": overall, "results": results}
    with open(os.path.join(OUT, "push_daily.log.json"), "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2, default=str)
    print(json.dumps({"enabled": log["enabled"], "overall_ok": overall, "results": {
        k: ({"ok": v.get("ok"), "note": str(v.get("resp", "") or v.get("info", ""))[:80]}
            if isinstance(v, dict) else v) for k, v in results.items()}}, ensure_ascii=False, indent=2))
    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    main()
