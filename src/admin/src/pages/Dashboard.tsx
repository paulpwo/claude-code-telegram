import { useQuery } from "@tanstack/react-query";
import { dashboardApi } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Activity,
  Users,
  MessageSquare,
  Clock,
  DollarSign,
  Layers,
  CheckCircle2,
  XCircle,
  Wrench,
  TrendingUp,
} from "lucide-react";

// ── helpers ───────────────────────────────────────────────────────────────────

function fmt$(n: number) {
  if (n >= 1) return `$${n.toFixed(2)}`;
  return `$${n.toFixed(4)}`;
}

function relTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function shortDate(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// ── stat card ─────────────────────────────────────────────────────────────────

interface StatCardProps {
  title: string;
  value: string | number;
  sub?: string;
  icon: React.ElementType;
  accent?: string; // tailwind text colour class
}

function StatCard({ title, value, sub, icon: Icon, accent }: StatCardProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className={`text-2xl font-bold ${accent ?? ""}`}>{value}</div>
        {sub && <p className="text-xs text-muted-foreground mt-1">{sub}</p>}
      </CardContent>
    </Card>
  );
}

// ── 7-day bar chart ───────────────────────────────────────────────────────────

interface DayBar {
  date: string;
  messages: number;
  cost: number;
}

function ActivityChart({ data }: { data: DayBar[] }) {
  const maxMsgs = Math.max(...data.map((d) => d.messages), 1);
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-muted-foreground" />
          Messages — last 7 days
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-end gap-1.5 h-24">
          {data.map((d) => {
            const pct = Math.max((d.messages / maxMsgs) * 100, d.messages > 0 ? 6 : 2);
            return (
              <div key={d.date} className="flex-1 flex flex-col items-center gap-1 group relative">
                {/* tooltip */}
                <div className="absolute bottom-full mb-1 hidden group-hover:flex flex-col items-center z-10">
                  <div className="bg-popover border text-popover-foreground text-xs rounded px-2 py-1 whitespace-nowrap shadow">
                    <span className="font-semibold">{d.messages} msgs</span>
                    {d.cost > 0 && <span className="text-muted-foreground ml-1">· {fmt$(d.cost)}</span>}
                  </div>
                </div>
                <div
                  className="w-full rounded-sm bg-primary/80 hover:bg-primary transition-colors"
                  style={{ height: `${pct}%` }}
                />
                <span className="text-[10px] text-muted-foreground">{shortDate(d.date)}</span>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

// ── top tools ─────────────────────────────────────────────────────────────────

interface ToolStat {
  tool: string;
  uses: number;
}

function TopTools({ tools }: { tools: ToolStat[] }) {
  const max = Math.max(...tools.map((t) => t.uses), 1);
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <Wrench className="h-4 w-4 text-muted-foreground" />
          Top tools today
        </CardTitle>
      </CardHeader>
      <CardContent>
        {tools.length === 0 ? (
          <p className="text-sm text-muted-foreground">No tool usage today</p>
        ) : (
          <div className="space-y-2">
            {tools.map((t) => (
              <div key={t.tool} className="flex items-center gap-2">
                <span className="text-xs font-mono w-32 truncate shrink-0">{t.tool}</span>
                <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                  <div
                    className="h-full rounded-full bg-primary/70"
                    style={{ width: `${(t.uses / max) * 100}%` }}
                  />
                </div>
                <span className="text-xs text-muted-foreground w-6 text-right">{t.uses}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── recent activity ───────────────────────────────────────────────────────────

interface ActivityRow {
  id: number;
  username?: string;
  event_type: string;
  success: boolean;
  timestamp: string;
}

function RecentActivity({ rows }: { rows: ActivityRow[] }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <Activity className="h-4 w-4 text-muted-foreground" />
          Recent activity
        </CardTitle>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No activity yet</p>
        ) : (
          <div className="space-y-2">
            {rows.map((r) => (
              <div key={r.id} className="flex items-center justify-between gap-2 text-sm">
                <div className="flex items-center gap-2 min-w-0">
                  {r.success ? (
                    <CheckCircle2 className="h-3.5 w-3.5 text-green-500 shrink-0" />
                  ) : (
                    <XCircle className="h-3.5 w-3.5 text-destructive shrink-0" />
                  )}
                  <Badge variant="secondary" className="text-xs font-mono shrink-0">
                    {r.event_type}
                  </Badge>
                  {r.username && (
                    <span className="text-muted-foreground truncate text-xs">@{r.username}</span>
                  )}
                </div>
                <span className="text-xs text-muted-foreground shrink-0">{relTime(r.timestamp)}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── main page ─────────────────────────────────────────────────────────────────

export function Dashboard() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: () => dashboardApi.getSummary().then((r) => r.data),
    refetchInterval: 30_000,
  });

  if (isLoading) {
    return (
      <div className="p-8">
        <p className="text-muted-foreground">Loading dashboard...</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="p-8">
        <p className="text-destructive">Failed to load dashboard data.</p>
      </div>
    );
  }

  const nextCronLabel = data?.next_cron_run
    ? `${new Date(data.next_cron_run).toLocaleTimeString()}${data.next_cron_name ? ` · ${data.next_cron_name}` : ""}`
    : "—";

  return (
    <div className="p-8 space-y-6">
      {/* header */}
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Dashboard</h2>
        <p className="text-muted-foreground">System overview — auto-refreshes every 30s</p>
      </div>

      {/* row 1 — sessions + messages */}
      <div className="grid gap-4 grid-cols-2 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="Active Sessions"
          value={data?.active_sessions ?? 0}
          sub={`${data?.total_sessions ?? 0} total`}
          icon={Activity}
          accent="text-primary"
        />
        <StatCard
          title="Messages Today"
          value={data?.messages_today ?? 0}
          sub={`${data?.total_messages ?? 0} all-time`}
          icon={MessageSquare}
        />
        <StatCard
          title="Users"
          value={data?.total_users ?? 0}
          sub={`${data?.allowed_users ?? 0} allowed · ${data?.blocked_users ?? 0} blocked`}
          icon={Users}
        />
        <StatCard
          title="Next Cron"
          value={nextCronLabel}
          icon={Clock}
        />
      </div>

      {/* row 2 — cost */}
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-3">
        <StatCard
          title="Cost Today"
          value={fmt$(data?.cost_today ?? 0)}
          icon={DollarSign}
          accent={data?.cost_today && data.cost_today > 0.5 ? "text-amber-500" : undefined}
        />
        <StatCard
          title="Cost This Month"
          value={fmt$(data?.cost_this_month ?? 0)}
          icon={DollarSign}
        />
        <StatCard
          title="Total Cost"
          value={fmt$(data?.cost_total ?? 0)}
          sub="all time"
          icon={Layers}
        />
      </div>

      {/* row 3 — chart + top tools */}
      <div className="grid gap-4 grid-cols-1 lg:grid-cols-2">
        <ActivityChart data={data?.activity_7d ?? []} />
        <TopTools tools={data?.top_tools ?? []} />
      </div>

      {/* row 4 — recent activity */}
      <RecentActivity rows={data?.recent_activity ?? []} />
    </div>
  );
}
