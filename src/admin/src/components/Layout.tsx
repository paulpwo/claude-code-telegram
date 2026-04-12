import { NavLink, Outlet } from "react-router-dom";
import {
  LayoutDashboard,
  MessageSquare,
  Activity,
  Clock,
  Settings,
  Users,
  LogOut,
} from "lucide-react";
import { logout } from "@/lib/auth";
import { Button } from "@/components/ui/button";

const navItems = [
  { to: "/admin/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/admin/sessions", label: "Sessions", icon: MessageSquare },
  { to: "/admin/events", label: "Events", icon: Activity },
  { to: "/admin/crons", label: "Crons", icon: Clock },
  { to: "/admin/config", label: "Config", icon: Settings },
  { to: "/admin/users", label: "Users", icon: Users },
];

export function Layout() {
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

        <div className="p-4 border-t">
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
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
