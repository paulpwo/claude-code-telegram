import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { cronsApi } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Pause, Play, Zap } from "lucide-react";

export function Crons() {
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["crons"],
    queryFn: () => cronsApi.list().then((r) => r.data),
    refetchInterval: 30_000,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["crons"] });

  const pauseMutation = useMutation({
    mutationFn: (id: string) => cronsApi.pause(id),
    onSuccess: invalidate,
  });

  const resumeMutation = useMutation({
    mutationFn: (id: string) => cronsApi.resume(id),
    onSuccess: invalidate,
  });

  const triggerMutation = useMutation({
    mutationFn: (id: string) => cronsApi.trigger(id),
    onSuccess: invalidate,
  });

  if (isLoading) {
    return (
      <div className="p-8">
        <p className="text-muted-foreground">Loading scheduled jobs...</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="p-8">
        <p className="text-destructive">
          Failed to load cron jobs. The scheduler may not be running.
        </p>
      </div>
    );
  }

  return (
    <div className="p-8 space-y-6">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Scheduled Jobs</h2>
        <p className="text-muted-foreground">
          {data?.length ?? 0} jobs — auto-refreshes every 30s
        </p>
      </div>

      <div className="border rounded-md">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Job ID</TableHead>
              <TableHead>Name</TableHead>
              <TableHead>Trigger</TableHead>
              <TableHead>Next Run</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.map((job) => (
              <TableRow key={job.id}>
                <TableCell className="font-mono text-xs">{job.id}</TableCell>
                <TableCell className="font-medium">{job.name}</TableCell>
                <TableCell className="font-mono text-xs">{job.trigger}</TableCell>
                <TableCell className="text-muted-foreground text-sm">
                  {job.next_run_time
                    ? new Date(job.next_run_time).toLocaleString()
                    : "—"}
                </TableCell>
                <TableCell>
                  <Badge variant={job.is_paused ? "warning" : "success"}>
                    {job.is_paused ? "paused" : "running"}
                  </Badge>
                </TableCell>
                <TableCell>
                  <div className="flex gap-2">
                    {job.is_paused ? (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => resumeMutation.mutate(job.id)}
                        disabled={resumeMutation.isPending}
                        title="Resume"
                      >
                        <Play className="h-3 w-3 mr-1" />
                        Resume
                      </Button>
                    ) : (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => pauseMutation.mutate(job.id)}
                        disabled={pauseMutation.isPending}
                        title="Pause"
                      >
                        <Pause className="h-3 w-3 mr-1" />
                        Pause
                      </Button>
                    )}
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => triggerMutation.mutate(job.id)}
                      disabled={triggerMutation.isPending}
                      title="Trigger now"
                    >
                      <Zap className="h-3 w-3 mr-1" />
                      Trigger
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
            {!data?.length && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                  No scheduled jobs
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
