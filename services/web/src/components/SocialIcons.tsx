import { Github, Linkedin } from "lucide-react";
import { Button } from "@/components/ui/button";

const SocialIcons = () => {
  return (
    <div className="flex justify-center gap-4">
      <Button
        variant="outline"
        size="icon"
        className="hover-glow rounded-full"
        asChild
      >
        <a
          href="https://www.linkedin.com/in/artem-vozniuk-6036b290/"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="LinkedIn Profile"
        >
          <Linkedin className="h-5 w-5" />
        </a>
      </Button>
      <Button
        variant="outline"
        size="icon"
        className="hover-glow rounded-full"
        asChild
      >
        <a
          href="https://github.com/art-vozniuk"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="GitHub Profile"
        >
          <Github className="h-5 w-5" />
        </a>
      </Button>
    </div>
  );
};

export default SocialIcons;
