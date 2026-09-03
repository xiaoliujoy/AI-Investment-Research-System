# -*- coding: utf-8 -*-
"""P1-A.1b：daily-os E2E 测试（pytest 原生）。

依赖 daily-os/conftest.py 的 `app_server` fixture 提供隔离服务与临时 daily_os.db。
本测试只验证「本地每日记录」链路：午间 -> 交易 -> 晚间复盘评分 -> 当日汇总 -> 趋势序列。
所有写入都落在 fixture 重定向的临时库，绝不触碰真实 daily_os.db。
"""
import json
import urllib.request
import pytest
import app as A

DATE = "2026-08-13"


def _post(base, path, body):
    req = urllib.request.Request(base + path,
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def _get(base, path):
    with urllib.request.urlopen(base + path, timeout=5) as r:
        return json.loads(r.read())


def test_e2e(app_server):
    base = app_server["base"]

    # 1) 午间记录
    noon = _post(base, "/api/noon", {"date": DATE, "state": "丰盛", "note": "观想圆满"})
    assert noon == {"ok": True}, noon

    # 2) 交易记录（追加一条 session）
    trade = _post(base, "/api/trade", {"date": DATE, "session": {
        "env": "震荡", "dir": "多", "has_chance": "是", "accept_no": "能",
        "plan": True, "chase": False, "early": False, "loss": False, "note": "按计划入场"}})
    assert trade.get("ok") is True and trade.get("count") == 1, trade

    # 3) 晚间复盘 + 评分
    evening = _post(base, "/api/evening", {"date": DATE,
        "evening_data": {"closest": "开盘前冥想", "taken": "尾盘追价", "error": "无",
                          "review": {"plan": True, "entry": True, "stop": True, "early": False, "miss": False},
                          "growth": {"learn": "先写计划再开仓", "good": "没有冲动交易", "next": "明天所有交易先写计划"}},
        "score_inner": 4, "score_abundance": 5, "score_discipline": 4,
        "score_awareness": 4, "score_joy": 5, "belief_fulfillment": 4})
    assert evening == {"ok": True}, evening

    # 4) 当日汇总：评分映射应与 compute_scores 一致
    #    dss = mean(4,5,4,4,5) = 4.4; presence = (4+4)/2 = 4.0
    #    discipline_idx = (4+4)/2 = 4.0; joy_idx = (5+5)/2 = 5.0
    t = _get(base, "/api/today?date=" + DATE)
    assert t.get("noon_state") == "丰盛", t.get("noon_state")
    assert t.get("daily_state_score") == 4.4, t.get("daily_state_score")
    assert t.get("presence") == 4.0, t.get("presence")
    assert t.get("discipline_idx") == 4.0, t.get("discipline_idx")
    assert t.get("joy_idx") == 5.0, t.get("joy_idx")
    assert t.get("belief_fulfillment") == 4, t.get("belief_fulfillment")

    # 5) 趋势序列：至少包含本日期，且分数一致
    tr = _get(base, "/api/trend?days=30")
    assert isinstance(tr, list) and len(tr) >= 1, len(tr)
    assert tr[0]["daily_state_score"] == 4.4, tr[0]
    assert tr[0].get("discipline_idx") == 4.0, tr[0]
