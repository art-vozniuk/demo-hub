import { useState, useEffect, useRef, useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Sparkles, ArrowLeft } from "lucide-react";
import type { RecastTemplateRead } from "@/api";
import { pipelinesApi, ApiError, type PipelineStatusItem } from "@/api";
import { uploadToS3, parseS3Url, getFileExtension } from "@/lib/s3";
import UploadDropzone from "@/components/UploadDropzone";
import GenerationCard from "@/components/GenerationCard";
import FaceSelectionOverlay from "@/components/FaceSelectionOverlay";
import CostBadge from "@/components/CostBadge";
import InsufficientTokensDialog from "@/components/InsufficientTokensDialog";
import OutOfTokensDialog from "@/components/OutOfTokensDialog";
import { useFaceRecognition } from "@/hooks/useFaceRecognition";
import { useTurnstile } from "@/hooks/useTurnstile";
import { useWallet } from "@/contexts/WalletContext";
import { toast } from "sonner";
import { v4 as uuidv4 } from "uuid";
import { useAnalytics } from "@/hooks/useAnalytics";

interface S3Ref {
  bucket: string;
  key: string;
}

interface SerializedFile {
  fileDataUrl: string;
  fileName: string;
  fileType: string;
}

interface PersistedState {
  isCustom: boolean;
  selectedTemplates: RecastTemplateRead[];
  selfie?: SerializedFile;
  selfieS3?: S3Ref;
  template?: SerializedFile;
  templateS3?: S3Ref;
}

const STORAGE_KEY = "generation-state";

const fileToDataUrl = (file: File): Promise<SerializedFile> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () =>
      resolve({
        fileDataUrl: reader.result as string,
        fileName: file.name,
        fileType: file.type,
      });
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });

const dataUrlToFile = (s: SerializedFile): File => {
  const byteString = atob(s.fileDataUrl.split(",")[1]);
  const mimeString = s.fileDataUrl.split(",")[0].split(":")[1].split(";")[0];
  const ab = new ArrayBuffer(byteString.length);
  const ia = new Uint8Array(ab);
  for (let i = 0; i < byteString.length; i++) ia[i] = byteString.charCodeAt(i);
  const blob = new Blob([ab], { type: mimeString });
  return new File([blob], s.fileName, { type: s.fileType });
};

const loadPersisted = (): {
  isCustom: boolean;
  selectedTemplates: RecastTemplateRead[];
  selfieFile: File | null;
  selfieS3: S3Ref | null;
  templateFile: File | null;
  templateS3: S3Ref | null;
} | null => {
  const saved = sessionStorage.getItem(STORAGE_KEY);
  if (!saved) return null;
  try {
    const data = JSON.parse(saved) as PersistedState;
    return {
      isCustom: data.isCustom,
      selectedTemplates: data.selectedTemplates ?? [],
      selfieFile: data.selfie ? dataUrlToFile(data.selfie) : null,
      selfieS3: data.selfieS3 ?? null,
      templateFile: data.template ? dataUrlToFile(data.template) : null,
      templateS3: data.templateS3 ?? null,
    };
  } catch (error) {
    console.error("Failed to restore generation state:", error);
    toast.error("Failed to restore generation state: " + error);
    return null;
  }
};

const persist = async (
  state: PersistedState & {
    selfieFile?: File | null;
    templateFile?: File | null;
  }
) => {
  const payload: PersistedState = {
    isCustom: state.isCustom,
    selectedTemplates: state.selectedTemplates,
    selfieS3: state.selfieS3,
    templateS3: state.templateS3,
  };
  if (state.selfieFile) payload.selfie = await fileToDataUrl(state.selfieFile);
  if (state.templateFile)
    payload.template = await fileToDataUrl(state.templateFile);
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
};

const clearPersisted = () => sessionStorage.removeItem(STORAGE_KEY);

const FaceFusionGenerate = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { track } = useAnalytics();
  const {
    balance,
    isAnonymous,
    getCost,
    turnstileRequired,
    refresh: refreshBalance,
  } = useWallet();
  const faceSwapCost = getCost("face_swap");
  const turnstile = useTurnstile(isAnonymous === true && turnstileRequired);
  const [insufficientDialogOpen, setInsufficientDialogOpen] = useState(false);
  const [insufficientDialogCost, setInsufficientDialogCost] = useState(0);
  const [outOfTokensDialogOpen, setOutOfTokensDialogOpen] = useState(false);

  const [initialState] = useState(() => {
    const persisted = loadPersisted();
    const fromState = location.state as
      | {
          selectedTemplates?: RecastTemplateRead[];
          customTemplate?: boolean;
        }
      | null;

    return {
      isCustom: Boolean(fromState?.customTemplate || persisted?.isCustom),
      templates:
        fromState?.selectedTemplates || persisted?.selectedTemplates || [],
      selfieFile: persisted?.selfieFile || null,
      selfieS3: persisted?.selfieS3 || null,
      templateFile: persisted?.templateFile || null,
      templateS3: persisted?.templateS3 || null,
    };
  });

  const isCustom = initialState.isCustom;
  const [selectedTemplates] = useState<RecastTemplateRead[]>(
    initialState.templates
  );

  const [selfieFile, setSelfieFile] = useState<File | null>(
    initialState.selfieFile
  );
  const [selfieS3, setSelfieS3] = useState<S3Ref | null>(initialState.selfieS3);
  const [isUploadingSelfie, setIsUploadingSelfie] = useState(false);

  const [templateFile, setTemplateFile] = useState<File | null>(
    initialState.templateFile
  );
  const [templateS3, setTemplateS3] = useState<S3Ref | null>(
    initialState.templateS3
  );
  const [isUploadingTemplate, setIsUploadingTemplate] = useState(false);

  const selfieRecognition = useFaceRecognition();
  const templateRecognition = useFaceRecognition();

  const [isProcessing, setIsProcessing] = useState(false);
  const [pipelineStatuses, setPipelineStatuses] = useState<
    Map<string, PipelineStatusItem>
  >(new Map());
  const [pipelineIds, setPipelineIds] = useState<string[]>([]);
  const [estimatedFinishAt, setEstimatedFinishAt] = useState<
    Map<string, string>
  >(new Map());
  const [workersMissing, setWorkersMissing] = useState<Map<string, boolean>>(
    new Map()
  );
  const [completedAnimations, setCompletedAnimations] = useState<Set<string>>(
    new Set()
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [totalGenerationDuration, setTotalGenerationDuration] = useState<
    number | null
  >(null);

  const pollingIntervalRef = useRef<number | null>(null);
  const pollingTimeoutRef = useRef<number | null>(null);
  const generationStartTime = useRef<number | null>(null);
  const isMountedRef = useRef(true);

  const objectUrlsRef = useRef<Map<File, string>>(new Map());
  const previewUrl = useCallback((file: File) => {
    const cache = objectUrlsRef.current;
    const cached = cache.get(file);
    if (cached) return cached;
    const url = URL.createObjectURL(file);
    cache.set(file, url);
    return url;
  }, []);

  useEffect(() => {
    const cache = objectUrlsRef.current;
    return () => {
      cache.forEach((url) => URL.revokeObjectURL(url));
      cache.clear();
    };
  }, []);

  const clearPolling = useCallback(() => {
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
      pollingIntervalRef.current = null;
    }
    if (pollingTimeoutRef.current) {
      clearTimeout(pollingTimeoutRef.current);
      pollingTimeoutRef.current = null;
    }
  }, []);

  // Selfie upload → S3 → kick face_recognition.
  useEffect(() => {
    const upload = async (file: File) => {
      setIsUploadingSelfie(true);
      setErrorMessage(null);
      try {
        const id = uuidv4();
        const ext = getFileExtension(file.name);
        const result = await uploadToS3(file, "media", `user/${id}.${ext}`);
        setSelfieS3(result);
        track({
          name: "image_uploaded",
          params: {
            file_size_kb: Math.round(file.size / 1024),
            file_type: file.type,
          },
        });
      } catch (error) {
        console.error("Failed to upload selfie:", error);
        toast.error("Failed to upload selfie: " + error);
        setSelfieFile(null);
      } finally {
        setIsUploadingSelfie(false);
      }
    };

    if (selfieFile && !selfieS3) {
      upload(selfieFile);
    }
  }, [selfieFile, selfieS3, track]);

  useEffect(() => {
    if (selfieS3 && selfieRecognition.status === "idle") {
      selfieRecognition.run({
        bucket: selfieS3.bucket,
        key: selfieS3.key,
        getTurnstileToken: isAnonymous ? turnstile.getToken : undefined,
      });
    }
  }, [selfieS3, selfieRecognition, isAnonymous, turnstile]);

  // Template upload → S3 → kick face_recognition (custom mode only).
  useEffect(() => {
    const upload = async (file: File) => {
      setIsUploadingTemplate(true);
      setErrorMessage(null);
      try {
        const id = uuidv4();
        const ext = getFileExtension(file.name);
        const result = await uploadToS3(file, "media", `templates/${id}.${ext}`);
        setTemplateS3(result);
      } catch (error) {
        console.error("Failed to upload template:", error);
        toast.error("Failed to upload template: " + error);
        setTemplateFile(null);
      } finally {
        setIsUploadingTemplate(false);
      }
    };

    if (isCustom && templateFile && !templateS3) {
      upload(templateFile);
    }
  }, [isCustom, templateFile, templateS3]);

  useEffect(() => {
    if (
      isCustom &&
      templateS3 &&
      templateRecognition.status === "idle"
    ) {
      templateRecognition.run({
        bucket: templateS3.bucket,
        key: templateS3.key,
        getTurnstileToken: isAnonymous ? turnstile.getToken : undefined,
      });
    }
  }, [isCustom, templateS3, templateRecognition, isAnonymous, turnstile]);

  const pollPipelineStatuses = useCallback(
    async (ids: string[]) => {
      if (!isMountedRef.current) return;

      try {
        const response = await pipelinesApi.getStatus(ids);
        if (!isMountedRef.current) return;

        const statusMap = new Map<string, PipelineStatusItem>();
        let allCompleted = true;
        let hasFailures = false;

        for (const pipeline of response.pipelines) {
          statusMap.set(pipeline.id, pipeline);
          if (pipeline.status !== "COMPLETED" && pipeline.status !== "FAILED") {
            allCompleted = false;
          }
          if (pipeline.status === "FAILED") hasFailures = true;
        }

        setPipelineStatuses(statusMap);

        if (
          allCompleted &&
          generationStartTime.current &&
          totalGenerationDuration === null
        ) {
          const duration = (Date.now() - generationStartTime.current) / 1000;
          setTotalGenerationDuration(duration);

          response.pipelines.forEach((pipeline) => {
            if (pipeline.status === "COMPLETED") {
              track({
                name: "generation_completed",
                params: {
                  pipeline_id: pipeline.id,
                  duration_seconds: duration,
                },
              });
            } else if (pipeline.status === "FAILED") {
              track({
                name: "generation_failed",
                params: {
                  pipeline_id: pipeline.id,
                  error: pipeline.message || "Unknown error",
                },
              });
            }
          });

          if (hasFailures) {
            toast.error(
              "Some pipelines failed. Check individual results for details."
            );
          }

          // Pull post-refund balance so users see returned tokens.
          if (hasFailures) refreshBalance();
        }

        if (allCompleted) {
          setIsProcessing(false);
          clearPolling();
        }
      } catch (error) {
        if (!isMountedRef.current) return;
        console.error("Failed to poll pipeline statuses:", error);
        toast.error("Failed to poll pipeline statuses: " + error);
        clearPolling();
        setIsProcessing(false);
      }
    },
    [totalGenerationDuration, clearPolling, track, refreshBalance]
  );

  const startGeneration = useCallback(async () => {
    if (!selfieS3) return;
    if (faceSwapCost === undefined) return;
    const sourceBbox = selfieRecognition.selectedBbox;
    if (!sourceBbox) return;

    if (isCustom) {
      if (!templateS3) return;
      if (!templateRecognition.selectedBbox) return;
    }

    const jobCount = isCustom ? 1 : selectedTemplates.length;
    const totalCost = jobCount * faceSwapCost;
    if (balance !== null && balance < totalCost) {
      if (isAnonymous) {
        setInsufficientDialogCost(totalCost);
        setInsufficientDialogOpen(true);
      } else {
        setOutOfTokensDialogOpen(true);
      }
      return;
    }

    generationStartTime.current = Date.now();
    setIsProcessing(true);
    setPipelineStatuses(new Map());
    setEstimatedFinishAt(new Map());
    setWorkersMissing(new Map());
    setCompletedAnimations(new Set());
    setErrorMessage(null);
    setTotalGenerationDuration(null);

    try {
      const traceId = uuidv4();

      const jobs = isCustom
        ? [
            {
              pipeline_id: uuidv4(),
              pipeline_name: "face_swap",
              input: {
                source_image_bucket: selfieS3.bucket,
                source_image_key: selfieS3.key,
                template_image_bucket: templateS3!.bucket,
                template_image_key: templateS3!.key,
                source_face_bbox: sourceBbox,
                target_face_bbox: templateRecognition.selectedBbox,
              },
            },
          ]
        : selectedTemplates.map((template) => {
            const tplS3 = parseS3Url(template.url);
            return {
              pipeline_id: uuidv4(),
              pipeline_name: "face_swap",
              input: {
                source_image_bucket: selfieS3.bucket,
                source_image_key: selfieS3.key,
                template_image_bucket: tplS3.bucket,
                template_image_key: tplS3.key,
                source_face_bbox: sourceBbox,
              },
            };
          });

      const ids = jobs.map((j) => j.pipeline_id);
      setPipelineIds(ids);

      const turnstileToken = isAnonymous
        ? (await turnstile.getToken().catch(() => null)) ?? undefined
        : undefined;

      try {
        await pipelinesApi.queuePipelines(
          { trace_id: traceId, jobs },
          turnstileToken,
        );
      } catch (err) {
        if (err instanceof ApiError && err.status === 402) {
          await refreshBalance();
          if (isAnonymous) {
            setInsufficientDialogCost(jobs.length * faceSwapCost);
            setInsufficientDialogOpen(true);
          } else {
            setOutOfTokensDialogOpen(true);
          }
          setIsProcessing(false);
          setPipelineIds([]);
          return;
        }
        throw err;
      }

      refreshBalance();

      track({
        name: "generation_started",
        params: { pipeline_count: jobs.length, trace_id: traceId },
      });

      toast.success("Your generation pipelines are queued.", { duration: 5000 });

      // Fetch ETA per pipeline; failures shouldn't block the generation flow.
      Promise.all(
        ids.map((id) =>
          pipelinesApi
            .getEstimate(id)
            .then((res) => {
              if (!isMountedRef.current) return;
              const target = new Date(
                Date.now() + res.estimated_seconds * 1000
              ).toISOString();
              setEstimatedFinishAt((prev) => {
                const next = new Map(prev);
                next.set(id, target);
                return next;
              });
              setWorkersMissing((prev) => {
                const next = new Map(prev);
                next.set(id, res.workers_missing);
                return next;
              });
            })
            .catch((e) => console.warn(`Failed to fetch estimate for ${id}:`, e))
        )
      );

      clearPolling();
      await pollPipelineStatuses(ids);

      pollingIntervalRef.current = window.setInterval(() => {
        if (!isMountedRef.current) {
          clearPolling();
          return;
        }
        pollPipelineStatuses(ids);
      }, 1000);

      pollingTimeoutRef.current = window.setTimeout(() => {
        clearPolling();
        setIsProcessing(false);
        setErrorMessage(
          "Generation timeout. Sorry, GPUs might be currently offline. Please try again later."
        );
        toast.error("Generation timeout. GPUs might be offline.");
      }, 90000);
    } catch (error) {
      console.error("Failed to queue pipelines:", error);
      toast.error("Failed to queue pipelines: " + error);
      clearPolling();
      setIsProcessing(false);
      setPipelineIds([]);
    }
  }, [
    isCustom,
    selectedTemplates,
    selfieS3,
    selfieRecognition.selectedBbox,
    templateS3,
    templateRecognition.selectedBbox,
    pollPipelineStatuses,
    clearPolling,
    track,
    balance,
    isAnonymous,
    faceSwapCost,
    turnstile,
    refreshBalance,
  ]);

  const handleGenerate = useCallback(async () => {
    setErrorMessage(null);

    track({
      name: "generate_initiated",
      params: {
        template_count: isCustom ? 1 : selectedTemplates.length,
        has_auth: true,
      },
    });

    await startGeneration();
  }, [isCustom, selectedTemplates, track, startGeneration]);

  useEffect(() => {
    isMountedRef.current = true;
    const handleBeforeUnload = () => clearPersisted();
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      isMountedRef.current = false;
      clearPolling();
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, [clearPolling]);

  // Empty-state guard: someone landed on /generate without picking
  // anything (and not via custom flow). Send them back.
  if (!isCustom && selectedTemplates.length === 0) {
    return (
      <main className="container mx-auto px-6 py-16 flex items-center justify-center min-h-[calc(100vh-8rem)]">
        <div className="text-center space-y-6">
          <h2 className="text-2xl font-bold">No templates selected</h2>
          <p className="text-muted-foreground">
            Please go back and select up to 3 templates first.
          </p>
          <Button
            onClick={() => {
              track({ name: "back_to_templates", params: { source: "no_templates_page" } });
              clearPersisted();
              navigate("/face-fusion");
            }}
            variant="outline"
          >
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

  const generationCount = isCustom ? 1 : selectedTemplates.length;
  const allAnimationsComplete =
    pipelineIds.length > 0 &&
    (completedAnimations.size === generationCount ||
      countCompletedOrFailed() === generationCount);

  // Generate button is enabled only when every prerequisite is satisfied
  // for the current mode.
  const selfieReady =
    selfieRecognition.status === "complete" &&
    selfieRecognition.selectedBbox !== null;
  const templateReady =
    !isCustom ||
    (templateRecognition.status === "complete" &&
      templateRecognition.selectedBbox !== null);
  const canGenerate =
    !isProcessing &&
    pipelineIds.length === 0 &&
    !!selfieS3 &&
    !isUploadingSelfie &&
    (!isCustom || (!!templateS3 && !isUploadingTemplate)) &&
    selfieReady &&
    templateReady;

  const handleResetSelfie = () => {
    setSelfieFile(null);
    setSelfieS3(null);
    selfieRecognition.reset();
  };

  const handleResetTemplate = () => {
    setTemplateFile(null);
    setTemplateS3(null);
    templateRecognition.reset();
  };

  return (
    <main className="container mx-auto px-6 py-16 space-y-12 min-h-[calc(100vh-8rem)]">
      <section className="max-w-4xl mx-auto space-y-6 text-center animate-fade-in">
        <Button
          onClick={() => {
            track({ name: "back_to_templates", params: { source: "generate_page" } });
            clearPersisted();
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
            {isCustom
              ? "Upload a template and a portrait, choose which face to swap."
              : `Upload a clear portrait to apply ${selectedTemplates.length} selected style${selectedTemplates.length !== 1 ? "s" : ""}`}
          </p>
          {faceSwapCost !== undefined && (
            <div className="flex justify-center">
              <CostBadge
                cost={(isCustom ? 1 : selectedTemplates.length) * faceSwapCost}
              />
            </div>
          )}
        </div>

        {/* Custom flow: dual upload — template first, then selfie. */}
        {isCustom && (
          <div className="grid gap-8 md:grid-cols-2 max-w-3xl mx-auto">
            <div className="space-y-3">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                1. Template
              </h3>
              {!templateFile ? (
                <UploadDropzone
                  onFileSelect={setTemplateFile}
                  selectedFile={templateFile}
                />
              ) : !templateS3 || isUploadingTemplate ? (
                <div className="max-w-md mx-auto">
                  <div className="relative">
                    <img
                      src={previewUrl(templateFile)}
                      alt="Template"
                      className="w-full rounded-xl shadow-2xl border border-border"
                    />
                    <div className="absolute inset-0 flex items-center justify-center bg-background/80 rounded-xl">
                      <div className="text-center">
                        <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-primary border-r-transparent mb-2" />
                        <p className="text-sm text-muted-foreground">Uploading…</p>
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <FaceSelectionOverlay
                  imageUrl={previewUrl(templateFile)}
                  faces={templateRecognition.payload?.faces ?? []}
                  imageWidth={templateRecognition.payload?.image_width ?? 1}
                  imageHeight={templateRecognition.payload?.image_height ?? 1}
                  selectedFaceId={templateRecognition.selectedFaceId}
                  onFaceSelect={templateRecognition.selectFace}
                  isAnalyzing={templateRecognition.status === "running"}
                  errorMessage={templateRecognition.errorMessage}
                />
              )}
              {templateFile && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleResetTemplate}
                  className="text-xs"
                >
                  Replace template
                </Button>
              )}
            </div>

            <div className="space-y-3">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                2. Your photo
              </h3>
              {!selfieFile ? (
                <UploadDropzone
                  onFileSelect={setSelfieFile}
                  selectedFile={selfieFile}
                />
              ) : !selfieS3 || isUploadingSelfie ? (
                <div className="max-w-md mx-auto">
                  <div className="relative">
                    <img
                      src={previewUrl(selfieFile)}
                      alt="Your selfie"
                      className="w-full rounded-xl shadow-2xl border border-border"
                    />
                    <div className="absolute inset-0 flex items-center justify-center bg-background/80 rounded-xl">
                      <div className="text-center">
                        <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-primary border-r-transparent mb-2" />
                        <p className="text-sm text-muted-foreground">Uploading…</p>
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <FaceSelectionOverlay
                  imageUrl={previewUrl(selfieFile)}
                  faces={selfieRecognition.payload?.faces ?? []}
                  imageWidth={selfieRecognition.payload?.image_width ?? 1}
                  imageHeight={selfieRecognition.payload?.image_height ?? 1}
                  selectedFaceId={selfieRecognition.selectedFaceId}
                  onFaceSelect={selfieRecognition.selectFace}
                  isAnalyzing={selfieRecognition.status === "running"}
                  errorMessage={selfieRecognition.errorMessage}
                />
              )}
              {selfieFile && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleResetSelfie}
                  className="text-xs"
                >
                  Replace photo
                </Button>
              )}
            </div>
          </div>
        )}

        {/* Standard flow: only selfie upload. Templates are already chosen. */}
        {!isCustom && (
          <>
            {!selfieFile ? (
              <UploadDropzone
                onFileSelect={setSelfieFile}
                selectedFile={selfieFile}
              />
            ) : !selfieS3 || isUploadingSelfie ? (
              <div className="max-w-md mx-auto">
                <div className="relative group">
                  <img
                    src={previewUrl(selfieFile)}
                    alt="Your selfie"
                    className="w-full rounded-xl shadow-2xl border border-border"
                  />
                  <div className="absolute inset-0 flex items-center justify-center bg-background/80 rounded-xl">
                    <div className="text-center">
                      <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-primary border-r-transparent mb-2" />
                      <p className="text-sm text-muted-foreground">Uploading…</p>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <FaceSelectionOverlay
                imageUrl={previewUrl(selfieFile)}
                faces={selfieRecognition.payload?.faces ?? []}
                imageWidth={selfieRecognition.payload?.image_width ?? 1}
                imageHeight={selfieRecognition.payload?.image_height ?? 1}
                selectedFaceId={selfieRecognition.selectedFaceId}
                onFaceSelect={selfieRecognition.selectFace}
                isAnalyzing={selfieRecognition.status === "running"}
                errorMessage={selfieRecognition.errorMessage}
              />
            )}
            {selfieFile && !isProcessing && pipelineIds.length === 0 && (
              <Button
                variant="ghost"
                size="sm"
                onClick={handleResetSelfie}
                className="text-xs"
              >
                Replace photo
              </Button>
            )}
          </>
        )}
      </section>

      {((isCustom && templateFile && selfieFile) ||
        (!isCustom && selfieFile)) && (
        <>
          {!isCustom && (
            <section className="max-w-4xl mx-auto">
              <h2 className="text-2xl font-bold text-center mb-8">
                Selected Templates
              </h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
                {selectedTemplates.map((template, index) => {
                  const pipelineId = pipelineIds[index];
                  const status = pipelineId
                    ? pipelineStatuses.get(pipelineId)
                    : null;
                  const isCardProcessing = pipelineId
                    ? !status ||
                      status.status === "RUNNING" ||
                      status.status === "PENDING"
                    : false;
                  const generatedImage =
                    status?.status === "COMPLETED"
                      ? ((status.result as { result_url?: string } | null)?.result_url ?? null)
                      : null;
                  const cardErrorMessage =
                    status?.status === "FAILED" ? status.message : null;

                  return (
                    <GenerationCard
                      key={template.id}
                      imageUrl={template.url}
                      isProcessing={isCardProcessing}
                      generatedImage={generatedImage || undefined}
                      errorMessage={cardErrorMessage || undefined}
                      templateName={template.name}
                      pipelineId={pipelineId || null}
                      estimatedFinishAt={
                        pipelineId ? estimatedFinishAt.get(pipelineId) ?? null : null
                      }
                      workersMissing={
                        pipelineId ? workersMissing.get(pipelineId) ?? false : false
                      }
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
          )}

          {isCustom && pipelineIds.length > 0 && (
            <section className="max-w-md mx-auto">
              <div className="grid grid-cols-1 gap-6">
                {pipelineIds.map((pipelineId, index) => {
                  const status = pipelineStatuses.get(pipelineId);
                  const isCardProcessing =
                    !status ||
                    status.status === "RUNNING" ||
                    status.status === "PENDING";
                  const generatedImage =
                    status?.status === "COMPLETED"
                      ? ((status.result as { result_url?: string } | null)?.result_url ?? null)
                      : null;
                  const cardErrorMessage =
                    status?.status === "FAILED" ? status.message : null;
                  const previewSource = templateFile
                    ? previewUrl(templateFile)
                    : "";

                  return (
                    <GenerationCard
                      key={pipelineId}
                      imageUrl={previewSource}
                      isProcessing={isCardProcessing}
                      generatedImage={generatedImage || undefined}
                      errorMessage={cardErrorMessage || undefined}
                      templateName="Custom"
                      pipelineId={pipelineId}
                      estimatedFinishAt={
                        pipelineId ? estimatedFinishAt.get(pipelineId) ?? null : null
                      }
                      workersMissing={
                        pipelineId ? workersMissing.get(pipelineId) ?? false : false
                      }
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
          )}

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
                disabled={!canGenerate}
              >
                <Sparkles className="mr-2 h-5 w-5" />
                {isUploadingSelfie || isUploadingTemplate
                  ? "Uploading…"
                  : selfieRecognition.status === "running" ||
                      templateRecognition.status === "running"
                    ? "Detecting faces…"
                    : "Generate"}
              </Button>
            </div>
          )}

          {allAnimationsComplete && (
            <div className="flex justify-center gap-4 animate-fade-in">
              <Button
                onClick={() => {
                  const hasErrors = Array.from(pipelineStatuses.values()).some(
                    (s) => s.status === "FAILED"
                  );
                  track({
                    name: "try_other_templates_clicked",
                    params: { from_status: hasErrors ? "error" : "success" },
                  });
                  clearPersisted();
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

      <InsufficientTokensDialog
        open={insufficientDialogOpen}
        onOpenChange={setInsufficientDialogOpen}
        cost={insufficientDialogCost}
        balance={balance ?? 0}
      />
      <OutOfTokensDialog
        open={outOfTokensDialogOpen}
        onOpenChange={setOutOfTokensDialogOpen}
      />
    </main>
  );
};

export default FaceFusionGenerate;
