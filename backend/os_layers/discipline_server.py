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
CSV_PATH = os.path.join(PROJECT_ROOT, "mt5_raw", "trade_path.csv")
EI_PATH = os.path.join(PROJECT_ROOT, "mt5_raw", "execution_intelligence.json")

# 装载引擎
spec = importlib.util.spec_from_file_location(
    "trading_discipline_engine", os.path.join(HERE, "trading_discipline_engine.py"))
ENG = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ENG)
ENG.init()


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
            if path == "/api/plan":
                tid = ENG.record_plan(
                    data.get("market", "MT5"),
                    data.get("symbol", ""),
                    data.get("direction", ""),
                    data.get("hypothesis", ""),
                    data.get("invalid", ""),
                    data.get("risk", ""),
                    data.get("signal", ""),
                    data.get("scenario", ""),
                    data.get("hold4h", ""),
                    data.get("exit", ""),
                )
                self._send(200, {"ok": True, "id": tid})

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
