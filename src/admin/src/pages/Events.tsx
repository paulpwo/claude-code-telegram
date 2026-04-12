import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { eventsApi, WebhookEvent, AuditEvent } from "@/lib/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const PAGE_SIZE = 20;

function WebhooksTab() {
  const [offset, setOffset] = useState(0);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["webhooks", offset],
    queryFn: () =>
      eventsApi.getWebhooks({ limit: PAGE_SIZE, offset }).then((r) => r.data),
    refetchInterval: 5_000,
  });

  if (isLoading) return <p className="text-muted-foreground py-4">Loading...</p>;
  if (isError) return <p className="text-destructive py-4">Failed to load webhook events.</p>;

  const total = data?.total ?? 0;

  return (
    <div className="space-y-4">
      <div className="border rounded-md">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>ID</TableHead>
              <TableHead>Provider</TableHead>
              <TableHead>Event Type</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Received At</TableHead>
              <TableHead>Payload Preview</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(data?.items ?? []).map((event: WebhookEvent) => (
              <TableRow key={event.id}>
                <TableCell className="font-mono text-xs">{event.id}</TableCell>
                <TableCell>
                  <Badge variant="outline">{event.provider}</Badge>
                </TableCell>
                <TableCell>{event.event_type}</TableCell>
                <TableCell>
                  <Badge variant={event.status === "processed" ? "success" : "warning"}>
                    {event.status}
                  </Badge>
                </TableCell>
                <TableCell className="text-muted-foreground text-sm">
                  {new Date(event.received_at).toLocaleString()}
                </TableCell>
                <TableCell className="font-mono text-xs max-w-xs truncate">
                  {event.payload_preview}
                </TableCell>
              </TableRow>
            ))}
            {!data?.items.length && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                  No webhook events found
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {total} total events
        </p>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setOffset(offset - PAGE_SIZE)} disabled={offset === 0}>
            Previous
          </Button>
          <Button variant="outline" size="sm" onClick={() => setOffset(offset + PAGE_SIZE)} disabled={offset + PAGE_SIZE >= total}>
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}

function AuditLogTab() {
  const [offset, setOffset] = useState(0);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["audit-log", offset],
    queryFn: () =>
      eventsApi.getAuditLog({ limit: PAGE_SIZE, offset }).then((r) => r.data),
    refetchInterval: 5_000,
  });

  if (isLoading) return <p className="text-muted-foreground py-4">Loading...</p>;
  if (isError) return <p className="text-destructive py-4">Failed to load audit log.</p>;

  const total = data?.total ?? 0;

  return (
    <div className="space-y-4">
      <div className="border rounded-md">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>ID</TableHead>
              <TableHead>User</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>Resource</TableHead>
              <TableHead>Details</TableHead>
              <TableHead>Created At</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(data?.items ?? []).map((event: AuditEvent) => (
              <TableRow key={event.id}>
                <TableCell className="font-mono text-xs">{event.id}</TableCell>
                <TableCell>{event.username ?? event.user_id}</TableCell>
                <TableCell>
                  <Badge variant="secondary">{event.action}</Badge>
                </TableCell>
                <TableCell className="font-mono text-xs">{event.resource ?? "—"}</TableCell>
                <TableCell className="text-sm max-w-xs truncate">{event.details ?? "—"}</TableCell>
                <TableCell className="text-muted-foreground text-sm">
                  {new Date(event.created_at).toLocaleString()}
                </TableCell>
              </TableRow>
            ))}
            {!data?.items.length && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                  No audit events found
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{total} total events</p>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setOffset(offset - PAGE_SIZE)} disabled={offset === 0}>
            Previous
          </Button>
          <Button variant="outline" size="sm" onClick={() => setOffset(offset + PAGE_SIZE)} disabled={offset + PAGE_SIZE >= total}>
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}

export function Events() {
  return (
    <div className="p-8 space-y-6">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Events</h2>
        <p className="text-muted-foreground">Webhooks and audit log — auto-refreshes every 5s</p>
      </div>

      <Tabs defaultValue="webhooks">
        <TabsList>
          <TabsTrigger value="webhooks">Webhooks</TabsTrigger>
          <TabsTrigger value="audit">Audit Log</TabsTrigger>
        </TabsList>
        <TabsContent value="webhooks">
          <WebhooksTab />
        </TabsContent>
        <TabsContent value="audit">
          <AuditLogTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
