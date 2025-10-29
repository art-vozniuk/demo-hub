import { useState, useEffect, useRef, useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Sparkles, ArrowLeft } from "lucide-react";
import type { RecastTemplateRead } from "@/api";
import { pipelinesApi, type PipelineStatusItem, ApiError } from "@/api";
import { uploadToS3, parseS3Url, getFileExtension } from "@/lib/s3";
import UploadDropzone from "@/components/UploadDropzone";
import GenerationCard from "@/components/GenerationCard";
import { toast } from "sonner";
import { v4 as uuidv4 } from 'uuid';
import { useAuth } from "@/contexts/AuthContext";
import { useAnalytics } from "@/hooks/useAnalytics";

interface GenerationState {
  selectedTemplates: RecastTemplateRead[];
  selectedFile: File | null;
  uploadedImageS3?: { bucket: string; key: string } | null;
  autoGenerate?: boolean;
}

const saveGenerationState = async (state: GenerationState): Promise<void> => {
  if (state.selectedFile) {
    return new Promise((resolve) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        const dataToSave = {
          selectedTemplates: state.selectedTemplates,
          fileDataUrl: reader.result,
          fileName: state.selectedFile?.name,
          fileType: state.selectedFile?.type,
          uploadedImageS3: state.uploadedImageS3,
        };
        sessionStorage.setItem('generation-state', JSON.stringify(dataToSave));
        console.log("Saved generation state to sessionStorage:", state.selectedTemplates.length, "templates");
        resolve();
      };
      reader.readAsDataURL(state.selectedFile);
    });
  }
};

const loadGenerationState = (): GenerationState | null => {
  const saved = sessionStorage.getItem('generation-state');
  if (!saved) return null;

  try {
    const data = JSON.parse(saved);
    
    if (data.fileDataUrl) {
      const byteString = atob(data.fileDataUrl.split(',')[1]);
      const mimeString = data.fileDataUrl.split(',')[0].split(':')[1].split(';')[0];
      const ab = new ArrayBuffer(byteString.length);
      const ia = new Uint8Array(ab);
      for (let i = 0; i < byteString.length; i++) {
        ia[i] = byteString.charCodeAt(i);
      }
      const blob = new Blob([ab], { type: mimeString });
      const file = new File([blob], data.fileName, { type: data.fileType });
      
      return {
        selectedTemplates: data.selectedTemplates,
        selectedFile: file,
        uploadedImageS3: data.uploadedImageS3 || null,
      };
    }
    
    return null;
  } catch (error) {
    console.error('Failed to restore generation state:', error);
    toast.error("Failed to restore generation state: " + error);
    return null;
  }
};

const clearGenerationState = () => {
  sessionStorage.removeItem('generation-state');
};

const FaceFusionGenerate = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();
  const { track } = useAnalytics();
  
  const [initialState] = useState(() => {
    const savedState = loadGenerationState();
    const templates = location.state?.selectedTemplates || savedState?.selectedTemplates || [];
    
    if (location.state?.selectedTemplates) {
      console.log("Loading templates from location.state");
    } else if (savedState?.selectedTemplates) {
      console.log("Loading templates from sessionStorage:", savedState.selectedTemplates.length);
    } else {
      console.log("No templates found");
    }
    
    return {
      templates,
      file: savedState?.selectedFile || null,
      s3Upload: savedState?.uploadedImageS3 || null,
    };
  });

  const [selectedTemplates] = useState<RecastTemplateRead[]>(initialState.templates);
  const [selectedFile, setSelectedFile] = useState<File | null>(initialState.file);
  const [uploadedImageS3, setUploadedImageS3] = useState<{ bucket: string; key: string } | null>(initialState.s3Upload);
  const [isUploading, setIsUploading] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [pipelineStatuses, setPipelineStatuses] = useState<Map<string, PipelineStatusItem>>(new Map());
  const [pipelineIds, setPipelineIds] = useState<string[]>([]);
  const [completedAnimations, setCompletedAnimations] = useState<Set<string>>(new Set());
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [totalGenerationDuration, setTotalGenerationDuration] = useState<number | null>(null);
  const pollingIntervalRef = useRef<number | null>(null);
  const pollingTimeoutRef = useRef<number | null>(null);
  const hasTriggeredAutoGenerate = useRef(false);
  const generationStartTime = useRef<number | null>(null);
  const isMountedRef = useRef(true);

  const clearPolling = useCallback(() => {
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
      pollingIntervalRef.current = null;
      console.log("Cleared polling interval");
    }
    if (pollingTimeoutRef.current) {
      clearTimeout(pollingTimeoutRef.current);
      pollingTimeoutRef.current = null;
      console.log("Cleared polling timeout");
    }
  }, []);

  const pollPipelineStatuses = useCallback(async (ids: string[]) => {
    if (!isMountedRef.current) return;
    
    try {
      const response = await pipelinesApi.getStatus(ids);
      
      if (!isMountedRef.current) return;
      
      const statusMap = new Map<string, PipelineStatusItem>();
      
      let allCompleted = true;
      let hasFailures = false;
      let failureMessages: string[] = [];
      
      for (const pipeline of response.pipelines) {
        statusMap.set(pipeline.id, pipeline);
        if (pipeline.status !== "COMPLETED" && pipeline.status !== "FAILED") {
          allCompleted = false;
        }
        if (pipeline.status === "FAILED") {
          hasFailures = true;
          const errorMsg = pipeline.message || "Unknown error";
          console.error(`Pipeline ${pipeline.id} failed:`, errorMsg);
          failureMessages.push(errorMsg);
        }
      }
      
      setPipelineStatuses(statusMap);
      
      if (allCompleted && generationStartTime.current && totalGenerationDuration === null) {
        const duration = (Date.now() - generationStartTime.current) / 1000;
        setTotalGenerationDuration(duration);
        
        response.pipelines.forEach(pipeline => {
          if (pipeline.status === "COMPLETED") {
            track({ 
              name: 'generation_completed', 
              params: { 
                pipeline_id: pipeline.id, 
                duration_seconds: duration 
              } 
            });
          } else if (pipeline.status === "FAILED") {
            track({ 
              name: 'generation_failed', 
              params: { 
                pipeline_id: pipeline.id, 
                error: pipeline.message || "Unknown error" 
              } 
            });
          }
        });
        
        if (hasFailures) {
          toast.error("Some pipelines failed. Check individual results for details.");
        }
      }
      
      if (allCompleted) {
        console.log("All pipelines completed, clearing polling");
        setIsProcessing(false);
        clearPolling();
        return;
      }
    } catch (error) {
      if (!isMountedRef.current) return;
      
      console.error("Failed to poll pipeline statuses:", error);
      toast.error("Failed to poll pipeline statuses: " + error);
      clearPolling();
      setIsProcessing(false);
    }
  }, [totalGenerationDuration, clearPolling]);

  const handleGenerateWithFile = useCallback(async (s3Result: { bucket: string; key: string }) => {
    generationStartTime.current = Date.now();
    
    setIsProcessing(true);
    setPipelineStatuses(new Map());
    setCompletedAnimations(new Set());
    setErrorMessage(null);
    setTotalGenerationDuration(null);

    try {
      const traceId = uuidv4();
      const jobs = selectedTemplates.map((template) => {
        const templateS3 = parseS3Url(template.url);
        
        return {
          pipeline_id: uuidv4(),
          pipeline_name: "recast",
          input: {
            source_image_bucket: s3Result.bucket,
            source_image_key: s3Result.key,
            template_image_bucket: templateS3.bucket,
            template_image_key: templateS3.key,
          },
        };
      });

      const generatedPipelineIds = jobs.map(job => job.pipeline_id);
      setPipelineIds(generatedPipelineIds);

      const response = await pipelinesApi.queuePipelines({
        trace_id: traceId,
        jobs,
      });

      track({ 
        name: 'generation_started', 
        params: { 
          pipeline_count: jobs.length, 
          trace_id: traceId 
        } 
      });

      toast.success(
          `Your generation pipelines are queued.`,
          { duration: 5000 }
        );

      clearPolling();

      await pollPipelineStatuses(generatedPipelineIds);

      pollingIntervalRef.current = window.setInterval(() => {
        if (!isMountedRef.current) {
          clearPolling();
          return;
        }
        pollPipelineStatuses(generatedPipelineIds);
      }, 1000);

      pollingTimeoutRef.current = window.setTimeout(() => {
        clearPolling();
        setIsProcessing(false);
        setErrorMessage("Generation timeout. Sorry, GPUs might be currently offline. Please try again later.");
        toast.error("Generation timeout. GPUs might be offline.");
      }, 90000);
    } catch (error) {
      console.error("Failed to queue pipelines:", error);
      toast.error("Failed to queue pipelines: " + error);

      clearPolling();
      setIsProcessing(false);
      setPipelineIds([]);
    }
  }, [selectedTemplates, pollPipelineStatuses, clearPolling]);

  const handleGenerate = async () => {
    if (!selectedFile || !uploadedImageS3) return;

    setErrorMessage(null);

    if (!user) {
      track({ name: 'auth_required', params: { redirect_from: 'generate_page' } });
      try {
        await saveGenerationState({
          selectedTemplates,
          selectedFile,
          uploadedImageS3,
        });
        
        await new Promise(resolve => setTimeout(resolve, 100));
        
        navigate("/auth", {
          state: {
            returnPath: "/face-fusion/generate",
            autoGenerate: true,
            selectedTemplates,
          },
        });
      } catch (error) {
        console.error("Failed to save state:", error);
        toast.error("Failed to save state: " + error);
      }
      return;
    }

    track({ 
      name: 'generate_initiated', 
      params: { 
        template_count: selectedTemplates.length, 
        has_auth: true 
      } 
    });

    await handleGenerateWithFile(uploadedImageS3);
  };

  useEffect(() => {
    const uploadFileToS3 = async (file: File) => {
      setIsUploading(true);
      setErrorMessage(null);
      try {
        const userImageId = uuidv4();
        const extension = getFileExtension(file.name);
        const userImageKey = `user/${userImageId}.${extension}`;

        const uploadResult = await uploadToS3(file, "media", userImageKey);
        setUploadedImageS3(uploadResult);
        track({ 
          name: 'image_uploaded', 
          params: { 
            file_size_kb: Math.round(file.size / 1024), 
            file_type: file.type 
          } 
        });
      } catch (error) {
        console.error("Failed to upload image:", error);
        toast.error("Failed to upload image: " + error);
        setSelectedFile(null);
      } finally {
        setIsUploading(false);
      }
    };

    if (selectedFile && !uploadedImageS3) {
      uploadFileToS3(selectedFile);
    }
  }, [selectedFile, uploadedImageS3]);

  useEffect(() => {
    const searchParams = new URLSearchParams(location.search);
    const shouldAutoGenerate = searchParams.get('autoGenerate') === 'true';
    
    if (shouldAutoGenerate && !authLoading && user && !hasTriggeredAutoGenerate.current && uploadedImageS3) {
      hasTriggeredAutoGenerate.current = true;
      
      setTimeout(() => {
        handleGenerateWithFile(uploadedImageS3);
      }, 500);
    }
  }, [location.search, authLoading, user, uploadedImageS3, handleGenerateWithFile]);

  useEffect(() => {
    isMountedRef.current = true;
    
    const handleBeforeUnload = () => {
      clearGenerationState();
    };
    
    window.addEventListener('beforeunload', handleBeforeUnload);
    
    return () => {
      isMountedRef.current = false;
      clearPolling();
      window.removeEventListener('beforeunload', handleBeforeUnload);
    };
  }, [clearPolling]);

  if (selectedTemplates.length === 0) {
    return (
      <main className="container mx-auto px-6 py-16 flex items-center justify-center min-h-[calc(100vh-8rem)]">
        <div className="text-center space-y-6">
          <h2 className="text-2xl font-bold">No templates selected</h2>
          <p className="text-muted-foreground">
            Please go back and select up to 3 templates first.
          </p>
          <Button onClick={() => {
            track({ name: 'back_to_templates', params: { source: 'no_templates_page' } });
            clearGenerationState();
            navigate("/face-fusion");
          }} variant="outline">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Templates
          </Button>
        </div>
      </main>
    );
  }

  const handleAnimationComplete = (index: number) => {
    setCompletedAnimations((prev) => new Set([...prev, index.toString()]));
  };

  const countCompletedOrFailed = () => {
    let count = 0;
    pipelineIds.forEach((pipelineId) => {
      const status = pipelineStatuses.get(pipelineId);
      if (status && (status.status === "COMPLETED" || status.status === "FAILED")) {
        count++;
      }
    });
    return count;
  };

  const allAnimationsComplete = pipelineIds.length > 0 && 
    (completedAnimations.size === selectedTemplates.length || 
     countCompletedOrFailed() === selectedTemplates.length);

  return (
    <main className="container mx-auto px-6 py-16 space-y-12 min-h-[calc(100vh-8rem)]">
      <section className="max-w-4xl mx-auto space-y-6 text-center animate-fade-in">
          <Button
            onClick={() => {
              track({ name: 'back_to_templates', params: { source: 'generate_page' } });
              clearGenerationState();
              navigate("/face-fusion");
            }}
            variant="ghost"
            className="mb-4"
          >
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Templates
          </Button>

        <div className="space-y-4">
          <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
            Upload a clear portrait to apply {selectedTemplates.length} selected style
            {selectedTemplates.length !== 1 ? "s" : ""}
          </p>
        </div>

        {!selectedFile ? (
          <UploadDropzone
            onFileSelect={setSelectedFile}
            selectedFile={selectedFile}
          />
        ) : (
          <div className="max-w-md mx-auto">
            <div className="relative group">
              <img
                src={URL.createObjectURL(selectedFile)}
                alt="Your selfie"
                className="w-full rounded-xl shadow-2xl border border-border"
              />
              {isUploading && (
                <div className="absolute inset-0 flex items-center justify-center bg-background/80 rounded-xl">
                  <div className="text-center">
                    <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-primary border-r-transparent mb-2"></div>
                    <p className="text-sm text-muted-foreground">Uploading...</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </section>

      {selectedFile && (
        <>
          <section className="max-w-4xl mx-auto">
            <h2 className="text-2xl font-bold text-center mb-8">
              Selected Templates
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
              {selectedTemplates.map((template, index) => {
                const pipelineId = pipelineIds[index];
                const status = pipelineId ? pipelineStatuses.get(pipelineId) : null;
                const isCardProcessing = pipelineId ? (!status || status.status === "RUNNING" || status.status === "PENDING") : false;
                const generatedImage = status?.status === "COMPLETED" ? status.result_url : null;
                const cardErrorMessage = status?.status === "FAILED" ? status.message : null;

                return (
                  <GenerationCard
                    key={template.id}
                    imageUrl={template.url}
                    isProcessing={isCardProcessing}
                    generatedImage={generatedImage || undefined}
                    errorMessage={cardErrorMessage || undefined}
                    templateName={template.name}
                    pipelineId={pipelineId || null}
                    onAnimationComplete={() => handleAnimationComplete(index)}
                  />
                );
              })}
            </div>
            
            {allAnimationsComplete && totalGenerationDuration !== null && (
              <div className="text-center mt-6 animate-fade-in">
                <p className="text-muted-foreground text-sm">
                  Done in {totalGenerationDuration.toFixed(1)} seconds
                </p>
              </div>
            )}
          </section>

          {errorMessage && (
            <div className="max-w-2xl mx-auto animate-fade-in">
              <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-4 text-center">
                <p className="text-destructive font-medium">{errorMessage}</p>
              </div>
            </div>
          )}

          {!isProcessing && pipelineIds.length === 0 && (
            <div className="flex justify-center animate-fade-in">
              <Button
                onClick={handleGenerate}
                size="lg"
                className="hover-glow text-lg font-semibold px-12 py-6 shadow-elegant"
                disabled={isUploading || !uploadedImageS3}
              >
                <Sparkles className="mr-2 h-5 w-5" />
                {isUploading ? "Uploading..." : "Generate"}
              </Button>
            </div>
          )}

          {allAnimationsComplete && (
            <div className="flex justify-center gap-4 animate-fade-in">
              <Button
                onClick={() => {
                  const hasErrors = Array.from(pipelineStatuses.values()).some(s => s.status === "FAILED");
                  track({ 
                    name: 'try_other_templates_clicked', 
                    params: { from_status: hasErrors ? 'error' : 'success' } 
                  });
                  clearGenerationState();
                  navigate("/face-fusion");
                }}
                size="lg"
              >
                Try Different Templates
              </Button>
            </div>
          )}
        </>
      )}
    </main>
  );
};

export default FaceFusionGenerate;
