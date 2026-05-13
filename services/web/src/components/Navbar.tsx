import { useLayoutEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import { useAnalytics } from "@/hooks/useAnalytics";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { User, LogOut, ChevronDown, List } from "lucide-react";
import TokenBalance from "@/components/TokenBalance";

type NavItem = { to: string; label: string; end?: boolean };

const ALL_LINKS: NavItem[] = [
  { to: "/generative-editing", label: "Generative Editing" },
  { to: "/renderer", label: "Gaussian Splatting" },
  { to: "/face-fusion", label: "Face Swap" },
  { to: "/author", label: "Author", end: true },
];

const Navbar = () => {
  const { user, signOut } = useAuth();
  const { track } = useAnalytics();
  const location = useLocation();
  const navigate = useNavigate();

  const navAreaRef = useRef<HTMLDivElement>(null);
  const measureRef = useRef<HTMLDivElement>(null);
  const [visibleCount, setVisibleCount] = useState(ALL_LINKS.length);

  useLayoutEffect(() => {
    const area = navAreaRef.current;
    const measure = measureRef.current;
    if (!area || !measure) return;

    const compute = () => {
      // Radix dropdowns apply a scroll-lock that adds margin-right to <body>,
      // shrinking the nav. Skip recomputing while locked so items don't
      // collapse into "More" while the user is interacting with a menu.
      if (document.body.hasAttribute("data-scroll-locked")) return;
      const available = area.clientWidth;
      const itemEls = measure.querySelectorAll<HTMLElement>("[data-m-item]");
      const moreEl = measure.querySelector<HTMLElement>("[data-m-more]");
      const moreWidth = moreEl ? moreEl.offsetWidth : 0;
      const gap = parseFloat(getComputedStyle(measure).columnGap || "0") || 0;
      const widths = Array.from(itemEls).map((el) => el.offsetWidth);

      const fullWidth =
        widths.reduce((sum, w) => sum + w, 0) +
        Math.max(0, widths.length - 1) * gap;
      if (fullWidth <= available) {
        setVisibleCount(widths.length);
        return;
      }

      let count = 0;
      let used = 0;
      for (let i = 0; i < widths.length; i++) {
        const after = used + (i > 0 ? gap : 0) + widths[i];
        if (after + gap + moreWidth <= available) {
          count = i + 1;
          used = after;
        } else {
          break;
        }
      }
      setVisibleCount(count);
    };

    compute();

    const ro = new ResizeObserver(compute);
    ro.observe(area);
    ro.observe(measure);

    return () => ro.disconnect();
  }, []);

  const isLinkActive = (link: NavItem) =>
    link.end ? location.pathname === link.to : location.pathname.startsWith(link.to);

  const visibleLinks = ALL_LINKS.slice(0, visibleCount);
  const hiddenLinks = ALL_LINKS.slice(visibleCount);
  const showMore = hiddenLinks.length > 0;
  const isMoreActive = hiddenLinks.some(isLinkActive);

  const handleSignOut = async () => {
    try {
      await signOut();
    } catch (error) {
      console.error('Sign out error:', error);
    }
  };

  const handleMyPipelines = () => {
    track({ name: 'nav_my_pipelines_clicked', params: {} });
    navigate('/me/pipelines');
  };

  const handleNavClick = (to: string) => {
    if (to === "/author") {
      track({ name: 'nav_home_clicked', params: {} });
    } else if (to === "/face-fusion") {
      track({ name: 'nav_facefusion_clicked', params: {} });
    } else if (to === "/generative-editing") {
      track({ name: 'nav_generative_clicked', params: {} });
    } else if (to === "/renderer") {
      track({ name: 'nav_renderer_clicked', params: {} });
    }
  };

  const navLinkClassName = ({ isActive }: { isActive: boolean }) =>
    `relative whitespace-nowrap text-xs sm:text-sm font-medium transition-colors hover:text-primary ${
      isActive ? "text-primary" : "text-muted-foreground"
    } after:absolute after:-bottom-1 after:left-0 after:h-0.5 after:w-full after:origin-left after:scale-x-0 after:bg-primary after:transition-transform after:duration-300 ${
      isActive ? "after:scale-x-100" : "hover:after:scale-x-100"
    }`;

  return (
    <nav className="sticky top-0 z-50 border-b border-border bg-background/80 backdrop-blur-md">
      <div className="container mx-auto flex h-16 items-center gap-3 sm:gap-8 px-3 sm:px-6">
        <h1 className="shrink-0 text-base sm:text-xl font-bold tracking-tight text-gradient">
          Demo Hub
        </h1>

        <div
          ref={navAreaRef}
          className="relative flex min-w-0 flex-1 items-center justify-end"
        >
          <div
            ref={measureRef}
            aria-hidden
            className="pointer-events-none invisible absolute left-0 top-0 flex items-center gap-3 sm:gap-8"
          >
            {ALL_LINKS.map((link) => (
              <span
                key={link.to}
                data-m-item
                className="whitespace-nowrap text-xs sm:text-sm font-medium"
              >
                {link.label}
              </span>
            ))}
            <span
              data-m-more
              className="flex items-center gap-1 whitespace-nowrap text-xs sm:text-sm font-medium"
            >
              More
              <ChevronDown className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
            </span>
          </div>

          <ul className="flex items-center gap-3 sm:gap-8">
            {visibleLinks.map((link) => (
              <li key={link.to}>
                <NavLink
                  to={link.to}
                  end={link.end}
                  onClick={() => handleNavClick(link.to)}
                  className={navLinkClassName}
                >
                  {link.label}
                </NavLink>
              </li>
            ))}
            {showMore && (
              <li>
                <DropdownMenu>
                  <DropdownMenuTrigger
                    aria-label="More navigation"
                    className={`group relative flex items-center gap-1 whitespace-nowrap text-xs sm:text-sm font-medium outline-none transition-colors hover:text-primary data-[state=open]:text-primary ${
                      isMoreActive ? "text-primary" : "text-muted-foreground"
                    } after:absolute after:-bottom-1 after:left-0 after:h-0.5 after:w-full after:origin-left after:scale-x-0 after:bg-primary after:transition-transform after:duration-300 ${
                      isMoreActive ? "after:scale-x-100" : "hover:after:scale-x-100"
                    }`}
                  >
                    More
                    <ChevronDown className="h-3.5 w-3.5 sm:h-4 sm:w-4 transition-transform duration-200 group-data-[state=open]:rotate-180" />
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="min-w-[10rem]">
                    {hiddenLinks.map((link) => (
                      <DropdownMenuItem key={link.to} asChild>
                        <NavLink
                          to={link.to}
                          end={link.end}
                          onClick={() => handleNavClick(link.to)}
                          className={({ isActive }) =>
                            `w-full cursor-pointer ${isActive ? "text-primary font-medium" : ""}`
                          }
                        >
                          {link.label}
                        </NavLink>
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              </li>
            )}
          </ul>
        </div>

        <div className="shrink-0 flex items-center gap-2 sm:gap-3 pl-2 sm:pl-4 border-l border-border">
          <TokenBalance />
          {user ? (
            <DropdownMenu>
              <DropdownMenuTrigger
                aria-label="User menu"
                className="group flex items-center gap-1 sm:gap-1.5 rounded-md px-1.5 sm:px-2 py-1 text-xs sm:text-sm text-muted-foreground outline-none transition-colors hover:text-primary hover:bg-muted/50 data-[state=open]:text-primary data-[state=open]:bg-muted/50"
              >
                <User className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
                <span className="hidden sm:inline">{user.email?.split('@')[0]}</span>
                <ChevronDown className="h-3 w-3 sm:h-3.5 sm:w-3.5 transition-transform duration-200 group-data-[state=open]:rotate-180" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="min-w-[12rem]">
                <DropdownMenuItem
                  onClick={handleMyPipelines}
                  className="cursor-pointer"
                >
                  <List className="mr-2 h-4 w-4" />
                  My Pipelines
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={handleSignOut}
                  className="cursor-pointer"
                >
                  <LogOut className="mr-2 h-4 w-4" />
                  Sign out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <Button
              asChild
              variant="outline"
              size="sm"
              className="h-7 sm:h-8 px-2 sm:px-3 text-xs sm:text-sm"
            >
              <Link to="/auth">Sign in</Link>
            </Button>
          )}
        </div>
      </div>
    </nav>
  );
};

export default Navbar;
