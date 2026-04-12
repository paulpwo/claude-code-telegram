import { useState } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { usersApi } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const PAGE_SIZE = 20;

export function Users() {
  const [offset, setOffset] = useState(0);
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["users", offset],
    queryFn: () =>
      usersApi.list({ limit: PAGE_SIZE, offset }).then((r) => r.data),
    refetchInterval: 30_000,
  });

  const toggleMutation = useMutation({
    mutationFn: ({ userId, isAllowed }: { userId: number; isAllowed: boolean }) =>
      usersApi.update(userId, { is_allowed: isAllowed }),
    // Optimistic update
    onMutate: async ({ userId, isAllowed }) => {
      await queryClient.cancelQueries({ queryKey: ["users", offset] });
      const previous = queryClient.getQueryData(["users", offset]);
      queryClient.setQueryData(["users", offset], (old: typeof data) => {
        if (!old) return old;
        return {
          ...old,
          items: old.items.map((u) =>
            u.user_id === userId ? { ...u, is_allowed: isAllowed } : u
          ),
        };
      });
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["users", offset], context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["users", offset] });
    },
  });

  if (isLoading) {
    return (
      <div className="p-8">
        <p className="text-muted-foreground">Loading users...</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="p-8">
        <p className="text-destructive">Failed to load users.</p>
      </div>
    );
  }

  const total = data?.total ?? 0;
  const hasNext = offset + PAGE_SIZE < total;
  const hasPrev = offset > 0;

  return (
    <div className="p-8 space-y-6">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Users</h2>
        <p className="text-muted-foreground">
          {total} total — auto-refreshes every 30s
        </p>
      </div>

      <div className="border rounded-md">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>User ID</TableHead>
              <TableHead>Username</TableHead>
              <TableHead>Name</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Last Active</TableHead>
              <TableHead>Total Cost</TableHead>
              <TableHead>Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.items.map((user) => (
              <TableRow key={user.user_id}>
                <TableCell className="font-mono text-sm">{user.user_id}</TableCell>
                <TableCell>{user.username ? `@${user.username}` : "—"}</TableCell>
                <TableCell>{user.first_name ?? "—"}</TableCell>
                <TableCell>
                  <Badge variant={user.is_allowed ? "success" : "destructive"}>
                    {user.is_allowed ? "allowed" : "blocked"}
                  </Badge>
                </TableCell>
                <TableCell className="text-muted-foreground text-sm">
                  {user.last_active
                    ? new Date(user.last_active).toLocaleString()
                    : "—"}
                </TableCell>
                <TableCell className="text-muted-foreground text-sm">
                  {user.total_cost !== undefined ? `$${user.total_cost.toFixed(4)}` : "—"}
                </TableCell>
                <TableCell>
                  <Button
                    variant={user.is_allowed ? "destructive" : "default"}
                    size="sm"
                    onClick={() =>
                      toggleMutation.mutate({
                        userId: user.user_id,
                        isAllowed: !user.is_allowed,
                      })
                    }
                    disabled={toggleMutation.isPending}
                  >
                    {user.is_allowed ? "Block" : "Allow"}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {!data?.items.length && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground py-8">
                  No users found
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
          <Button variant="outline" size="sm" onClick={() => setOffset(offset - PAGE_SIZE)} disabled={!hasPrev}>
            Previous
          </Button>
          <Button variant="outline" size="sm" onClick={() => setOffset(offset + PAGE_SIZE)} disabled={!hasNext}>
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
