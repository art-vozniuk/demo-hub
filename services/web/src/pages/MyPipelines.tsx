import { Fragment, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
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
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";
import { cn } from "@/lib/utils";
import { pipelinesApi, type UserPipelineItem } from "@/api";
import PipelineStatusBadge from "@/components/pipelines/PipelineStatusBadge";
import PipelineDetails, {
  getPipelineDisplayName,
} from "@/components/pipelines/details";
import SharePipelineButton from "@/components/SharePipelineButton";

const PAGE_SIZE = 50;
const POLL_INTERVAL_MS = 3000;

const buildPageList = (current: number, total: number): (number | "ellipsis")[] => {
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }
  const pages = new Set<number>([1, total, current, current - 1, current + 1]);
  const sorted = [...pages].filter((p) => p >= 1 && p <= total).sort((a, b) => a - b);
  const result: (number | "ellipsis")[] = [];
  for (let i = 0; i < sorted.length; i += 1) {
    if (i > 0 && sorted[i] - sorted[i - 1] > 1) result.push("ellipsis");
    result.push(sorted[i]);
  }
  return result;
};

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
  const [searchParams, setSearchParams] = useSearchParams();

  const pageParam = Number.parseInt(searchParams.get("page") ?? "1", 10);
  const page = Number.isFinite(pageParam) && pageParam >= 1 ? pageParam : 1;
  const offset = (page - 1) * PAGE_SIZE;

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

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: ["my-pipelines", user?.id, page],
    enabled: !!user,
    queryFn: () => pipelinesApi.getMine(PAGE_SIZE, offset),
    refetchInterval: (query) => {
      const items = query.state.data?.pipelines ?? [];
      return hasInFlight(items) ? POLL_INTERVAL_MS : false;
    },
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  });

  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  useEffect(() => {
    if (data && page > totalPages) {
      const next = new URLSearchParams(searchParams);
      if (totalPages <= 1) next.delete("page");
      else next.set("page", String(totalPages));
      setSearchParams(next, { replace: true });
    }
  }, [data, page, totalPages, searchParams, setSearchParams]);

  const goToPage = (target: number) => {
    const clamped = Math.min(Math.max(1, target), totalPages);
    if (clamped === page) return;
    const next = new URLSearchParams(searchParams);
    if (clamped === 1) next.delete("page");
    else next.set("page", String(clamped));
    setSearchParams(next);
    setExpanded({});
    if (typeof window !== "undefined") {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  };

  const pipelines = useMemo(() => data?.pipelines ?? [], [data?.pipelines]);
  const inFlightCount = useMemo(
    () =>
      pipelines.filter((p) => p.status === "PENDING" || p.status === "RUNNING")
        .length,
    [pipelines],
  );

  useEffect(() => {
    if (pipelines.length === 0) return;
    setExpanded((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const p of pipelines) {
        if (!(p.id in next)) {
          next[p.id] = true;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [pipelines]);

  const toggleRow = (id: string) =>
    setExpanded((prev) => ({ ...prev, [id]: !(prev[id] ?? true) }));

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
        <div
          className={cn(
            "rounded-md border border-border overflow-hidden transition-opacity",
            isFetching && "opacity-70",
          )}
        >
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
                const isOpen = expanded[p.id] ?? true;
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
                          {p.status === "COMPLETED" && (
                            <div
                              className="mt-3 flex justify-end"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <SharePipelineButton
                                pipelineId={p.id}
                                pipelineDisplayName={getPipelineDisplayName(
                                  p.pipeline_name,
                                )}
                                variant="full"
                              />
                            </div>
                          )}
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

      {data && total > 0 && (
        <div className="mt-4 flex flex-col items-center gap-3 sm:flex-row sm:justify-between">
          <p className="text-xs text-muted-foreground">
            Showing {offset + 1}–{offset + pipelines.length} of {total}.
          </p>
          {totalPages > 1 && (
            <Pagination className="mx-0 w-auto justify-end">
              <PaginationContent>
                <PaginationItem>
                  <PaginationPrevious
                    href="#"
                    aria-disabled={page <= 1}
                    className={cn(
                      page <= 1 && "pointer-events-none opacity-50",
                    )}
                    onClick={(e) => {
                      e.preventDefault();
                      goToPage(page - 1);
                    }}
                  />
                </PaginationItem>
                {buildPageList(page, totalPages).map((entry, idx) =>
                  entry === "ellipsis" ? (
                    <PaginationItem key={`ellipsis-${idx}`}>
                      <PaginationEllipsis />
                    </PaginationItem>
                  ) : (
                    <PaginationItem key={entry}>
                      <PaginationLink
                        href="#"
                        isActive={entry === page}
                        onClick={(e) => {
                          e.preventDefault();
                          goToPage(entry);
                        }}
                      >
                        {entry}
                      </PaginationLink>
                    </PaginationItem>
                  ),
                )}
                <PaginationItem>
                  <PaginationNext
                    href="#"
                    aria-disabled={page >= totalPages}
                    className={cn(
                      page >= totalPages && "pointer-events-none opacity-50",
                    )}
                    onClick={(e) => {
                      e.preventDefault();
                      goToPage(page + 1);
                    }}
                  />
                </PaginationItem>
              </PaginationContent>
            </Pagination>
          )}
        </div>
      )}
    </div>
  );
};

export default MyPipelines;
