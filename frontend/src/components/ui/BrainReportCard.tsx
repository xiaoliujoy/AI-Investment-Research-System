import { useState, useEffect } from "react";
import { Brain, Loader2, AlertCircle, RefreshCw, ShieldAlert, CheckCircle2, XCircle, AlertTriangle, ChevronDown, ChevronUp, Activity } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { api, ApiError, type BrainReport } from "@/lib/api";
import { cn } from "@/lib/utils";

const canBuyConfig = {
  YES: { icon: CheckCircle2, color: "text-success", bg: "bg-success/10", border: "border-success/30", label: "可以买入" },
  NO: { icon: XCircle, color: "text-danger", bg: "bg-danger/10", border: "border-danger/30", label: "不宜买入" },
  CAUTION: { icon: AlertTriangle, color: "text-warning", bg: "bg-warning/10", border: "border-warning/30", label: "谨慎" },
};

const severityConfig = {
  HIGH: { color: "text-danger", bg: "bg-danger/10", border: "border-danger/30" },
  MEDIUM: { color: "text-warning", bg: "bg-warning/10", border: "border-warning/30" },
  LOW: { color: "text-muted-foreground", bg: "bg-muted/20", border: "border-border/30" },
};

export function BrainReportCard() {
  const [report, setReport] = useState<BrainReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showNarrative, setShowNarrative] = useState(false);
  const [showChain, setShowChain] = useState(false);

  const load = () => {
    setLoading(true);
    setError(null);
    api.brainReport()
      .then(setReport)
      .catch((e) => setError(e instanceof ApiError ? e.message : "加载失败"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading) {
    return (
      <GlassCard className="mb-6 p-6">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> 加载决策简报...
        </div>
      </GlassCard>
    );
  }

  if (error) {
    return (
      <GlassCard className="mb-6 p-6">
        <div className="flex items-center gap-2 text-muted-foreground">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span className="text-sm">{error}</span>
          <button onClick={load} className="ml-auto text-primary hover:underline text-sm">重试</button>
        </div>
      </GlassCard>
    );
  }

  if (!report) return null;

  const cfg = canBuyConfig[report.decision.can_buy] || canBuyConfig.CAUTION;
  const CanBuyIcon = cfg.icon;
  const gn = report.L0.global_narrative;

  return (
    <div className="mb-6">
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
          <Brain className="h-4 w-4" /> 每日方向 · 验证简报
        </h3>
        <div className="flex items-center gap-2">
          {report.trade_date && (
            <span className="text-[11px] text-muted-foreground/50">{report.trade_date}</span>
          )}
          <button onClick={load} className="text-muted-foreground hover:text-primary" title="刷新">
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* L0 Narrative */}
      <GlassCard glow className="mb-3 p-4">
        <p className="text-[11px] text-muted-foreground/50 mb-1">L0 市场叙事</p>
        <p className="text-sm font-medium leading-relaxed">{report.L0.headline}</p>
        {report.L0.body && (
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{report.L0.body}</p>
        )}
      </GlassCard>

      {/* Decision + Confidence */}
      <div className="mb-3 grid gap-3 sm:grid-cols-3">
        {/* Decision */}
        <GlassCard className={cn("p-4 border", cfg.border)}>
          <p className="text-[11px] text-muted-foreground/50 mb-2">决策结论</p>
          <div className="flex items-center gap-2">
            <CanBuyIcon className={cn("h-5 w-5", cfg.color)} />
            <span className={cn("text-lg font-bold", cfg.color)}>{report.decision.can_buy}</span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">{cfg.label}</p>
          <p className="mt-2 text-xs font-medium text-foreground/80">{report.decision.position_pct}</p>
        </GlassCard>

        {/* Confidence */}
        <GlassCard className="p-4">
          <p className="text-[11px] text-muted-foreground/50 mb-2">置信度</p>
          <div className="flex items-baseline gap-1">
            <span className="text-2xl font-bold text-primary">{report.confidence.overall}</span>
            <span className="text-xs text-muted-foreground">/100</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted/30">
            <div
              className={cn(
                "h-full rounded-full transition-all",
                report.confidence.overall >= 70 ? "bg-success" : report.confidence.overall >= 50 ? "bg-warning" : "bg-danger"
              )}
              style={{ width: `${report.confidence.overall}%` }}
            />
          </div>
          <p className="mt-1.5 text-[11px] text-muted-foreground/50">
            base {report.confidence.base} · penalty {report.confidence.penalty}
          </p>
        </GlassCard>

        {/* Vote */}
        <GlassCard className="p-4">
          <p className="text-[11px] text-muted-foreground/50 mb-2">方向投票</p>
          <div className="flex items-center gap-4">
            <div>
              <p className="text-xs text-muted-foreground">看多</p>
              <p className="text-xl font-bold text-danger">{report.decision.bull}</p>
            </div>
            <div className="text-muted-foreground/30">vs</div>
            <div>
              <p className="text-xs text-muted-foreground">看空</p>
              <p className="text-xl font-bold text-success">{report.decision.bear}</p>
            </div>
          </div>
          {report.decision.hard_no.length > 0 && (
            <div className="mt-2 space-y-1">
              {report.decision.hard_no.map((h, i) => (
                <p key={i} className="flex items-center gap-1 text-[11px] text-danger/80">
                  <ShieldAlert className="h-3 w-3" /> {h}
                </p>
              ))}
            </div>
          )}
        </GlassCard>
      </div>

      {/* Reasons */}
      {report.decision.reasons.length > 0 && (
        <GlassCard className="mb-3 p-4">
          <p className="text-[11px] text-muted-foreground/50 mb-2">决策依据</p>
          <div className="space-y-1">
            {report.decision.reasons.map((r, i) => (
              <p key={i} className="text-xs text-foreground/80 flex items-start gap-1.5">
                <span className="text-muted-foreground/40 mt-0.5">{i + 1}.</span> {r}
              </p>
            ))}
          </div>
        </GlassCard>
      )}

      {/* Conflicts */}
      {report.conflicts.length > 0 && (
        <GlassCard className="mb-3 p-4">
          <div className="mb-2 flex items-center gap-1.5">
            <ShieldAlert className="h-4 w-4 text-warning" />
            <p className="text-sm font-semibold">跨层冲突检测 ({report.conflicts.length})</p>
          </div>
          <div className="space-y-2">
            {report.conflicts.map((c, i) => {
              const sc = severityConfig[c.severity] || severityConfig.LOW;
              return (
                <div key={i} className={cn("rounded-lg border p-2.5", sc.bg, sc.border)}>
                  <div className="flex items-center gap-2">
                    <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-bold", sc.bg, sc.color)}>
                      {c.severity}
                    </span>
                    <span className="text-xs font-medium">{c.rule}</span>
                    <span className="ml-auto text-[10px] text-muted-foreground/50">{c.layers.join(" / ")}</span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{c.desc}</p>
                </div>
              );
            })}
          </div>
        </GlassCard>
      )}

      {/* Global Narrative (expandable) */}
      {gn && (
        <GlassCard className="mb-3 p-4">
          <button
            onClick={() => setShowNarrative(!showNarrative)}
            className="flex w-full items-center justify-between"
          >
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-primary" />
              <span className="text-sm font-semibold">全球市场叙事</span>
              <span className="rounded bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
                {gn.narrative_name} ({Math.round(gn.match_score * 100)}%)
              </span>
            </div>
            {showNarrative ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
          </button>

          {showNarrative && (
            <div className="mt-3 space-y-3">
              <p className="text-sm font-medium leading-relaxed">{gn.headline}</p>

              {gn.true_driver && (
                <div>
                  <p className="text-[11px] font-semibold text-muted-foreground mb-0.5">真正驱动</p>
                  <p className="text-xs text-foreground/80">{gn.true_driver}</p>
                </div>
              )}

              {gn.weakest_link && (
                <div>
                  <p className="text-[11px] font-semibold text-muted-foreground mb-0.5">最弱环节</p>
                  <p className="text-xs text-warning/90">{gn.weakest_link}</p>
                </div>
              )}

              {gn.counterfactual && (
                <div>
                  <p className="text-[11px] font-semibold text-muted-foreground mb-0.5">反事实分析</p>
                  <p className="text-xs text-muted-foreground">{gn.counterfactual}</p>
                </div>
              )}

              {gn.q3_consensus && (
                <div>
                  <p className="text-[11px] font-semibold text-muted-foreground mb-0.5">共识阶段</p>
                  <p className="text-xs text-foreground/80">{gn.q3_consensus}</p>
                </div>
              )}

              {gn.q4_falsification && (
                <div>
                  <p className="text-[11px] font-semibold text-muted-foreground mb-0.5">证伪条件</p>
                  <p className="text-xs text-muted-foreground">{gn.q4_falsification}</p>
                </div>
              )}

              {gn.falsification_text && (
                <p className="text-[11px] text-muted-foreground/60 border-t border-border/30 pt-2">{gn.falsification_text}</p>
              )}
            </div>
          )}
        </GlassCard>
      )}

      {/* Reasoning Chain (expandable) */}
      <GlassCard className="p-4">
        <button
          onClick={() => setShowChain(!showChain)}
          className="flex w-full items-center justify-between"
        >
          <span className="text-sm font-semibold">推理链 ({report.chain.length} 层)</span>
          {showChain ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
        </button>
        {showChain && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {report.chain.map((layer, i) => {
              const r = report.results[layer] as Record<string, unknown> | undefined;
              const score = r?.score as number | undefined;
              const stage = r?.stage as string | undefined;
              const stageColor = stage === "bullish" ? "text-danger" : stage === "bearish" ? "text-success" : "text-muted-foreground";
              return (
                <div key={i} className="flex items-center gap-1">
                  {i > 0 && <span className="text-muted-foreground/30 text-xs">→</span>}
                  <div className={cn("rounded-lg border border-border/30 px-2.5 py-1.5", i === 0 && "border-primary/30 bg-primary/5")}>
                    <span className="text-xs font-medium">{layer}</span>
                    {score != null && (
                      <span className={cn("ml-1.5 text-[10px] font-mono", stageColor)}>{score}</span>
                    )}
                    {stage && stage !== "unknown" && stage !== "human" && (
                      <span className={cn("ml-1 text-[10px]", stageColor)}>{stage}</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </GlassCard>

      {/* Disclaimer */}
      <p className="mt-2 text-center text-[10px] text-muted-foreground/40">
        买卖/图形由你人工定 · 风险护栏非买卖指令 · 系统只定方向+验证
      </p>
    </div>
  );
}
