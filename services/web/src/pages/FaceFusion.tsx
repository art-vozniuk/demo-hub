import { useState, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import Masonry from "react-masonry-css";
import { Button } from "@/components/ui/button";
import {Sparkles, Loader2, Github} from "lucide-react";
import { recastApi, type RecastTemplateRead } from "@/api";
import TemplateCard from "@/components/TemplateCard";
import "./masonry.css";

const MAX_SELECTION = 6;

const FaceFusion = () => {
  const navigate = useNavigate();
  const [selectedTemplates, setSelectedTemplates] = useState<RecastTemplateRead[]>([]);
  const [isSticky, setIsSticky] = useState(false);
  const counterRef = useRef<HTMLDivElement>(null);

  const { data: templates, isLoading, error } = useQuery({
    queryKey: ["recast-templates"],
    queryFn: recastApi.getTemplates,
  });

  const breakpointColumns = {
    default: 4,
    1280: 3,
    1024: 3,
    768: 2,
    640: 2,
  };

  const handleToggleTemplate = (template: RecastTemplateRead) => {
    setSelectedTemplates((prev) => {
      const isSelected = prev.some((t) => t.id === template.id);
      if (isSelected) {
        return prev.filter((t) => t.id !== template.id);
      } else if (prev.length < MAX_SELECTION) {
        return [...prev, template];
      }
      return prev;
    });
  };

  const handleGenerate = () => {
    navigate("/face-fusion/generate", { state: { selectedTemplates } });
  };

  useEffect(() => {
    const handleScroll = () => {
      if (counterRef.current) {
        const rect = counterRef.current.getBoundingClientRect();
        setIsSticky(rect.top <= 80);
      }
    };

    window.addEventListener("scroll", handleScroll);
    handleScroll();

    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  if (isLoading) {
    return (
      <main className="container mx-auto px-6 py-16 flex items-center justify-center min-h-[calc(100vh-8rem)]">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-12 w-12 animate-spin text-primary" />
          <p className="text-lg text-muted-foreground">Loading templates...</p>
        </div>
      </main>
    );
  }

  if (error) {
    return (
      <main className="container mx-auto px-6 py-16 flex items-center justify-center min-h-[calc(100vh-8rem)]">
        <div className="text-center space-y-4">
          <h2 className="text-2xl font-bold text-destructive">Failed to load templates</h2>
          <p className="text-muted-foreground">
            {error instanceof Error ? error.message : "Unknown error occurred"}
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="container mx-auto px-6 py-16 space-y-12 min-h-[calc(100vh-8rem)]">
      <section className="max-w-4xl mx-auto space-y-6 text-center animate-fade-in">
        <div className="space-y-4">
          <h1 className="text-5xl font-bold tracking-tight sm:text-6xl">
            <span className="text-gradient">Try Style</span>
          </h1>

          <div className="flex items-center justify-center gap-3">
            <span className="text-lg text-muted-foreground">
              Check out the repository
            </span>
                <Button
                    variant="outline"
                    size="icon"
                    className="hover-glow rounded-full"
                    asChild
                >
                  <a
                      href="https://github.com/art-vozniuk/demo-hub"
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label="GitHub Profile"
                  >
                    <Github className="h-5 w-5"/>
                  </a>
                </Button>
          </div>

          <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
            Select up to {MAX_SELECTION} templates
          </p>
        </div>

        <div ref={counterRef} className="flex justify-center">
          <div
              className={`inline-flex items-center gap-2 px-4 py-2 rounded-full bg-primary/20 border border-primary/30 transition-opacity ${isSticky ? "opacity-0" : "opacity-100"}`}>
            <span className="text-sm font-medium">
              Selected: {selectedTemplates.length}/{MAX_SELECTION}
            </span>
          </div>
        </div>
      </section>

      {isSticky && (
          <div className="fixed top-8 left-1/2 -translate-x-1/2 z-40">
            <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-primary/20 border border-primary/30">
            <span className="text-sm font-medium">
              Selected: {selectedTemplates.length}/{MAX_SELECTION}
            </span>
          </div>
        </div>
      )}

      {selectedTemplates.length > 0 && (
        <div className="fixed bottom-8 left-0 right-0 z-50 flex justify-center animate-fade-in">
          <Button
            onClick={handleGenerate}
            size="lg"
            className="hover-glow text-lg font-semibold px-12 py-6 rounded-full shadow-2xl bg-gradient-to-r from-primary to-primary/80 hover:from-primary/90 hover:to-primary/70 transition-all duration-300 animate-shimmer"
          >
            <Sparkles className="mr-2 h-5 w-5" />
            Generate with {selectedTemplates.length} template{selectedTemplates.length !== 1 ? "s" : ""}
          </Button>
        </div>
      )}

      <section className="max-w-7xl mx-auto">
        {templates && templates.length > 0 ? (
          <Masonry
            breakpointCols={breakpointColumns}
            className="masonry-grid"
            columnClassName="masonry-grid-column"
          >
            {templates.map((template) => {
              const isSelected = selectedTemplates.some((t) => t.id === template.id);
              const isDisabled = selectedTemplates.length >= MAX_SELECTION && !isSelected;

              return (
                <TemplateCard
                  key={template.id}
                  template={template}
                  isSelected={isSelected}
                  isDisabled={isDisabled}
                  onToggle={handleToggleTemplate}
                />
              );
            })}
          </Masonry>
        ) : (
          <div className="text-center py-16">
            <p className="text-lg text-muted-foreground">No templates available</p>
          </div>
        )}
      </section>
    </main>
  );
};

export default FaceFusion;
