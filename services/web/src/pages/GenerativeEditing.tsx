import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { DemoHeader } from "@/components/DemoHeader";
import PresetCard from "@/components/PresetCard";
import { useWallet } from "@/contexts/WalletContext";
import { generativeApi, type GenerativePresetRead } from "@/api";
import { useAnalytics } from "@/hooks/useAnalytics";

const GenerativeEditing = () => {
  const navigate = useNavigate();
  const { track } = useAnalytics();
  const { getCost } = useWallet();
  const fluxCost = getCost("generative_editing");
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
      <DemoHeader
        title="Generative Editing"
        cost={fluxCost}
        description="Image-conditioned generative editing on FLUX.2 klein. Pick a cinematic preset and the platform routes your photo through a serverless A10G on Modal — async dispatch worker, RabbitMQ orchestration."
        githubUrl="https://github.com/art-vozniuk/demo-hub"
        onGithubClick={() =>
          track({ name: "generative_github_repo_clicked", params: {} })
        }
        tagline="Pick a cinematic preset"
      />

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
