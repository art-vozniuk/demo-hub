import { useState, useEffect } from "react";
import { Loader2, Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
} from "@/components/ui/dialog";
import {toast} from "sonner";

interface GenerationCardProps {
  imageUrl: string;
  isProcessing: boolean;
  generatedImage?: string;
  templateName?: string | null;
  onAnimationComplete?: () => void;
}

const GenerationCard = ({
  imageUrl,
  isProcessing,
  generatedImage,
  templateName,
  onAnimationComplete,
}: GenerationCardProps) => {
  const [blurAmount, setBlurAmount] = useState(0);
  const [displayImage, setDisplayImage] = useState(imageUrl);
  const [isImageLoaded, setIsImageLoaded] = useState(false);
  const [showSpinner, setShowSpinner] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);

  useEffect(() => {
    if (isProcessing) {
      setBlurAmount(30);
      setIsImageLoaded(false);
      setShowSpinner(true);
    } else if (generatedImage) {
      // Preload the generated image
      const img = new Image();
      img.onload = () => {
        // Once loaded, swap to the blurred result image
        setDisplayImage(generatedImage);
        setIsImageLoaded(true);
      };
      img.src = generatedImage;
    } else {
      // Processing stopped without a result (error case) - reset to original
      setBlurAmount(0);
      setShowSpinner(false);
      setDisplayImage(imageUrl);
    }
  }, [isProcessing, generatedImage, imageUrl]);

  useEffect(() => {
    if (isImageLoaded && generatedImage) {
      // Slowly unblur the image after it's loaded and swapped
      const unblurInterval = setInterval(() => {
        setBlurAmount((prev) => {
          if (prev <= 0) {
            clearInterval(unblurInterval);
            setShowSpinner(false);
            onAnimationComplete?.();
            return 0;
          }
          return prev - 1;
        });
      }, 1);

      return () => clearInterval(unblurInterval);
    }
  }, [isImageLoaded, generatedImage, onAnimationComplete]);

  const handleDownload = async (e?: React.MouseEvent) => {
    e?.stopPropagation();
    if (!generatedImage) return;

    try {
      const response = await fetch(generatedImage);
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `meme-fusion-${templateName || 'result'}-${Date.now()}.jpg`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Failed to download image:', error);
      toast.error("Failed to download image: " + error);
    }
  };

  const handleImageClick = () => {
    if (generatedImage && blurAmount === 0) {
      setIsModalOpen(true);
    }
  };

  const handleModalImageClick = () => {
    setIsModalOpen(false);
  };

  return (
    <>
      <div className="group relative overflow-hidden rounded-xl border border-border shadow-elegant transition-all hover:border-primary/50 bg-card">
        <div 
          className="aspect-square relative overflow-hidden cursor-pointer"
          onClick={handleImageClick}
        >
          <img
            src={displayImage}
            alt={templateName || "Template"}
            className="h-full w-full object-cover transition-all duration-700"
            style={{
              filter: `blur(${blurAmount}px)`,
            }}
          />
        
        {showSpinner && (
          <div className="absolute inset-0 flex items-center justify-center bg-background/10 backdrop-blur-sm">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        )}

          {generatedImage && blurAmount === 0 && (
            <div className="absolute top-2 right-2" onClick={(e) => e.stopPropagation()}>
              <Button
                onClick={handleDownload}
                size="sm"
                variant="secondary"
                className="h-8 w-8 p-0 rounded-full shadow-lg"
                title="Download image"
              >
                <Download className="h-4 w-4" />
              </Button>
            </div>
          )}

          {templateName && (
            <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 via-black/50 to-transparent p-3">
              <p className="text-white text-sm font-medium truncate">
                {templateName}
              </p>
            </div>
          )}
        </div>
      </div>

      <Dialog open={isModalOpen} onOpenChange={setIsModalOpen}>
        <DialogContent className="max-w-[98vw] max-h-[98vh] w-fit h-fit p-0 bg-transparent border-none">
          <div 
            className="relative cursor-pointer flex items-center justify-center"
            onClick={handleModalImageClick}
          >
            <img
              src={generatedImage || displayImage}
              alt={templateName || "Template"}
              className="max-w-[98vw] max-h-[98vh] w-auto h-auto object-contain rounded-lg"
            />
            <div className="absolute top-4 right-4" onClick={(e) => e.stopPropagation()}>
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
    </>
  );
};

export default GenerationCard;

