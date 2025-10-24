import { useCallback, useState } from "react";
import { Upload, Image, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

interface UploadDropzoneProps {
  onFileSelect: (file: File | null) => void;
  selectedFile: File | null;
}

const UploadDropzone = ({ onFileSelect, selectedFile }: UploadDropzoneProps) => {
  const [isDragging, setIsDragging] = useState(false);

  const validateFile = (file: File): boolean => {
    const validTypes = ["image/jpeg", "image/png", "image/webp"];
    const maxSize = 5 * 1024 * 1024; // 5MB

    if (!validTypes.includes(file.type)) {
      toast.error("Please upload a valid image file (JPEG, PNG, or WebP)");
      return false;
    }

    if (file.size > maxSize) {
      toast.error("File size must be less than 5MB");
      return false;
    }

    return true;
  };

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setIsDragging(false);

      const file = e.dataTransfer.files[0];
      if (file && validateFile(file)) {
        onFileSelect(file);
        //toast.success("Image uploaded successfully");
      }
    },
    [onFileSelect]
  );

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file && validateFile(file)) {
      onFileSelect(file);
      //toast.success("Image uploaded successfully");
    }
  };

  const handleRemove = () => {
    onFileSelect(null);
  };

  return (
    <div className="w-full max-w-2xl mx-auto">
      {!selectedFile ? (
        <div
          onDrop={handleDrop}
          onDragOver={(e) => {
            e.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          className={`relative overflow-hidden rounded-xl border-2 border-dashed p-12 transition-all ${
            isDragging
              ? "border-primary bg-primary/5"
              : "border-border bg-card hover:border-primary/50"
          }`}
        >
          <input
            type="file"
            id="file-upload"
            className="absolute inset-0 cursor-pointer opacity-0"
            accept="image/jpeg,image/png,image/webp"
            onChange={handleFileInput}
          />
          <div className="flex flex-col items-center gap-4 text-center">
            <div className="rounded-full bg-primary/10 p-4">
              <Upload className="h-8 w-8 text-primary" />
            </div>
            <div>
              <p className="text-lg font-medium">
                Drop your photo here, or{" "}
                <label
                  htmlFor="file-upload"
                  className="cursor-pointer text-primary underline-offset-4 hover:underline"
                >
                  browse
                </label>
              </p>
              <p className="mt-2 text-sm text-muted-foreground">
                JPEG, PNG, or WebP · Max 5MB
              </p>
            </div>
          </div>
        </div>
      ) : (
        <div className="card-gradient relative overflow-hidden rounded-xl border border-border p-6">
          <div className="flex items-center gap-4">
            <div className="rounded-lg bg-primary/10 p-3">
              <Image className="h-6 w-6 text-primary" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="truncate font-medium">{selectedFile.name}</p>
              <p className="text-sm text-muted-foreground">
                {(selectedFile.size / 1024 / 1024).toFixed(2)} MB
              </p>
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={handleRemove}
              className="hover:bg-destructive/10 hover:text-destructive"
            >
              <X className="h-5 w-5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};

export default UploadDropzone;
