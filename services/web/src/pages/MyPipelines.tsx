import { Fragment, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { useAnalytics } from "@/hooks/useAnalytics";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { pipelinesApi, type UserPipelineItem } from "@/api";
import PipelineStatusBadge from "@/components/pipelines/PipelineStatusBadge";
import PipelineDetails, {
  getPipelineDisplayName,
} from "@/components/pipelines/details";

const PAGE_SIZE = 50;
const POLL_INTERVAL_MS = 3000;

const formatRelativeTime = (iso: string) => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const diffMs = Date.now() - d.getTime();
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  if (diffDay < 14) return `${diffDay}d ago`;
  return d.toLocaleDateString();
};

const hasInFlight = (pipelines: UserPipelineItem[]) =>
  pipelines.some((p) => p.status === "PENDING" || p.status === "RUNNING");

const MyPipelines = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, loading: authLoading } = useAuth();
  const { track } = useAnalytics();
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      navigate(
        `/auth?redirect=${encodeURIComponent(location.pathname + location.search)}`,
        { replace: true },
      );
    }
  }, [authLoading, user, navigate, location.pathname, location.search]);

  useEffect(() => {
    if (user) track({ name: "my_pipelines_viewed", params: {} });
  }, [user, track]);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["my-pipelines", user?.id],
    enabled: !!user,
    queryFn: () => pipelinesApi.getMine(PAGE_SIZE, 0),
    refetchInterval: (query) => {
      const items = query.state.data?.pipelines ?? [];
      return hasInFlight(items) ? POLL_INTERVAL_MS : false;
    },
    refetchOnWindowFocus: true,
  });

  const pipelines = useMemo(() => data?.pipelines ?? [], [data?.pipelines]);
  const inFlightCount = useMemo(
    () =>
      pipelines.filter((p) => p.status === "PENDING" || p.status === "RUNNING")
        .length,
    [pipelines],
  );

  const toggleRow = (id: string) =>
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));

  if (authLoading || !user) {
    return null;
  }

  return (
    <div className="container mx-auto px-3 sm:px-6 py-8">
      <div className="mb-6">
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">
          My Pipelines
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          History of pipelines you have queued.
          {inFlightCount > 0 && (
            <span className="ml-2 text-primary">
              {inFlightCount} in progress
            </span>
          )}
        </p>
      </div>

      {isLoading ? (
        <div className="py-12 text-center text-sm text-muted-foreground">
          Loading…
        </div>
      ) : isError ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          Failed to load pipelines.
        </div>
      ) : pipelines.length === 0 ? (
        <div className="rounded-md border border-border px-4 py-12 text-center text-sm text-muted-foreground">
          You haven't run any pipelines yet.
        </div>
      ) : (
        <div className="rounded-md border border-border overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="hidden sm:table-cell">Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pipelines.map((p) => {
                const isOpen = !!expanded[p.id];
                return (
                  <Fragment key={p.id}>
                    <TableRow
                      onClick={() => toggleRow(p.id)}
                      className="cursor-pointer"
                    >
                      <TableCell className="w-8">
                        {isOpen ? (
                          <ChevronDown className="h-4 w-4 text-muted-foreground" />
                        ) : (
                          <ChevronRight className="h-4 w-4 text-muted-foreground" />
                        )}
                      </TableCell>
                      <TableCell className="font-medium">
                        {getPipelineDisplayName(p.pipeline_name)}
                      </TableCell>
                      <TableCell>
                        <PipelineStatusBadge status={p.status} />
                      </TableCell>
                      <TableCell className="hidden sm:table-cell text-sm text-muted-foreground">
                        {formatRelativeTime(p.created_at)}
                      </TableCell>
                    </TableRow>
                    {isOpen && (
                      <TableRow className={cn("bg-muted/20 hover:bg-muted/20")}>
                        <TableCell colSpan={4} className="p-4">
                          {p.status === "FAILED" && p.message && (
                            <div className="mb-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                              {p.message}
                            </div>
                          )}
                          <PipelineDetails pipeline={p} />
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      {data && data.total > pipelines.length && (
        <p className="mt-3 text-xs text-muted-foreground">
          Showing {pipelines.length} of {data.total}.
        </p>
      )}
    </div>
  );
};

export default MyPipelines;
