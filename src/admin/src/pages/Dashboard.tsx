import { useQuery } from "@tanstack/react-query";
import { dashboardApi } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Activity, Users, MessageSquare, Clock } from "lucide-react";

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

  const stats = [
    {
      title: "Active Sessions",
      value: data?.active_sessions ?? 0,
      icon: Activity,
      description: "Currently open sessions",
    },
    {
      title: "Total Users",
      value: data?.total_users ?? 0,
      icon: Users,
      description: "Registered users",
    },
    {
      title: "Events (24h)",
      value: data?.events_last_24h ?? 0,
      icon: MessageSquare,
      description: "Webhook + audit events",
    },
    {
      title: "Next Cron",
      value: data?.next_cron_run
        ? new Date(data.next_cron_run).toLocaleTimeString()
        : "—",
      icon: Clock,
      description: "Next scheduled job",
    },
  ];

  return (
    <div className="p-8 space-y-6">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Dashboard</h2>
        <p className="text-muted-foreground">System overview — auto-refreshes every 30s</p>
      </div>

      <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map(({ title, value, icon: Icon, description }) => (
          <Card key={title}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">{title}</CardTitle>
              <Icon className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{value}</div>
              <p className="text-xs text-muted-foreground mt-1">{description}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {(data?.messages_today !== undefined || data?.cost_today !== undefined) && (
        <div className="grid gap-4 grid-cols-1 sm:grid-cols-2">
          {data?.messages_today !== undefined && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Messages Today</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{data.messages_today}</div>
              </CardContent>
            </Card>
          )}
          {data?.cost_today !== undefined && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Cost Today</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">${data.cost_today.toFixed(4)}</div>
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
