import { Button } from "@/components/ui/button";
import { ArrowLeft, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";

const ComingSoon = () => {
  return (
    <main className="flex min-h-[calc(100vh-8rem)] items-center justify-center px-6">
      <div className="max-w-2xl space-y-8 text-center animate-fade-in">
        <div className="mx-auto w-fit rounded-full bg-primary/10 p-6">
          <Sparkles className="h-16 w-16 text-primary" />
        </div>

        <div className="space-y-4">
          <h1 className="text-5xl font-bold tracking-tight sm:text-6xl">
            Coming <span className="text-gradient">Soon</span>
          </h1>
          <p className="mx-auto max-w-xl text-lg leading-relaxed text-muted-foreground">
            Stay tuned for more interactive experiences.
          </p>
        </div>

        <Button asChild size="lg" className="hover-glow">
          <Link to="/">
            <ArrowLeft className="mr-2 h-5 w-5" />
            Back to Home
          </Link>
        </Button>
      </div>
    </main>
  );
};

export default ComingSoon;
