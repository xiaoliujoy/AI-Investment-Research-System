# -*- coding: utf-8 -*-
"""
ReasoningContext：贯穿整条推理链的共享状态。

核心思想（用户要求从"平行模块"升级为"串行推理链"）：
- 上一层 Agent 的结论（raw + 提取的 signal + 上游输入摘要）写入 ctx；
- 下一层 Agent 从 ctx 读取上游结论作为输入；
- 于是 L1→L2→L4→L3→L5→...→L8 真正形成一条"因果链"，
  而不再是八份互不相关的独立分析。
"""
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
BACK = os.path.dirname(BASE)
OUT = os.path.join(BACK, "output")
os.makedirs(OUT, exist_ok=True)


class ReasoningContext:
    def __init__(self, trade_date=None):
        self.trade_date = trade_date
        self.generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.results = {}   # "L1" -> AgentResult（含 raw/signal/output/confidence/risk_note/upstream/gaps）
        self.order = []     # 实际执行顺序（不含 L0）
        self.conflicts = []

    def put(self, layer, result):
        self.results[layer] = result
        if layer != "L0" and layer not in self.order:
            self.order.append(layer)

    def get(self, layer):
        return self.results.get(layer)

    def get_signal(self, layer, key, default=None):
        r = self.results.get(layer)
        if not r:
            return default
        return r.get("signal", {}).get(key, default)

    def get_raw(self, layer):
        r = self.results.get(layer)
        return r.get("raw") if r else None

    def all_layers(self):
        return self.results
