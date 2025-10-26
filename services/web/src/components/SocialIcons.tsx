import { Github, Linkedin, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import cvPdf from "@/assets/Artem Vozniuk AI infra & R&D.pdf";

const SocialIcons = () => {
  return (
    <TooltipProvider>
      <div className="flex justify-center gap-4">
        <Tooltip>
          <TooltipTrigger asChild>
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
          </TooltipTrigger>
          <TooltipContent side="bottom">
            <p>Visit LinkedIn profile</p>
          </TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
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
          </TooltipTrigger>
          <TooltipContent side="bottom">
            <p>Visit GitHub profile</p>
          </TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              size="icon"
              className="hover-glow rounded-full"
              asChild
            >
              <a
                href={cvPdf}
                download="Artem Vozniuk AI infra & R&D.pdf"
                aria-label="Download CV"
              >
                <FileText className="h-5 w-5" />
              </a>
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">
            <p>Download CV</p>
          </TooltipContent>
        </Tooltip>
      </div>
    </TooltipProvider>
  );
};

export default SocialIcons;
