import { Github, Linkedin, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import cvPdf from "@/assets/Artem Vozniuk - AI Infrastructure.pdf";

interface SocialIconsProps {
  onLinkedInClick?: () => void;
  onGitHubClick?: () => void;
  onResumeClick?: () => void;
}

const SocialIcons = ({ onLinkedInClick, onGitHubClick, onResumeClick }: SocialIconsProps) => {
  return (
    <div className="flex flex-wrap justify-center gap-2 sm:justify-start">
      <Button variant="outline" size="sm" className="hover-glow rounded-full" asChild>
        <a
          href="https://www.linkedin.com/in/artem-vozniuk-ai/"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="LinkedIn Profile"
          onClick={onLinkedInClick}
        >
          <Linkedin className="h-4 w-4" />
          LinkedIn
        </a>
      </Button>

      <Button variant="outline" size="sm" className="hover-glow rounded-full" asChild>
        <a
          href="https://github.com/art-vozniuk"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="GitHub Profile"
          onClick={onGitHubClick}
        >
          <Github className="h-4 w-4" />
          GitHub
        </a>
      </Button>

      <Button variant="outline" size="sm" className="hover-glow rounded-full" asChild>
        <a
          href={cvPdf}
          download="Artem Vozniuk - AI Infrastructure.pdf"
          aria-label="Download CV"
          onClick={onResumeClick}
        >
          <FileText className="h-4 w-4" />
          Resume
        </a>
      </Button>
    </div>
  );
};

export default SocialIcons;
