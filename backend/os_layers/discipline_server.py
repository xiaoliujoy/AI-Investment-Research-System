#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Trading Discipline Engine —— 轻量入口本地服务器（零依赖，仅标准库）

把「计划交易，交易计划」做成浏览器里最轻的录入界面：
  盘前计划 Plan → 盘中三问 Trade → 盘后复盘 Review → 我的数据 Dashboard

设计原则（对齐架构冻结 §1.1 / §11）：
  - 只记录、不预测、不诊断、不产买卖建议。
  - 录入 ≤60 秒：结构化小表单，回车即存。
  - 心理/反思字段原样保存，AI 不做任何分析。

启动（一次命令）：
  python backend/os_layers/discipline_server.py
浏览器打开 http://127.0.0.1:8777

说明：本服务仅监听本机回环地址，无鉴权，仅作个人本地录入工具。
若需手机访问，请用 --host 0.0.0.0 并在可信局域网内运行（数据含交易心理档案）。
"""
import argparse
import importlib.util
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
HTML_PATH = os.path.join(HERE, "discipline_ui.html")
COACH_HTML_PATH = os.path.join(HERE, "trading_coach_v02.html")
CSV_PATH = os.path.join(PROJECT_ROOT, "mt5_raw", "trade_path.csv")
EI_PATH = os.path.join(PROJECT_ROOT, "mt5_raw", "execution_intelligence.json")

# 装载引擎
spec = importlib.util.spec_from_file_location(
    "trading_discipline_engine", os.path.join(HERE, "trading_discipline_engine.py"))
ENG = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ENG)
ENG.init()

# 装载交易宪法引擎（事前闸门）
# trading_constitution.py 含个人化交易参数，不随仓库分发。
# 缺失时闸门降级为放行，Plan/Trade/Review 其余功能不受影响。
try:
    import trading_constitution as TC
except ImportError:  # pragma: no cover - 仓库未包含该私有模块
    TC = None

# 装载交易状态机（Trading State Machine v1.0 + 盈利保护）
# 状态层硬闸门：状态直接 gate 开仓，是「两个交易者」洞察的工程化卡点。
try:
    _tsm_spec = importlib.util.spec_from_file_location(
        "trading_state_machine", os.path.join(HERE, "trading_state_machine.py"))
    TSM = importlib.util.module_from_spec(_tsm_spec)
    _tsm_spec.loader.exec_module(TSM)
except Exception:  # pragma: no cover
    TSM = None

_NO_TC = {"decision": "ALLOW", "violations": [], "warnings": [],
          "note": "trading_constitution 未配置，事前闸门已跳过"}

# 会话（状态机的运行时载体，持久化到 mt5_raw/trading_session.json）
SESSION = TSM.load_session() if TSM else None


def _gate(proposal):
    """合并交易宪法闸门 + 交易状态机状态检查。

    - TC 缺失 → 仅状态检查；
    - TSM 缺失 → 仅宪法检查；
    - 两者都在 → merge_gate 合并，任一 BLOCK 即拒绝。
    私有模块缺失时降级为放行，不阻断录入。
    """
    const = TC.pre_trade_gate(proposal) if TC else dict(_NO_TC)
    if TSM is None or SESSION is None:
        return const
    state_res = TSM.pre_trade_check(proposal, SESSION)
    return TSM.merge_gate(const, state_res)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj=None, text=None, ctype="application/json"):
        self.send_response(code)
        if text is not None:
            body = text.encode("utf-8")
            self.send_header("Content-Type", "text/html; charset=utf-8")
        else:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            if os.path.exists(HTML_PATH):
                with open(HTML_PATH, encoding="utf-8") as f:
                    self._send(200, text=f.read())
            else:
                self._send(404, text="<h1>discipline_ui.html 未找到</h1>")
            return
        if path == "/api/today":
            self._send(200, ENG.get_today_plan() or {})
            return
        if path == "/api/history":
            self._send(200, ENG.get_history())
            return
        if path == "/api/status":
            out = {"belief": None, "abcd": None, "history": ENG.get_history(), "ei": None}
            if os.path.exists(CSV_PATH):
                try:
                    out["belief"] = ENG.belief_fulfillment_rate(CSV_PATH)
                    out["abcd"] = ENG.abcd_analysis(CSV_PATH)
                except Exception as e:  # noqa
                    out["belief_error"] = str(e)
            if os.path.exists(EI_PATH):
                try:
                    with open(EI_PATH, encoding="utf-8") as f:
                        out["ei"] = json.load(f)
                except Exception as e:  # noqa
                    out["ei_error"] = str(e)
            # 交易逻辑放弃率（Belief Execution Engine 核心指标）
            try:
                out["tar"] = ENG.thesis_abandonment_rate()
            except Exception as e:  # noqa
                out["tar_error"] = str(e)
            self._send(200, out)
            return
        if path == "/api/constitution":
            if TC is None:
                self._send(200, {"version": None, "text": "",
                                 "note": _NO_TC["note"]})
                return
            self._send(200, {"version": TC.CONSTITUTION_VERSION,
                             "text": TC.CONSTITUTION_TEXT})
            return
        if path == "/api/session":
            # 交易状态机快照：当前状态 / 当日盈亏 / 峰值 / 泄漏率 / 执行分 / 危险事件
            if TSM is None or SESSION is None:
                self._send(200, {"available": False,
                                 "note": "trading_state_machine 未加载"})
                return
            out = TSM.snapshot(SESSION)
            out["available"] = True
            out["state_machine_version"] = TSM.VERSION
            self._send(200, out)
            return
        if path in ("/coach", "/coach/"):
            # Trading Coach v0.2 状态机仪表盘（独立页面，不改动原 discipline_ui）
            if os.path.exists(COACH_HTML_PATH):
                with open(COACH_HTML_PATH, encoding="utf-8") as f:
                    self._send(200, text=f.read())
            else:
                self._send(404, text="<h1>trading_coach_v02.html 未找到</h1>")
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            data = {}
        path = self.path.split("?")[0]

        try:
            if path == "/api/gate":
                # 纯校验，不落库：返回 ALLOW/BLOCK/WARN + 触发的宪法条款 + 证据
                # 合并交易宪法 + 交易状态机（盈利保护 / 危险触发）
                proposal = {
                    "market_type": data.get("market", ""),
                    "symbol": data.get("symbol", ""),
                    "direction": data.get("direction", ""),
                    "why_now": data.get("why_now", ""),
                    "regime_support": data.get("regime_support", ""),
                    "invalid_condition": data.get("invalid", ""),
                    "planned_hold_min": data.get("planned_hold_min"),
                    "willing_hold_4h": data.get("hold4h"),
                    "planned_exit": data.get("exit", ""),
                    "risk_plan": data.get("risk", ""),
                    "entry_stage": data.get("entry_stage", ""),
                    "fomo_self_check": data.get("fomo_self_check", ""),
                    "cycle_aligned": data.get("cycle_aligned", ""),
                    "lot": data.get("lot"),
                    "stop_loss": data.get("stop_loss"),
                    "has_plan": data.get("has_plan", False),
                    "quick": data.get("quick", False),
                }
                self._send(200, _gate(proposal))
                return

            elif path == "/api/plan":
                # 录入前先过交易宪法闸门；BLOCK 级违规拒绝记录，并回写 constitution_check
                proposal = {
                    "market_type": data.get("market", "MT5"),
                    "symbol": data.get("symbol", ""),
                    "direction": data.get("direction", ""),
                    "why_now": data.get("why_now", ""),
                    "regime_support": data.get("regime_support", ""),
                    "invalid_condition": data.get("invalid", ""),
                    "planned_hold_min": data.get("planned_hold_min"),
                    "willing_hold_4h": data.get("hold4h"),
                    "planned_exit": data.get("exit", ""),
                    "risk_plan": data.get("risk", ""),
                    "entry_stage": data.get("entry_stage", ""),
                    "fomo_self_check": data.get("fomo_self_check", ""),
                    "cycle_aligned": data.get("cycle_aligned", ""),
                    "quick": data.get("quick", False),
                }
                gate = _gate(proposal)
                if gate["decision"] == "BLOCK":
                    self._send(200, {"ok": False, "blocked": True, "gate": gate,
                                     "msg": "违反交易宪法或交易状态机，计划未记录。见 violations。"})
                    return
                tid = ENG.record_plan(
                    proposal["market_type"],
                    proposal["symbol"],
                    proposal["direction"],
                    data.get("hypothesis", ""),
                    proposal["invalid_condition"],
                    proposal["risk_plan"],
                    data.get("signal", ""),
                    data.get("scenario", ""),
                    data.get("hold4h", ""),
                    proposal["planned_exit"],
                    why_now=proposal["why_now"],
                    regime_support=proposal["regime_support"],
                    planned_hold_min=proposal["planned_hold_min"],
                    entry_stage=data.get("entry_stage", ""),
                    fomo_self_check=data.get("fomo_self_check", ""),
                    cycle_aligned=data.get("cycle_aligned", ""),
                    planned_attribution=data.get("planned_attribution", ""),
                )
                ENG.record_constitution_check(tid, gate)
                # 状态机：记录一份确认型计划 → OBSERVE 升 NORMAL（出现交易机会）
                if TSM is not None and SESSION is not None:
                    TSM.mark_planned(SESSION)
                    TSM.save_session(SESSION)
                self._send(200, {"ok": True, "id": tid, "gate": gate,
                                "state": SESSION.state if SESSION else None})

            elif path == "/api/trade":
                ENG.record_checkin(
                    data.get("tid"),
                    data.get("q1", "n"),
                    data.get("q1_note", ""),
                    data.get("q2", ""),
                    data.get("q3", ""),
                    data.get("note", ""),
                )
                self._send(200, {"ok": True})

            elif path == "/api/review":
                ENG.record_review(
                    data.get("tid"),
                    int(data.get("dq", 0)),
                    int(data.get("eq", 0)),
                    int(data.get("em", 0)),
                    data.get("judgment", "y"),
                    data.get("execution", "y"),
                    data.get("fear", ""),
                    data.get("improve", ""),
                    data.get("deviation", "none"),
                    data.get("close_reason", ""),
                )
                self._send(200, {"ok": True})

            elif path == "/api/reflect":
                rid = ENG.record_reflection(
                    data.get("date", ""),
                    data.get("title", ""),
                    data.get("category", "insight"),
                    data.get("body", ""),
                    data.get("tags", ""),
                )
                self._send(200, {"ok": True, "id": rid})

            elif path == "/api/session/update":
                # 交易状态机会话更新（手动驱动，因 MT5 无实时连接）
                # action:
                #   start  —— 重置当日会话（清零盈亏/计数，回 OBSERVE）
                #   pnl    —— 绝对校准：把当日盈亏设为 daily_pnl（非累加，避免双计）
                #   trade  —— 累加登记一笔已平仓结果（驱动 PROFIT/DAMAGED/DANGER）
                if TSM is None or SESSION is None:
                    self._send(200, {"ok": False, "note": "trading_state_machine 未加载"})
                    return
                action = (data.get("action") or "").strip().lower()
                if action == "start":
                    TSM.start_session(SESSION)
                    TSM.save_session(SESSION)
                    self._send(200, {"ok": True, "state": SESSION.state})
                    return
                if action == "pnl":
                    val = float(data.get("daily_pnl", 0) or 0)
                    SESSION.daily_pnl = val
                    SESSION.final_pnl = val
                    if val > SESSION.peak_pnl:
                        SESSION.peak_pnl = val
                    TSM.evaluate_state(SESSION)
                    TSM.save_session(SESSION)
                    self._send(200, {"ok": True, "state": SESSION.state,
                                    "daily_pnl": round(SESSION.daily_pnl, 2),
                                    "peak_pnl": round(SESSION.peak_pnl, 2)})
                    return
                if action == "trade":
                    danger = TSM.register_trade_result(
                        SESSION,
                        pnl=float(data.get("pnl", 0) or 0),
                        lot=float(data.get("lot", 0) or 0),
                        direction=data.get("direction", ""),
                        hold_min=data.get("hold_min"),
                        had_sl=bool(data.get("had_sl", False)),
                        was_reversal=bool(data.get("was_reversal", False)),
                        opened_new=bool(data.get("opened_new", True)),
                    )
                    TSM.save_session(SESSION)
                    self._send(200, {"ok": True, "danger": danger,
                                    "state": SESSION.state,
                                    "daily_pnl": round(SESSION.daily_pnl, 2)})
                    return
                self._send(200, {"ok": False, "msg": "未知 action: %s" % action})

            else:
                self._send(404, {"error": "not found"})
        except Exception as e:  # noqa
            self._send(500, {"error": str(e)})

    def log_message(self, fmt, *args):
        sys.stderr.write("[discipline] " + (fmt % args) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8777)
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print("══════════════════════════════════════════")
    print("  Trading Discipline 轻量入口已启动")
    print("  浏览器打开: http://%s:%d" % (args.host, args.port))
    print("  停服: Ctrl+C")
    print("══════════════════════════════════════════")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
