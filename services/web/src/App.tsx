import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "./contexts/AuthContext";
import { WalletProvider } from "./contexts/WalletContext";
import { AnalyticsProvider } from "./contexts/AnalyticsContext";
import { AppErrorBoundary } from "./components/AppErrorBoundary";
import Navbar from "./components/Navbar";
import Footer from "./components/Footer";
import Home from "./pages/Home";
import FaceFusion from "./pages/FaceFusion";
import FaceFusionGenerate from "./pages/FaceFusionGenerate";
import GenerativeEditing from "./pages/GenerativeEditing";
import GenerativeEditingGenerate from "./pages/GenerativeEditingGenerate";
import Renderer from "./pages/Renderer";
import Sharp from "./pages/Sharp";
import Auth from "./pages/Auth";
import MyPipelines from "./pages/MyPipelines";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient();

const App = () => (
  <AppErrorBoundary>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <Toaster />
        <Sonner />
        <BrowserRouter>
          <AnalyticsProvider>
            <AuthProvider>
              <WalletProvider>
                <div className="flex min-h-screen flex-col">
                  <Navbar />
                  <div className="flex-1">
                    <Routes>
                      <Route path="/" element={<Navigate to="/generative-editing" replace />} />
                      <Route path="/author" element={<Home />} />
                      <Route path="/face-fusion" element={<FaceFusion />} />
                      <Route path="/face-fusion/generate" element={<FaceFusionGenerate />} />
                      <Route path="/generative-editing" element={<GenerativeEditing />} />
                      <Route path="/generative-editing/generate" element={<GenerativeEditingGenerate />} />
                      <Route path="/renderer" element={<Renderer />} />
                      <Route path="/sharp" element={<Sharp />} />
                      <Route path="/me/pipelines" element={<MyPipelines />} />
                      <Route path="/auth" element={<Auth />} />
                      <Route path="*" element={<NotFound />} />
                    </Routes>
                  </div>
                </div>
              </WalletProvider>
            </AuthProvider>
          </AnalyticsProvider>
        </BrowserRouter>
      </TooltipProvider>
    </QueryClientProvider>
  </AppErrorBoundary>
);

export default App;
