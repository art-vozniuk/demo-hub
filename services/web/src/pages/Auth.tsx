import { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/contexts/AuthContext';
import { useAnalytics } from '@/hooks/useAnalytics';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';

const Auth = () => {
  const { user, loading: authLoading, signInWithGoogle, signInAsTestUser } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { track } = useAnalytics();
  const [isSigningIn, setIsSigningIn] = useState(false);

  const returnPath = location.state?.returnPath || '/face-fusion';
  const selectedTemplates = location.state?.selectedTemplates;
  const autoGenerate = location.state?.autoGenerate;

  useEffect(() => {
    if (!authLoading && user) {
      track({ name: 'auth_completed', params: { provider: 'google' } });
      
      const navState: any = {};
      if (selectedTemplates) {
        navState.selectedTemplates = selectedTemplates;
      }
      
      const searchParams = new URLSearchParams();
      if (autoGenerate) {
        searchParams.set('autoGenerate', 'true');
      }
      
      const finalPath = searchParams.toString() 
        ? `${returnPath}?${searchParams.toString()}` 
        : returnPath;
      
      navigate(finalPath, {
        state: Object.keys(navState).length > 0 ? navState : undefined,
        replace: true,
      });
    }
  }, [user, authLoading, navigate, returnPath, selectedTemplates, autoGenerate, track]);

  const handleSignIn = async () => {
    setIsSigningIn(true);
    try {
      await signInWithGoogle();
    } catch (error) {
      console.error('Sign in error:', error);
      toast.error('Failed to sign in. Please try again.');
      setIsSigningIn(false);
    }
  };

  const handleTestUserSignIn = async () => {
    setIsSigningIn(true);
    try {
      await signInAsTestUser();
    } catch (error) {
      console.error('Test user sign in error:', error);
      toast.error('Failed to sign in as test user. Please try again.');
      setIsSigningIn(false);
    }
  };

  if (authLoading) {
    return (
      <main className="container mx-auto px-6 py-16 flex items-center justify-center min-h-[calc(100vh-8rem)]">
        <Loader2 className="h-8 w-8 animate-spin" />
      </main>
    );
  }

  return (
    <main className="container mx-auto px-6 py-16 flex items-center justify-center min-h-[calc(100vh-8rem)]">
      <div className="max-w-md w-full space-y-8 text-center">
        <div className="space-y-4">
          <h1 className="text-4xl font-bold">Sign In Required</h1>
          <p className="text-lg text-muted-foreground">
            Please sign in to continue. We need authentication to rate limit GPU requests and ensure fair usage for everyone.
          </p>
        </div>

        <div className="space-y-4">
          <Button
            onClick={handleSignIn}
            disabled={isSigningIn}
            size="lg"
            className="w-full text-lg py-6"
          >
            {isSigningIn ? (
              <>
                <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                Signing in...
              </>
            ) : (
              <>
                <svg className="mr-2 h-5 w-5" viewBox="0 0 24 24">
                  <path
                    fill="currentColor"
                    d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                  />
                  <path
                    fill="currentColor"
                    d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                  />
                  <path
                    fill="currentColor"
                    d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                  />
                  <path
                    fill="currentColor"
                    d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                  />
                </svg>
                Sign in with Google
              </>
            )}
          </Button>

          <Button
            onClick={handleTestUserSignIn}
            disabled={isSigningIn}
            variant="secondary"
            size="sm"
            className="w-full"
          >
            Sign In as Test User
          </Button>

          <Button
            onClick={() => navigate(returnPath)}
            variant="ghost"
            className="w-full"
          >
            Go Back
          </Button>
        </div>
      </div>
    </main>
  );
};

export default Auth;
