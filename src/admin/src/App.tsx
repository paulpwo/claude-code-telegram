import { Routes, Route, Navigate } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Login } from "@/pages/Login";
import { Dashboard } from "@/pages/Dashboard";
import { Sessions } from "@/pages/Sessions";
import { SessionDetail } from "@/pages/SessionDetail";
import { Events } from "@/pages/Events";
import { Crons } from "@/pages/Crons";
import { Config } from "@/pages/Config";
import { Users } from "@/pages/Users";

export default function App() {
  return (
    <Routes>
      {/* Public routes */}
      <Route path="/admin/login" element={<Login />} />

      {/* Protected routes with Layout */}
      <Route
        path="/admin"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="sessions" element={<Sessions />} />
        <Route path="sessions/:id" element={<SessionDetail />} />
        <Route path="events" element={<Events />} />
        <Route path="crons" element={<Crons />} />
        <Route path="config" element={<Config />} />
        <Route path="users" element={<Users />} />
      </Route>

      {/* Fallback */}
      <Route path="*" element={<Navigate to="/admin/" replace />} />
    </Routes>
  );
}
