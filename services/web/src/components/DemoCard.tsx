import { useState, useEffect } from "react";
import { Loader2 } from "lucide-react";
import { Progress } from "@/components/ui/progress";

interface DemoCardProps {
  index: number;
  isProcessing: boolean;
  previewImage: string;
  generatedImage?: string;
}

const DemoCard = ({
  index,
  isProcessing,
  previewImage,
  generatedImage,
}: DemoCardProps) => {
  const [progress, setProgress] = useState(0);
  const [blurAmount, setBlurAmount] = useState(0);

  useEffect(() => {
    if (isProcessing) {
      // Initial blur to 90%
      setBlurAmount(20);
      setProgress(0);

      const blurInterval = setInterval(() => {
        setBlurAmount((prev) => Math.max(5, prev - 1));
      }, 100);

      const progressInterval = setInterval(() => {
        setProgress((prev) => {
          if (prev >= 90) {
            clearInterval(progressInterval);
            return 90;
          }
          return prev + 10;
        });
      }, 200);

      return () => {
        clearInterval(blurInterval);
        clearInterval(progressInterval);
      };
    } else if (generatedImage) {
      setProgress(100);
      setBlurAmount(0);
    }
  }, [isProcessing, generatedImage]);

  return (
    <div className="card-gradient group relative overflow-hidden rounded-xl border border-border shadow-elegant transition-all hover:border-primary/50">
      <div className="aspect-square relative overflow-hidden">
        <img
          src={generatedImage || previewImage}
          alt={`Demo ${index + 1}`}
          className="h-full w-full object-cover transition-all duration-700"
          style={{
            filter: `blur(${blurAmount}px)`,
          }}
        />
        
        {isProcessing && (
          <div className="absolute inset-0 flex items-center justify-center bg-background/10 backdrop-blur-sm">
            <div className="w-full max-w-[80%] space-y-4 px-4">
              <Loader2 className="mx-auto h-8 w-8 animate-spin text-primary" />
              <Progress value={progress} className="h-1" />
            </div>
          </div>
        )}

        {generatedImage && !isProcessing && (
          <div className="absolute inset-0 bg-gradient-to-t from-background/80 to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
        )}
      </div>
    </div>
  );
};

export default DemoCard;
