import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { sessionsApi } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ArrowLeft } from "lucide-react";

export function SessionDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["session", id],
    queryFn: () => sessionsApi.get(id!).then((r) => r.data),
    refetchInterval: 10_000,
    enabled: !!id,
  });

  if (isLoading) {
    return (
      <div className="p-8">
        <p className="text-muted-foreground">Loading session...</p>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="p-8">
        <p className="text-destructive">Session not found.</p>
      </div>
    );
  }

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" onClick={() => navigate(-1)}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Session Detail</h2>
          <p className="font-mono text-xs text-muted-foreground">{data.session_id}</p>
        </div>
        <Badge variant={data.is_active ? "success" : "secondary"}>
          {data.is_active ? "active" : "closed"}
        </Badge>
      </div>

      <div className="grid gap-4 grid-cols-1 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">User</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-semibold">{data.username ?? data.user_id}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Directory</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-mono text-sm truncate">{data.directory}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Messages</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{data.message_count}</p>
          </CardContent>
        </Card>
      </div>

      <div className="space-y-2">
        <h3 className="font-semibold">Message Thread</h3>
        <div className="space-y-3 max-h-[600px] overflow-y-auto">
          {data.messages?.map((msg) => (
            <div
              key={msg.id}
              className={`rounded-lg p-4 ${
                msg.role === "user"
                  ? "bg-primary/10 ml-8"
                  : "bg-muted mr-8"
              }`}
            >
              <div className="flex justify-between items-center mb-1">
                <span className="text-xs font-semibold uppercase text-muted-foreground">
                  {msg.role}
                </span>
                <span className="text-xs text-muted-foreground">
                  {new Date(msg.timestamp).toLocaleString()}
                </span>
              </div>
              <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
              {(msg.tokens || msg.cost) && (
                <div className="mt-2 flex gap-3 text-xs text-muted-foreground">
                  {msg.tokens && <span>{msg.tokens} tokens</span>}
                  {msg.cost && <span>${msg.cost.toFixed(6)}</span>}
                </div>
              )}
            </div>
          ))}
          {!data.messages?.length && (
            <p className="text-muted-foreground text-sm">No messages in this session.</p>
          )}
        </div>
      </div>
    </div>
  );
}
