import { ReactNode } from "react";
import { Github } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ExpandableDescription } from "@/components/ExpandableDescription";
import CostBadge from "@/components/CostBadge";

type DemoHeaderProps = {
  title: string;
  description: ReactNode;
  githubUrl: string;
  onGithubClick?: () => void;
  cost?: number;
  tagline?: ReactNode;
  children?: ReactNode;
};

export const DemoHeader = ({
  title,
  description,
  githubUrl,
  onGithubClick,
  cost,
  tagline,
  children,
}: DemoHeaderProps) => (
  <section className="max-w-4xl mx-auto space-y-6 text-center animate-fade-in">
    <div className="space-y-4">
      <h1 className="text-5xl font-bold tracking-tight sm:text-6xl flex items-center justify-center gap-3 flex-wrap">
        <span className="text-gradient">{title}</span>
        {cost !== undefined && <CostBadge cost={cost} size="md" />}
      </h1>

      <ExpandableDescription>{description}</ExpandableDescription>

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
                href={githubUrl}
                target="_blank"
                rel="noopener noreferrer"
                aria-label="GitHub Repository"
                onClick={onGithubClick}
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

      {tagline !== undefined && (
        <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
          {tagline}
        </p>
      )}
    </div>
    {children}
  </section>
);

export default DemoHeader;
