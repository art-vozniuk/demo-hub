import { useState } from "react";
import { Download } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";

interface PipelinePreviewImageProps {
  url: string;
  label: string;
  downloadName?: string;
}

const PipelinePreviewImage = ({
  url,
  label,
  downloadName,
}: PipelinePreviewImageProps) => {
  const [open, setOpen] = useState(false);

  const handleDownload = async (e?: React.MouseEvent) => {
    e?.stopPropagation();
    try {
      const response = await fetch(url);
      const blob = await response.blob();
      const objectUrl = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      const extFromUrl = url.split("?")[0].split(".").pop() || "jpg";
      link.download = `${downloadName || label.toLowerCase()}-${Date.now()}.${extFromUrl}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(objectUrl);
    } catch (error) {
      console.error("Failed to download image:", error);
      toast.error("Failed to download image");
    }
  };

  return (
    <div className="space-y-1.5">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className="group relative overflow-hidden rounded-md border border-border bg-card">
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="block w-full focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          aria-label={`Open ${label} fullscreen`}
        >
          <img
            src={url}
            alt={label}
            className="h-32 w-32 sm:h-40 sm:w-40 object-cover"
            loading="lazy"
            decoding="async"
          />
        </button>
        <div
          className="absolute top-1.5 right-1.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100"
          onClick={(e) => e.stopPropagation()}
        >
          <Button
            onClick={handleDownload}
            size="sm"
            variant="secondary"
            className="h-7 w-7 p-0 rounded-full shadow-lg"
            title="Download image"
          >
            <Download className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          className="max-w-[98vw] max-h-[98vh] w-fit h-fit p-0 bg-transparent border-none"
          hideClose
        >
          <div
            className="relative cursor-pointer flex items-center justify-center"
            onClick={() => setOpen(false)}
          >
            <img
              src={url}
              alt={label}
              className="max-w-[98vw] max-h-[98vh] w-auto h-auto object-contain rounded-lg"
            />
            <div
              className="absolute top-4 right-4"
              onClick={(e) => e.stopPropagation()}
            >
              <Button
                onClick={handleDownload}
                size="sm"
                variant="secondary"
                className="h-10 w-10 p-0 rounded-full shadow-lg"
                title="Download image"
              >
                <Download className="h-5 w-5" />
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default PipelinePreviewImage;
