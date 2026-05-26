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
import Flux from "./pages/Flux";
import FluxCustom from "./pages/FluxCustom";
import FluxGenerate from "./pages/FluxGenerate";
import Renderer from "./pages/Renderer";
import Editor from "./pages/Editor";
import Sharp from "./pages/Sharp";
import SharpViewer from "./pages/SharpViewer";
import TrellisViewer from "./pages/TrellisViewer";
import Auth from "./pages/Auth";
import MyPipelines from "./pages/MyPipelines";
import PipelineShare from "./pages/PipelineShare";
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
                      <Route path="/" element={<Navigate to="/flux" replace />} />
                      <Route path="/author" element={<Home />} />
                      <Route path="/face-fusion" element={<FaceFusion />} />
                      <Route path="/face-fusion/generate" element={<FaceFusionGenerate />} />
                      <Route path="/flux" element={<Flux />} />
                      <Route path="/flux/generate" element={<FluxGenerate />} />
                      <Route path="/flux/custom" element={<FluxCustom />} />
                      <Route path="/renderer" element={<Renderer />} />
                      <Route path="/editor" element={<Editor />} />
                      <Route path="/sharp" element={<Sharp />} />
                      <Route path="/sharp/view" element={<SharpViewer />} />
                      <Route path="/trellis/view" element={<TrellisViewer />} />
                      <Route path="/me/pipelines" element={<MyPipelines />} />
                      <Route path="/p/:pipelineId" element={<PipelineShare />} />
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
