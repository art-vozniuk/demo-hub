import { useCallback, useEffect, useRef, useState } from "react";
import { v4 as uuidv4 } from "uuid";

import { pipelinesApi } from "@/api";
import type { FaceRecognitionResult } from "@/api";

type Status = "idle" | "running" | "complete" | "failed";

interface State {
  status: Status;
  payload: FaceRecognitionResult | null;
  errorMessage: string | null;
  selectedFaceId: string | null;
}

const initialState: State = {
  status: "idle",
  payload: null,
  errorMessage: null,
  selectedFaceId: null,
};

interface RunArgs {
  bucket: string;
  key: string;
}

// Submits a face_recognition job for an S3 image, polls until terminal,
// and exposes the detected faces with a selectedFaceId that defaults to
// the largest face.
export function useFaceRecognition() {
  const [state, setState] = useState<State>(initialState);
  const intervalRef = useRef<number | null>(null);
  const timeoutRef = useRef<number | null>(null);
  const isMountedRef = useRef(true);

  const clearTimers = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      clearTimers();
    };
  }, [clearTimers]);

  const reset = useCallback(() => {
    clearTimers();
    setState(initialState);
  }, [clearTimers]);

  const selectFace = useCallback((faceId: string) => {
    setState((prev) =>
      prev.payload && prev.payload.faces.some((f) => f.id === faceId)
        ? { ...prev, selectedFaceId: faceId }
        : prev
    );
  }, []);

  const run = useCallback(
    async ({ bucket, key }: RunArgs) => {
      clearTimers();
      setState({ ...initialState, status: "running" });

      const pipelineId = uuidv4();
      const traceId = uuidv4();

      try {
        await pipelinesApi.queuePipelines({
          trace_id: traceId,
          jobs: [
            {
              pipeline_id: pipelineId,
              pipeline_name: "face_recognition",
              input: { image_bucket: bucket, image_key: key },
            },
          ],
        });
      } catch (error) {
        if (!isMountedRef.current) return;
        const message =
          error instanceof Error ? error.message : "Failed to start face recognition";
        setState({
          status: "failed",
          payload: null,
          errorMessage: message,
          selectedFaceId: null,
        });
        return;
      }

      const poll = async () => {
        try {
          const response = await pipelinesApi.getStatus([pipelineId]);
          if (!isMountedRef.current) return;

          const item = response.pipelines.find((p) => p.id === pipelineId);
          if (!item) return;

          if (item.status === "COMPLETED") {
            clearTimers();
            const payload = (item.result as FaceRecognitionResult | null) ?? null;
            const firstFaceId = payload?.faces?.[0]?.id ?? null;
            if (!payload || payload.faces.length === 0) {
              setState({
                status: "failed",
                payload,
                errorMessage: "No face detected. Try another photo.",
                selectedFaceId: null,
              });
            } else {
              setState({
                status: "complete",
                payload,
                errorMessage: null,
                selectedFaceId: firstFaceId,
              });
            }
            return;
          }

          if (item.status === "FAILED") {
            clearTimers();
            setState({
              status: "failed",
              payload: null,
              errorMessage: item.message || "Face recognition failed",
              selectedFaceId: null,
            });
          }
        } catch (error) {
          if (!isMountedRef.current) return;
          clearTimers();
          const message =
            error instanceof Error ? error.message : "Polling failed";
          setState({
            status: "failed",
            payload: null,
            errorMessage: message,
            selectedFaceId: null,
          });
        }
      };

      // Poll immediately in addition to the interval — detection often
      // finishes inside the first second.
      void poll();
      intervalRef.current = window.setInterval(poll, 1000);
      timeoutRef.current = window.setTimeout(() => {
        if (!isMountedRef.current) return;
        clearTimers();
        setState({
          status: "failed",
          payload: null,
          errorMessage:
            "Face recognition timed out. GPUs may be offline. Please try again.",
          selectedFaceId: null,
        });
      }, 90000);
    },
    [clearTimers]
  );

  const selectedBbox =
    state.payload?.faces.find((f) => f.id === state.selectedFaceId)?.bbox ?? null;

  return {
    status: state.status,
    payload: state.payload,
    errorMessage: state.errorMessage,
    selectedFaceId: state.selectedFaceId,
    selectedBbox,
    run,
    reset,
    selectFace,
  };
}
