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
  <section className="space-y-6 animate-fade-in">
    <div className="space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
          {title}
        </h1>
        {cost !== undefined && <CostBadge cost={cost} />}
      </div>

      <ExpandableDescription className="text-base text-muted-foreground leading-relaxed max-w-3xl">
        {description}
      </ExpandableDescription>

      {tagline !== undefined && (
        <p className="pt-2 text-base font-medium text-muted-foreground/90 max-w-3xl">
          {tagline}
        </p>
      )}
    </div>
    {children}
  </section>
);

export default DemoHeader;
