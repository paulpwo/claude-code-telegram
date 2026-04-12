import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { sessionsApi, Session } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const PAGE_SIZE = 20;

export function Sessions() {
  const [offset, setOffset] = useState(0);
  const navigate = useNavigate();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["sessions", offset],
    queryFn: () =>
      sessionsApi.list({ limit: PAGE_SIZE, offset }).then((r) => r.data),
    refetchInterval: 5_000,
  });

  if (isLoading) {
    return (
      <div className="p-8">
        <p className="text-muted-foreground">Loading sessions...</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="p-8">
        <p className="text-destructive">Failed to load sessions.</p>
      </div>
    );
  }

  const total = data?.total ?? 0;
  const hasNext = offset + PAGE_SIZE < total;
  const hasPrev = offset > 0;

  return (
    <div className="p-8 space-y-6">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Sessions</h2>
        <p className="text-muted-foreground">
          {total} total — auto-refreshes every 5s
        </p>
      </div>

      <div className="border rounded-md">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Session ID</TableHead>
              <TableHead>User</TableHead>
              <TableHead>Directory</TableHead>
              <TableHead>Messages</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Last Active</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(data?.items ?? []).map((session: Session) => (
              <TableRow
                key={session.session_id}
                className="cursor-pointer"
                onClick={() => navigate(`/admin/sessions/${session.session_id}`)}
              >
                <TableCell className="font-mono text-xs">
                  {session.session_id.slice(0, 12)}…
                </TableCell>
                <TableCell>{session.username ?? session.user_id}</TableCell>
                <TableCell className="font-mono text-xs max-w-xs truncate">
                  {session.directory}
                </TableCell>
                <TableCell>{session.message_count}</TableCell>
                <TableCell>
                  <Badge variant={session.is_active ? "success" : "secondary"}>
                    {session.is_active ? "active" : "closed"}
                  </Badge>
                </TableCell>
                <TableCell className="text-muted-foreground text-sm">
                  {session.last_active
                    ? new Date(session.last_active).toLocaleString()
                    : "—"}
                </TableCell>
              </TableRow>
            ))}
            {!data?.items.length && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                  No sessions found
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Showing {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
        </p>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setOffset(offset - PAGE_SIZE)}
            disabled={!hasPrev}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setOffset(offset + PAGE_SIZE)}
            disabled={!hasNext}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
