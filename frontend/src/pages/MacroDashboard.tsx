import { useState, useEffect } from "react";
import { TrendingUp, TrendingDown, RefreshCw, Loader2 } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { api, type MacroAsset, type MacroData } from "@/lib/api";
import { cn } from "@/lib/utils";

/** 分类颜色 */
const CAT_COLOR: Record<string, string> = {
  commodity: "text-amber-400",
  crypto: "text-orange-400",
  forex: "text-blue-400",
};

/** 分类标签 */
const CAT_LABEL: Record<string, string> = {
  commodity: "商品",
  crypto: "加密",
  forex: "指数",
};

const fmtPct = (v: number | null) =>
  v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;

export function MacroDashboard() {
  const [data, setData] = useState<MacroData | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    api.macro()
      .then(setData)
      .catch((e) => setErr(e?.message || String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading) {
    return (
      <div className="mb-6">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-muted-foreground">全球宏观资产</h3>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <GlassCard key={i} className="p-3">
              <p className="text-xs text-muted-foreground">加载中…</p>
              <p className="mt-1 font-mono text-lg font-bold text-muted-foreground/40">—</p>
            </GlassCard>
          ))}
        </div>
      </div>
    );
  }

  if (err || !data) {
    return (
      <div className="mb-6">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-muted-foreground">全球宏观资产</h3>
          <button onClick={load} className="text-xs text-primary hover:underline">重试</button>
        </div>
        <GlassCard className="p-3">
          <p className="text-sm text-muted-foreground">加载失败{err ? `: ${err}` : ""}</p>
        </GlassCard>
      </div>
    );
  }

  return (
    <div className="mb-6">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-muted-foreground">全球宏观资产</h3>
        <button
          onClick={load}
          className="text-muted-foreground hover:text-primary"
          title="刷新"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {data.commodities.map((asset) => {
          const isUp = (asset.change_pct ?? 0) >= 0;
          return (
            <GlassCard key={asset.key} className="p-3">
              <div className="flex items-center justify-between">
                <p className="truncate text-xs text-muted-foreground">{asset.name}</p>
                <span className={cn("rounded px-1 py-0.5 text-[9px] font-medium", CAT_COLOR[asset.cat] || "text-blue-400", "bg-white/5")}>
                  {CAT_LABEL[asset.cat] || "资产"}
                </span>
              </div>
              <p className={cn("mt-1 font-mono text-lg font-bold", isUp ? "text-danger" : "text-success")}>
                {asset.price == null ? "—" : asset.price.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}
              </p>
              <div className={cn("flex items-center gap-1 text-xs", isUp ? "text-danger" : "text-success")}>
                {asset.change_pct != null && (
                  isUp ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />
                )}
                {fmtPct(asset.change_pct)}
              </div>
            </GlassCard>
          );
        })}
      </div>
    </div>
  );
}
