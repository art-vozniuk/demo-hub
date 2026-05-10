import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Github } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ExpandableDescription } from "@/components/ExpandableDescription";
import PresetCard from "@/components/PresetCard";
import { generativeApi, type GenerativePresetRead } from "@/api";
import { useAnalytics } from "@/hooks/useAnalytics";

const GenerativeEditing = () => {
  const navigate = useNavigate();
  const { track } = useAnalytics();
  const [presets, setPresets] = useState<GenerativePresetRead[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    generativeApi
      .getPresets()
      .then((list) => {
        if (!alive) return;
        setPresets(list);
        setLoading(false);
      })
      .catch((err) => {
        if (!alive) return;
        setError(err?.message ?? "Failed to load presets");
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const handleSelect = (preset: GenerativePresetRead) => {
    track({
      name: "generative_preset_opened",
      params: { preset_slug: preset.slug },
    });
    navigate(`/generative-editing/generate?preset=${preset.slug}`);
  };

  return (
    <main className="container mx-auto px-6 py-16 space-y-12 min-h-[calc(100vh-8rem)]">
      <section className="max-w-4xl mx-auto space-y-6 text-center animate-fade-in">
        <div className="space-y-4">
          <h1 className="text-5xl font-bold tracking-tight sm:text-6xl">
            <span className="text-gradient">Generative Editing</span>
          </h1>

          <ExpandableDescription>
            Image-conditioned generative editing on FLUX.2 klein. Pick a
            cinematic preset and the platform routes your photo through a
            serverless A10G on Modal — async dispatch worker, RabbitMQ
            orchestration.
          </ExpandableDescription>

          <div className="flex items-center justify-center gap-3">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="outline"
                  size="icon"
                  className="rounded-full animate-pulse-glow"
                  asChild
                >
                  <a
                    href="https://github.com/art-vozniuk/demo-hub"
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label="GitHub Repository"
                    onClick={() =>
                      track({
                        name: "generative_github_repo_clicked",
                        params: {},
                      })
                    }
                  >
                    <Github className="h-5 w-5" />
                  </a>
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                <p>Visit the repository</p>
              </TooltipContent>
            </Tooltip>
          </div>

          <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
            Pick a cinematic preset
          </p>
        </div>
      </section>

      <section className="max-w-6xl mx-auto">
        {error && (
          <div className="text-sm text-destructive text-center">{error}</div>
        )}
        {loading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div
                key={i}
                className="aspect-square rounded-lg bg-muted/40 animate-pulse"
              />
            ))}
          </div>
        ) : presets.length === 0 && !error ? (
          <p className="text-center text-muted-foreground">
            No presets available
          </p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {presets.map((preset) => (
              <PresetCard
                key={preset.id}
                preset={preset}
                onSelect={handleSelect}
              />
            ))}
          </div>
        )}
      </section>
    </main>
  );
};

export default GenerativeEditing;
