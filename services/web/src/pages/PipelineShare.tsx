import { useEffect, useMemo } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Loader2, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  pipelinesApi,
  type PublicPipeline,
  type UserPipelineItem,
} from "@/api";
import PipelineStatusBadge from "@/components/pipelines/PipelineStatusBadge";
import PipelineDetails, {
  getPipelineDisplayName,
} from "@/components/pipelines/details";
import SharePipelineButton from "@/components/SharePipelineButton";
import { getTryItHref } from "@/lib/share";
import { useAnalytics } from "@/hooks/useAnalytics";

const toUserPipelineItem = (p: PublicPipeline): UserPipelineItem => ({
  ...p,
  message: null,
  updated_at: p.created_at,
});

const formatDate = (iso: string): string => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
};

const PipelineShare = () => {
  const { pipelineId } = useParams<{ pipelineId: string }>();
  const navigate = useNavigate();
  const { track } = useAnalytics();

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["pipeline-public", pipelineId],
    enabled: !!pipelineId,
    queryFn: () => pipelinesApi.getPublic(pipelineId!),
    retry: false,
  });

  const displayName = useMemo(
    () => (data ? getPipelineDisplayName(data.pipeline_name) : ""),
    [data],
  );

  useEffect(() => {
    if (!data) return;
    track({
      name: "pipeline_share_viewed",
      params: { pipeline_id: data.id, pipeline_name: data.pipeline_name },
    });
  }, [data, track]);

  if (!pipelineId) {
    return null;
  }

  if (isLoading) {
    return (
      <main className="container mx-auto px-6 py-24 flex items-center justify-center min-h-[calc(100vh-8rem)]">
        <div className="flex items-center gap-3 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          Loading shared pipeline…
        </div>
      </main>
    );
  }

  if (isError || !data) {
    const notFound =
      (error as { status?: number } | undefined)?.status === 404;
    return (
      <main className="container mx-auto px-6 py-24 flex items-center justify-center min-h-[calc(100vh-8rem)]">
        <div className="max-w-md text-center space-y-4">
          <h1 className="text-2xl font-bold">
            {notFound ? "Pipeline not found" : "Could not load this pipeline"}
          </h1>
          <p className="text-sm text-muted-foreground">
            {notFound
              ? "The link may be wrong, or this pipeline was removed."
              : "Please try again in a moment."}
          </p>
          <Button onClick={() => navigate("/")} variant="outline">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back home
          </Button>
        </div>
      </main>
    );
  }

  const tryHref = getTryItHref(data.pipeline_name);

  return (
    <main className="container mx-auto px-3 sm:px-6 py-8 sm:py-12 min-h-[calc(100vh-8rem)]">
      <div className="mx-auto max-w-4xl space-y-6">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="space-y-1">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              Shared pipeline
            </p>
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">
              {displayName}
            </h1>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <PipelineStatusBadge status={data.status} />
              <span>•</span>
              <span>{formatDate(data.created_at)}</span>
            </div>
          </div>
          <SharePipelineButton
            pipelineId={data.id}
            pipelineDisplayName={displayName}
            variant="full"
          />
        </div>

        <div className="rounded-xl border border-border bg-card/50 p-4 sm:p-6 shadow-elegant">
          <PipelineDetails pipeline={toUserPipelineItem(data)} />
        </div>

        <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-2">
          <Button
            asChild
            size="lg"
            className="hover-glow text-base font-semibold px-8 shadow-elegant"
          >
            <Link
              to={tryHref}
              onClick={() =>
                track({
                  name: "pipeline_share_try_clicked",
                  params: {
                    pipeline_id: data.id,
                    pipeline_name: data.pipeline_name,
                  },
                })
              }
            >
              <Sparkles className="mr-2 h-5 w-5" />
              Try it yourself
            </Link>
          </Button>
        </div>
      </div>
    </main>
  );
};

export default PipelineShare;
