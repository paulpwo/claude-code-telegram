import { NavLink, Outlet } from "react-router-dom";
import {
  LayoutDashboard,
  MessageSquare,
  Activity,
  Clock,
  Settings,
  Users,
  LogOut,
  Moon,
  Sun,
} from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { logout } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/hooks/useTheme";
import api from "@/lib/api";

const navItems = [
  { to: "/admin/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/admin/sessions", label: "Sessions", icon: MessageSquare },
  { to: "/admin/events", label: "Events", icon: Activity },
  { to: "/admin/crons", label: "Crons", icon: Clock },
  { to: "/admin/config", label: "Config", icon: Settings },
  { to: "/admin/users", label: "Users", icon: Users },
];

function StatusBar() {
  const queryClient = useQueryClient();

  const { data: health, isFetching } = useQuery({
    queryKey: ["health"],
    queryFn: () => api.get<{ status: string }>("/health", { baseURL: "/" }),
    refetchInterval: 15_000,
    retry: false,
  });

  // Read dashboard cache WITHOUT triggering a fetch — Dashboard.tsx owns the query
  const summary = queryClient.getQueryData<Record<string, unknown>>(["dashboard-summary"]);
  const queryState = queryClient.getQueryState(["dashboard-summary"]);
  const dataUpdatedAt = queryState?.dataUpdatedAt;

  const isOnline = health?.data?.status === "ok";
  const lastRefresh = dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString() : null;

  return (
    <div className="flex items-center gap-4 text-xs text-muted-foreground">
      {/* active sessions */}
      {(summary as any)?.active_sessions !== undefined && (
        <span className="flex items-center gap-1.5">
          <Activity className="h-3 w-3" />
          {(summary as any).active_sessions} active
        </span>
      )}

      {/* last refresh */}
      {lastRefresh && (
        <span className="hidden sm:inline">
          updated {lastRefresh}
        </span>
      )}

      {/* health dot */}
      <span className="flex items-center gap-1.5 font-medium">
        <span
          className={`relative flex h-2 w-2 ${isFetching ? "" : ""}`}
        >
          {isOnline && (
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
          )}
          <span
            className={`relative inline-flex rounded-full h-2 w-2 ${
              isOnline ? "bg-green-500" : "bg-red-500"
            }`}
          />
        </span>
        <span className={isOnline ? "text-green-600 dark:text-green-400" : "text-destructive"}>
          {isOnline ? "Online" : "Offline"}
        </span>
      </span>
    </div>
  );
}

export function Layout() {
  const { theme, toggle } = useTheme();

  return (
    <div className="flex h-screen bg-background">
      {/* Sidebar */}
      <aside className="w-64 border-r bg-card flex flex-col">
        <div className="p-6 border-b">
          <h1 className="text-xl font-bold text-primary">Admin Panel</h1>
          <p className="text-xs text-muted-foreground mt-1">Claude Code Telegram Bot</p>
        </div>

        <nav className="flex-1 p-4 space-y-1">
          {navItems.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                }`
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="p-4 border-t space-y-1">
          <Button
            variant="ghost"
            className="w-full justify-start gap-3 text-muted-foreground"
            onClick={toggle}
          >
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            {theme === "dark" ? "Light mode" : "Dark mode"}
          </Button>
          <Button
            variant="ghost"
            className="w-full justify-start gap-3 text-muted-foreground"
            onClick={logout}
          >
            <LogOut className="h-4 w-4" />
            Logout
          </Button>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar */}
        <header className="h-12 border-b bg-card flex items-center justify-end px-6 shrink-0">
          <StatusBar />
        </header>

        {/* Page */}
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
