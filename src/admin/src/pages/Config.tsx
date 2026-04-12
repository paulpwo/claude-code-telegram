import { useQuery } from "@tanstack/react-query";
import { configApi } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export function Config() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["config"],
    queryFn: () => configApi.get().then((r) => r.data),
    // Static — no polling
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  if (isLoading) {
    return (
      <div className="p-8">
        <p className="text-muted-foreground">Loading configuration...</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="p-8">
        <p className="text-destructive">Failed to load configuration.</p>
      </div>
    );
  }

  const entries = Object.entries(data ?? {});

  return (
    <div className="p-8 space-y-6">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Configuration</h2>
        <p className="text-muted-foreground">
          Read-only settings dump — secrets are masked
        </p>
      </div>

      <div className="border rounded-md">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Key</TableHead>
              <TableHead>Value</TableHead>
              <TableHead>Type</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.map(([key, value]) => {
              const isMasked = value === "***";
              const displayValue =
                typeof value === "object" && value !== null
                  ? JSON.stringify(value)
                  : String(value ?? "—");

              return (
                <TableRow key={key}>
                  <TableCell className="font-mono text-sm font-medium">{key}</TableCell>
                  <TableCell>
                    {isMasked ? (
                      <span className="text-muted-foreground italic">***</span>
                    ) : (
                      <span className="font-mono text-sm">{displayValue}</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {isMasked ? (
                      <Badge variant="destructive">secret</Badge>
                    ) : (
                      <Badge variant="outline">{typeof value}</Badge>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
            {!entries.length && (
              <TableRow>
                <TableCell colSpan={3} className="text-center text-muted-foreground py-8">
                  No configuration available
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
