import { useState } from "react";
import { Check, Copy, Share2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { canUseWebShare, getPipelineShareUrl } from "@/lib/share";
import { useAnalytics } from "@/hooks/useAnalytics";

type Variant = "icon" | "compact" | "full";

interface SharePipelineButtonProps {
  pipelineId: string;
  pipelineDisplayName?: string;
  variant?: Variant;
  className?: string;
}

const SharePipelineButton = ({
  pipelineId,
  pipelineDisplayName,
  variant = "icon",
  className,
}: SharePipelineButtonProps) => {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const { track } = useAnalytics();

  const shareUrl = getPipelineShareUrl(pipelineId);
  const shareTitle = pipelineDisplayName
    ? `${pipelineDisplayName} — Demo Hub`
    : "Demo Hub pipeline";
  const shareText = pipelineDisplayName
    ? `Check out this ${pipelineDisplayName} result on Demo Hub`
    : "Check out this pipeline result on Demo Hub";

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      toast.success("Link copied to clipboard");
      track({ name: "pipeline_share_copy", params: { pipeline_id: pipelineId } });
      window.setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error("Failed to copy share link:", error);
      toast.error("Failed to copy link");
    }
  };

  const handleNativeShare = async () => {
    if (!canUseWebShare()) return;
    try {
      await navigator.share({
        title: shareTitle,
        text: shareText,
        url: shareUrl,
      });
      track({
        name: "pipeline_share_native",
        params: { pipeline_id: pipelineId },
      });
      setOpen(false);
    } catch (error) {
      if ((error as DOMException)?.name === "AbortError") return;
      console.error("Native share failed:", error);
    }
  };

  const trigger = (() => {
    if (variant === "icon") {
      return (
        <Button
          size="sm"
          variant="secondary"
          className={cn("h-8 w-8 p-0 rounded-full shadow-lg", className)}
          title="Share pipeline"
          aria-label="Share pipeline"
          onClick={(e) => e.stopPropagation()}
        >
          <Share2 className="h-4 w-4" />
        </Button>
      );
    }
    if (variant === "compact") {
      return (
        <Button
          size="sm"
          variant="ghost"
          className={cn("h-7 gap-1.5 px-2 text-xs", className)}
          title="Share pipeline"
          onClick={(e) => e.stopPropagation()}
        >
          <Share2 className="h-3.5 w-3.5" />
          Share
        </Button>
      );
    }
    return (
      <Button
        variant="outline"
        size="sm"
        className={cn("gap-2", className)}
        onClick={(e) => e.stopPropagation()}
      >
        <Share2 className="h-4 w-4" />
        Share
      </Button>
    );
  })();

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          track({
            name: "pipeline_share_opened",
            params: { pipeline_id: pipelineId },
          });
        }
      }}
    >
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent
        className="sm:max-w-md"
        onClick={(e) => e.stopPropagation()}
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Share2 className="h-5 w-5 text-primary" />
            Share this pipeline
          </DialogTitle>
          <DialogDescription>
            Anyone with the link can view{pipelineDisplayName ? ` this ${pipelineDisplayName} result` : " this result"}
            .
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-center gap-2">
          <Input
            readOnly
            value={shareUrl}
            onFocus={(e) => e.currentTarget.select()}
            className="flex-1 text-xs sm:text-sm"
            aria-label="Share link"
          />
          <Button
            type="button"
            onClick={handleCopy}
            className="gap-1.5 shrink-0"
            variant={copied ? "secondary" : "default"}
          >
            {copied ? (
              <>
                <Check className="h-4 w-4" />
                Copied
              </>
            ) : (
              <>
                <Copy className="h-4 w-4" />
                Copy
              </>
            )}
          </Button>
        </div>

        {canUseWebShare() && (
          <Button
            type="button"
            variant="outline"
            onClick={handleNativeShare}
            className="w-full gap-2"
          >
            <Share2 className="h-4 w-4" />
            Share via…
          </Button>
        )}
      </DialogContent>
    </Dialog>
  );
};

export default SharePipelineButton;
