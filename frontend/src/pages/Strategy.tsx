import { useState, useEffect } from "react";
import { TrendingUp, TrendingDown, BarChart3, Users, DollarSign, RefreshCw, Loader2 } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { api, type MarketAmountData, type SectorStat, type LeaderCandidate } from "@/lib/api";
import { cn } from "@/lib/utils";

export function Strategy() {
  const [amount, setAmount] = useState<MarketAmountData | null>(null);
  const [sectors, setSectors] = useState<SectorStat[]>([]);
  const [leaders, setLeaders] = useState<LeaderCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    Promise.all([
      api.strategyMarketAmount().catch(() => null),
      api.strategySectorStats().catch(() => []),
      api.strategyLeaderCandidates(20).catch(() => []),
    ])
      .then(([a, s, l]) => {
        setAmount(a);
        setSectors(s);
        setLeaders(l);
      })
      .catch((e) => setError(e?.message || "加载失败"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="策略研究"
        subtitle="市场情绪 · 板块热度 · 龙头候选"
        actions={
          <button onClick={load} className="text-muted-foreground hover:text-primary">
            <RefreshCw className="h-4 w-4" />
          </button>
        }
      />

      {error && (
        <GlassCard className="mb-6 border-danger/30 p-4">
          <p className="text-sm text-danger">{error}</p>
        </GlassCard>
      )}

      {/* 市场成交额 */}
      <GlassCard className="mb-6">
        <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold">
          <DollarSign className="h-4 w-4" /> 市场成交额
        </h3>
        {amount ? (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div>
              <p className="text-xs text-muted-foreground">两市合计</p>
              <p className="font-mono text-xl font-bold">{amount.total_amount.toLocaleString()}亿</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">上海</p>
              <p className="font-mono text-lg font-semibold">{amount.sh_amount.toLocaleString()}亿</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">深圳</p>
              <p className="font-mono text-lg font-semibold">{amount.sz_amount.toLocaleString()}亿</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">较昨日</p>
              <p className={cn("font-mono text-lg font-semibold", (amount.change_rate ?? 0) >= 0 ? "text-danger" : "text-success")}>
                {amount.change_rate != null ? `${(amount.change_rate * 100).toFixed(2)}%` : "—"}
              </p>
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">暂无数据</p>
        )}
      </GlassCard>

      {/* 板块热度 */}
      <GlassCard className="mb-6">
        <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold">
          <BarChart3 className="h-4 w-4" /> 板块热度 TOP10
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                <th className="px-2 py-2">板块</th>
                <th className="px-2 py-2 text-right">涨跌幅</th>
                <th className="px-2 py-2 text-right">成交额</th>
                <th className="px-2 py-2 text-right">占比</th>
              </tr>
            </thead>
            <tbody>
              {sectors.slice(0, 10).map((s) => (
                <tr key={s.name} className="border-b border-border/30">
                  <td className="px-2 py-2 font-medium">{s.name}</td>
                  <td className={cn("px-2 py-2 text-right font-mono", (s.change_pct ?? 0) >= 0 ? "text-danger" : "text-success")}>
                    {s.change_pct != null ? `${s.change_pct > 0 ? "+" : ""}${s.change_pct}%` : "—"}
                  </td>
                  <td className="px-2 py-2 text-right font-mono">{s.amount.toLocaleString()}亿</td>
                  <td className="px-2 py-2 text-right font-mono text-muted-foreground">
                    {s.amount_ratio != null ? `${(s.amount_ratio * 100).toFixed(2)}%` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>

      {/* 龙头候选 */}
      <GlassCard>
        <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold">
          <Users className="h-4 w-4" /> 龙头候选 TOP20
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                <th className="px-2 py-2">#</th>
                <th className="px-2 py-2">股票</th>
                <th className="px-2 py-2">板块</th>
                <th className="px-2 py-2 text-right">涨幅</th>
                <th className="px-2 py-2 text-right">成交额</th>
                <th className="px-2 py-2 text-right">换手</th>
                <th className="px-2 py-2 text-right">连板</th>
                <th className="px-2 py-2 text-right">市值</th>
              </tr>
            </thead>
            <tbody>
              {leaders.map((l) => (
                <tr key={l.code} className="border-b border-border/30">
                  <td className="px-2 py-2 text-muted-foreground">{l.amount_rank}</td>
                  <td className="px-2 py-2">
                    <span className="font-medium">{l.name}</span>
                    <span className="ml-1 text-xs text-muted-foreground">{l.code}</span>
                  </td>
                  <td className="px-2 py-2 text-xs text-muted-foreground">{l.sector}</td>
                  <td className={cn("px-2 py-2 text-right font-mono", (l.change_pct ?? 0) >= 0 ? "text-danger" : "text-success")}>
                    {l.change_pct != null ? `${l.change_pct > 0 ? "+" : ""}${l.change_pct}%` : "—"}
                  </td>
                  <td className="px-2 py-2 text-right font-mono">{l.amount.toLocaleString()}亿</td>
                  <td className="px-2 py-2 text-right font-mono">
                    {l.turnover_rate != null ? `${l.turnover_rate}%` : "—"}
                  </td>
                  <td className="px-2 py-2 text-right font-mono">{l.board_height > 0 ? `${l.board_height}板` : "—"}</td>
                  <td className="px-2 py-2 text-right font-mono text-muted-foreground">
                    {l.mcap != null ? `${l.mcap.toLocaleString()}亿` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>
    </div>
  );
}
