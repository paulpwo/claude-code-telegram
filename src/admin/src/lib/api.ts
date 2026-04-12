import axios from "axios";
import { clearToken, getToken } from "./auth";

const api = axios.create({
  baseURL: "/api/admin",
  headers: {
    "Content-Type": "application/json",
  },
});

// Request interceptor: inject JWT from localStorage
api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor: clear token and redirect on 401
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      clearToken();
      window.location.href = "/admin/login";
    }
    return Promise.reject(error);
  }
);

export default api;

// ---------- typed API helpers ----------

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Session {
  session_id: string;
  user_id: number;
  username?: string;
  directory: string;
  is_active: boolean;
  message_count: number;
  created_at: string;
  last_active?: string;
}

export interface Message {
  id: number;
  role: string;
  content: string;
  timestamp: string;
  tokens?: number;
  cost?: number;
}

export interface WebhookEvent {
  id: number;
  provider: string;
  event_type: string;
  payload_preview: string;
  status: string;
  received_at: string;
}

export interface AuditEvent {
  id: number;
  user_id: number;
  username?: string;
  action: string;
  resource?: string;
  details?: string;
  created_at: string;
}

export interface CronJob {
  id: string;
  name: string;
  func: string;
  trigger: string;
  next_run_time?: string;
  is_paused: boolean;
}

export interface User {
  user_id: number;
  username?: string;
  first_name?: string;
  is_allowed: boolean;
  last_active?: string;
  total_cost?: number;
}

export interface ActivityDay {
  date: string;
  messages: number;
  cost: number;
}

export interface ToolStat {
  tool: string;
  uses: number;
}

export interface ActivityRow {
  id: number;
  username?: string;
  event_type: string;
  success: boolean;
  timestamp: string;
}

export interface DashboardSummary {
  // sessions
  total_sessions: number;
  active_sessions: number;
  // users
  total_users: number;
  allowed_users: number;
  blocked_users: number;
  // messages
  total_messages: number;
  messages_today: number;
  // cost
  cost_today: number;
  cost_this_month: number;
  cost_total: number;
  // events
  total_events_24h: number;
  // scheduler
  next_cron_run?: string;
  next_cron_name?: string;
  // charts
  activity_7d: ActivityDay[];
  top_tools: ToolStat[];
  recent_activity: ActivityRow[];
}

// Auth
export const authApi = {
  login: (password: string) =>
    api.post<{ access_token: string; token_type: string; expires_in: number }>(
      "/auth/login",
      { password }
    ),
};

// Dashboard
export const dashboardApi = {
  getSummary: () => api.get<DashboardSummary>("/summary"),
};

// Sessions
export const sessionsApi = {
  list: (params?: { limit?: number; offset?: number; user_id?: number }) =>
    api.get<PaginatedResponse<Session>>("/sessions", { params }),
  get: (sessionId: string) =>
    api.get<Session & { messages: Message[] }>(`/sessions/${sessionId}`),
};

// Events
export const eventsApi = {
  getWebhooks: (params?: { limit?: number; offset?: number; provider?: string }) =>
    api.get<PaginatedResponse<WebhookEvent>>("/events/webhooks", { params }),
  getAuditLog: (params?: { limit?: number; offset?: number; user_id?: number; action?: string }) =>
    api.get<PaginatedResponse<AuditEvent>>("/events/audit", { params }),
};

// Crons
export const cronsApi = {
  list: () => api.get<{ jobs: CronJob[]; total: number }>("/crons"),
  pause: (jobId: string) => api.post(`/crons/${jobId}/pause`),
  resume: (jobId: string) => api.post(`/crons/${jobId}/resume`),
  trigger: (jobId: string) => api.post(`/crons/${jobId}/trigger`),
};

// Config
export const configApi = {
  get: () => api.get<Record<string, unknown>>("/config"),
};

// Users
export const usersApi = {
  list: (params?: { limit?: number; offset?: number }) =>
    api.get<PaginatedResponse<User>>("/users", { params }),
  update: (userId: number, data: { is_allowed: boolean }) =>
    api.patch<User>(`/users/${userId}`, data),
};
