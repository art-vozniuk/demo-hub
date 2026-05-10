import { NavLink } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import { useAnalytics } from "@/hooks/useAnalytics";
import { Button } from "@/components/ui/button";
import { User, LogOut } from "lucide-react";

const Navbar = () => {
  const { user, signOut } = useAuth();
  const { track } = useAnalytics();
  
  const navLinks = [
    { to: "/generative-editing", label: "Generative Editing" },
    { to: "/face-fusion", label: "Face Swap" },
    { to: "/renderer", label: "Gaussian Splatting" },
    { to: "/author", label: "Author" },
  ];

  const handleSignOut = async () => {
    try {
      await signOut();
    } catch (error) {
      console.error('Sign out error:', error);
    }
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

  return (
    <nav className="sticky top-0 z-50 border-b border-border bg-background/80 backdrop-blur-md">
      <div className="container mx-auto flex h-16 items-center justify-between px-3 sm:px-6">
        <h1 className="text-base sm:text-xl font-bold tracking-tight text-gradient">
          <span className="hidden sm:inline">Demo Hub</span>
          <span className="sm:hidden">Demo Hub</span>
        </h1>
        
        <div className="flex items-center gap-3 sm:gap-8">
          <ul className="flex gap-3 sm:gap-8">
            {navLinks.map((link) => (
              <li key={link.to}>
                <NavLink
                  to={link.to}
                  end={link.to === "/author"}
                  onClick={() => handleNavClick(link.to)}
                  className={({ isActive }) =>
                    `relative text-xs sm:text-sm font-medium transition-colors hover:text-primary ${
                      isActive ? "text-primary" : "text-muted-foreground"
                    } after:absolute after:-bottom-1 after:left-0 after:h-0.5 after:w-full after:origin-left after:scale-x-0 after:bg-primary after:transition-transform after:duration-300 ${
                      isActive ? "after:scale-x-100" : "hover:after:scale-x-100"
                    }`
                  }
                >
                  {link.label}
                </NavLink>
              </li>
            ))}
          </ul>

          {user && (
            <div className="flex items-center gap-2 sm:gap-3 pl-2 sm:pl-4 border-l border-border">
              <div className="flex items-center gap-1 sm:gap-2 text-xs sm:text-sm text-muted-foreground">
                <User className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
                <span className="hidden sm:inline">{user.email?.split('@')[0]}</span>
              </div>
              <Button
                onClick={handleSignOut}
                variant="ghost"
                size="sm"
                className="h-7 sm:h-8 px-1.5 sm:px-2"
              >
                <LogOut className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
              </Button>
            </div>
          )}
        </div>
      </div>
    </nav>
  );
};

export default Navbar;
