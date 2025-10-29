import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import Masonry from "react-masonry-css";
import { Button } from "@/components/ui/button";
import {Sparkles, Loader2, Github, Linkedin} from "lucide-react";
import { recastApi, type RecastTemplateRead } from "@/api";
import TemplateCard from "@/components/TemplateCard";
import { useAnalytics } from "@/hooks/useAnalytics";
import type { AnalyticsEvent } from "@/types/analytics";
import "./masonry.css";
import {Tooltip, TooltipContent, TooltipTrigger} from "@/components/ui/tooltip.tsx";

const MAX_SELECTION = 6;
const MIN_TEMPLATES_TO_SHOW = 6;

const FaceFusion = () => {
  const navigate = useNavigate();
  const { track } = useAnalytics();
  const [selectedTemplates, setSelectedTemplates] = useState<RecastTemplateRead[]>([]);
  const [isSticky, setIsSticky] = useState(false);
  const counterRef = useRef<HTMLDivElement>(null);
  const [loadedTemplates, setLoadedTemplates] = useState<RecastTemplateRead[]>([]);
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const loadingRef = useRef(false);

  useEffect(() => {
    if (loadingRef.current) return;
    loadingRef.current = true;

    const loadTemplates = async () => {
      try {
        console.log("Fetching templates from API...");
        const templates = await recastApi.getTemplates();
        console.log(`Received ${templates.length} templates from API`);
        
        let loadedCount = 0;
        let initialLoadingCompleted = false;

        templates.forEach((template, index) => {
          const img = new Image();
          
          const handleLoad = () => {
            loadedCount++;
            console.log(`Template ${index + 1}/${templates.length} loaded: ${template.name} (${loadedCount} total)`);
            
            setLoadedTemplates((prev) => {
              console.log(`Adding template to state. Previous count: ${prev.length}, New count: ${prev.length + 1}`);
              return [...prev, template];
            });
            
            if (loadedCount === MIN_TEMPLATES_TO_SHOW && !initialLoadingCompleted) {
              initialLoadingCompleted = true;
              console.log(`Reached ${MIN_TEMPLATES_TO_SHOW} loaded templates - showing page`);
              setIsInitialLoading(false);
              track({ name: 'template_viewed', params: { template_count: MIN_TEMPLATES_TO_SHOW } });
            }
          };
          
          img.onload = handleLoad;
          img.onerror = handleLoad;
          img.src = template.url;
        });
      } catch (err) {
        console.error("Failed to load templates:", err);
        setError(err instanceof Error ? err.message : "Failed to load templates");
        setIsInitialLoading(false);
      }
    };

    loadTemplates();
  }, []);

  const breakpointColumns = {
    default: 4,
    1280: 3,
    1024: 3,
    768: 2,
    640: 2,
  };

  const handleToggleTemplate = (template: RecastTemplateRead) => {
    const isSelected = selectedTemplates.some((t) => t.id === template.id);
    
    if (isSelected) {
      const newLength = selectedTemplates.length - 1;
      const event: AnalyticsEvent = { 
        name: 'template_deselected', 
        params: { 
          template_id: template.id, 
          template_name: template.name,
          total_selected: newLength
        } 
      };
      track(event);
      setSelectedTemplates((prev) => prev.filter((t) => t.id !== template.id));
    } else if (selectedTemplates.length < MAX_SELECTION) {
      const newLength = selectedTemplates.length + 1;
      const event: AnalyticsEvent = { 
        name: 'template_selected', 
        params: { 
          template_id: template.id, 
          template_name: template.name,
          total_selected: newLength
        } 
      };
      track(event);
      setSelectedTemplates((prev) => [...prev, template]);
    } else {
      track({ name: 'max_templates_reached', params: { max_allowed: MAX_SELECTION } });
    }
  };

  const handleGenerate = () => {
    track({ 
      name: 'generate_clicked', 
      params: { template_count: selectedTemplates.length, source: 'face_fusion' } 
    });
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

  if (isInitialLoading) {
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
          <p className="text-muted-foreground">{error}</p>
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
                          aria-label="GitHub Profile"
                          onClick={() => track({ name: 'facefusion_github_repo_clicked', params: {} })}
                      >
                        <Github className="h-5 w-5"/>
                      </a>
                    </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                <p>Visit the repository</p>
              </TooltipContent>
            </Tooltip>

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
        {loadedTemplates.length > 0 ? (
          <Masonry
            breakpointCols={breakpointColumns}
            className="masonry-grid"
            columnClassName="masonry-grid-column"
          >
            {loadedTemplates.map((template) => {
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
