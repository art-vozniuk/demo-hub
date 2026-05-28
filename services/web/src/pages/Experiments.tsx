import { useEffect, useMemo, useState } from "react";
import { Navigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  benchApi,
  type BenchConfig,
  type BenchEstimateResponse,
  type BenchRunSummary,
  type BenchTier,
} from "@/api/bench";
import { usePermissions } from "@/hooks/usePermissions";

const CONFIGS: { value: BenchConfig; label: string }[] = [
  { value: "flux_local_mock", label: "Local mock (dispatch only, $0)" },
  { value: "flux_modal_mock", label: "Modal CPU mock (~$0.0001/img)" },
  { value: "flux_opt_a10g", label: "A10G — no batching" },
  { value: "flux_opt_h100", label: "H100 — batched (8)" },
];

const TIERS: { value: BenchTier; label: string; description: string }[] = [
  { value: "MOCK_LOCAL", label: "MOCK_LOCAL", description: "dispatch sleeps, no Modal" },
  { value: "MOCK_MODAL", label: "MOCK_MODAL", description: "Modal CPU, sleeps + stubs" },
  { value: "REAL", label: "REAL", description: "real GPU billing" },
];

const Experiments = () => {
  const { permissions, isLoading: permsLoading } = usePermissions();
  const qc = useQueryClient();

  const [config, setConfig] = useState<BenchConfig>("flux_local_mock");
  const [tier, setTier] = useState<BenchTier>("MOCK_LOCAL");
  const [budgetUsd, setBudgetUsd] = useState<number>(0.05);
  const [concurrency, setConcurrency] = useState<number>(8);
  const [error, setError] = useState<string | null>(null);

  const runsQuery = useQuery({
    queryKey: ["bench", "runs"],
    queryFn: benchApi.listRuns,
    refetchInterval: 2000,
    enabled: permissions.can_run_experiments,
  });

  const estimateQuery = useQuery({
    queryKey: ["bench", "estimate", config, tier, budgetUsd],
    queryFn: () => benchApi.estimate({ config, tier, budget_usd: budgetUsd }),
    enabled: permissions.can_run_experiments && budgetUsd > 0,
  });

  useEffect(() => {
    // Keep config and tier loosely coupled — picking a mock tier with a
    // real config (or vice versa) is a footgun.
    if (tier === "MOCK_LOCAL" && config !== "flux_local_mock") {
      setConfig("flux_local_mock");
    } else if (tier === "MOCK_MODAL" && config !== "flux_modal_mock") {
      setConfig("flux_modal_mock");
    } else if (
      tier === "REAL" &&
      (config === "flux_local_mock" || config === "flux_modal_mock")
    ) {
      setConfig("flux_opt_a10g");
    }
  }, [tier, config]);

  const onStart = async () => {
    setError(null);
    try {
      await benchApi.startRun({
        config,
        tier,
        budget_usd: budgetUsd,
        concurrency,
        sample_input: {
          image_bucket: "demo-hub-public",
          image_key: "samples/portrait.jpg",
          prompt: "studio portrait, cinematic lighting",
        },
      });
      qc.invalidateQueries({ queryKey: ["bench", "runs"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  if (permsLoading) {
    return <PageScaffold title="Experiments" subtitle="Checking access…" />;
  }
  if (!permissions.can_run_experiments) {
    return <Navigate to="/" replace />;
  }

  return (
    <PageScaffold
      title="Experiments"
      subtitle="Cost-bounded inference bench. Don't burn the wallet."
    >
      <div className="grid gap-6 md:grid-cols-[1fr,1fr]">
        <section className="rounded-lg border border-border bg-card p-5">
          <h2 className="mb-4 text-sm font-semibold uppercase text-muted-foreground">
            Start a run
          </h2>

          <Field label="Tier">
            <select
              value={tier}
              onChange={(e) => setTier(e.target.value as BenchTier)}
              className="w-full rounded border border-border bg-background px-2 py-1.5 text-sm"
            >
              {TIERS.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label} — {t.description}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Config">
            <select
              value={config}
              onChange={(e) => setConfig(e.target.value as BenchConfig)}
              className="w-full rounded border border-border bg-background px-2 py-1.5 text-sm"
            >
              {CONFIGS.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </Field>

          <Field label={`Budget ($${budgetUsd.toFixed(2)})`}>
            <input
              type="range"
              min={0.01}
              max={0.50}
              step={0.01}
              value={budgetUsd}
              onChange={(e) => setBudgetUsd(parseFloat(e.target.value))}
              className="w-full"
            />
          </Field>

          <Field label={`Concurrency (${concurrency})`}>
            <input
              type="range"
              min={1}
              max={64}
              step={1}
              value={concurrency}
              onChange={(e) => setConcurrency(parseInt(e.target.value))}
              className="w-full"
            />
          </Field>

          <EstimateBox estimate={estimateQuery.data} />

          <button
            onClick={onStart}
            disabled={!estimateQuery.data?.proceedable}
            className="mt-4 w-full rounded bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:bg-muted disabled:text-muted-foreground"
          >
            Run
          </button>
          {error && (
            <p className="mt-2 text-xs text-destructive">{error}</p>
          )}
        </section>

        <section className="rounded-lg border border-border bg-card p-5">
          <h2 className="mb-4 text-sm font-semibold uppercase text-muted-foreground">
            Recent runs
          </h2>
          <RecentRuns runs={runsQuery.data?.runs ?? []} />
        </section>
      </div>

      <section className="mt-6 rounded-lg border border-border bg-card p-5">
        <h2 className="mb-2 text-sm font-semibold uppercase text-muted-foreground">
          Grafana
        </h2>
        <p className="mb-4 text-sm text-muted-foreground">
          Live dashboards behind <code className="font-mono">/grafana/</code> —
          Inference (RED + GPU internals), Bench Comparison (images per $0.10),
          and Cold Start.
        </p>
        <iframe
          title="Grafana — bench comparison"
          src="/grafana/d/bench-compare?theme=dark&kiosk=tv"
          className="h-[480px] w-full rounded border border-border"
        />
      </section>
    </PageScaffold>
  );
};

const PageScaffold = ({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children?: React.ReactNode;
}) => (
  <div className="container mx-auto max-w-6xl px-4 py-8">
    <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
    {subtitle && (
      <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
    )}
    <div className="mt-6">{children}</div>
  </div>
);

const Field = ({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) => (
  <label className="mb-3 block">
    <span className="mb-1 block text-xs text-muted-foreground">{label}</span>
    {children}
  </label>
);

const EstimateBox = ({
  estimate,
}: {
  estimate: BenchEstimateResponse | undefined;
}) => {
  if (!estimate) {
    return (
      <div className="mt-2 rounded border border-border bg-muted/30 p-3 text-xs text-muted-foreground">
        Calculating estimate…
      </div>
    );
  }
  return (
    <div
      className={`mt-2 rounded border p-3 text-xs ${
        estimate.proceedable
          ? "border-border bg-muted/30"
          : "border-destructive/40 bg-destructive/10"
      }`}
    >
      <div className="grid grid-cols-2 gap-2">
        <Stat label="Expected images">
          {estimate.expected_images_low}–{estimate.expected_images_high}
        </Stat>
        <Stat label="Expected time">
          {estimate.expected_time_seconds_low.toFixed(1)}–
          {estimate.expected_time_seconds_high.toFixed(1)}s
        </Stat>
        <Stat label="Cold-start risk">{estimate.cold_start_risk_pct}%</Stat>
        <Stat label="Today's spend">
          ${estimate.todays_spend_usd.toFixed(4)} / $
          {estimate.daily_cap_usd.toFixed(2)}
        </Stat>
      </div>
      {!estimate.proceedable && estimate.reason && (
        <p className="mt-2 text-destructive">{estimate.reason}</p>
      )}
    </div>
  );
};

const Stat = ({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) => (
  <div>
    <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
      {label}
    </div>
    <div className="text-sm font-medium">{children}</div>
  </div>
);

const RecentRuns = ({ runs }: { runs: BenchRunSummary[] }) => {
  const rows = useMemo(() => runs.slice(0, 20), [runs]);
  if (rows.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No runs yet. Start one from the panel on the left.
      </p>
    );
  }
  return (
    <ul className="divide-y divide-border">
      {rows.map((r) => {
        const ipd =
          r.cost_usd > 0 ? r.images_generated / r.cost_usd : 0;
        return (
          <li key={r.run_id} className="py-2 text-xs">
            <div className="flex flex-wrap items-baseline gap-x-3">
              <span className="font-mono">{r.run_id.slice(0, 8)}</span>
              <span className="font-medium">{r.config}</span>
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px]">
                {r.tier}
              </span>
              <span
                className={
                  r.status === "completed"
                    ? "text-green-600"
                    : r.status === "failed" || r.status === "aborted"
                    ? "text-destructive"
                    : "text-muted-foreground"
                }
              >
                {r.status}
              </span>
            </div>
            <div className="mt-1 grid grid-cols-4 gap-2 text-muted-foreground">
              <div>{r.images_generated} img</div>
              <div>${r.cost_usd.toFixed(4)}</div>
              <div>{r.elapsed_seconds.toFixed(1)}s</div>
              <div>{ipd.toFixed(0)} img/$</div>
            </div>
          </li>
        );
      })}
    </ul>
  );
};

export default Experiments;
