import { ReactNode } from "react";
import { ExpandableDescription } from "@/components/ExpandableDescription";
import CostBadge from "@/components/CostBadge";

type DemoHeaderProps = {
  title: string;
  description: ReactNode;
  cost?: number;
  tagline?: ReactNode;
  children?: ReactNode;
};

export const DemoHeader = ({
  title,
  description,
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
