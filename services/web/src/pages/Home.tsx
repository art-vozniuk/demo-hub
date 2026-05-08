import { useEffect, useState } from "react";
import Avatar from "@/components/Avatar";
import SocialIcons from "@/components/SocialIcons";
import { Link } from "react-router-dom";
import { useAnalytics } from "@/hooks/useAnalytics";
import recommendationsImage1 from "@/assets/recs1.png";
import recommendationsImage2 from "@/assets/recs2.png";
import recommendationsImage3 from "@/assets/recs3.png";
import recommendationsImage4 from "@/assets/recs4.png";

const Home = () => {
  const { track } = useAnalytics();
  const [hasTrackedScroll, setHasTrackedScroll] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      if (hasTrackedScroll) return;

      const scrollPosition = window.innerHeight + window.scrollY;
      const documentHeight = document.documentElement.scrollHeight;

      if (scrollPosition >= documentHeight - 100) {
        track({ name: 'home_scrolled_to_bottom', params: {} });
        setHasTrackedScroll(true);
      }
    };

    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, [hasTrackedScroll, track]);

  return (
    <main className="flex min-h-[calc(100vh-8rem)] items-center justify-center px-6 py-16">
      <div className="max-w-2xl space-y-8 text-center animate-fade-in">
        <Avatar />
        <SocialIcons
          onLinkedInClick={() => track({ name: 'home_linkedin_clicked', params: {} })}
          onGitHubClick={() => track({ name: 'home_github_clicked', params: {} })}
          onResumeClick={() => track({ name: 'home_resume_clicked', params: {} })}
        />

        <div className="space-y-4">
          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl leading-tight">
            Software Engineer<br/>
            <span className="text-gradient">ML Serving Infrastructure, GPU Systems, Scalable Distributed Backends</span>
          </h1>

          <p className="mx-auto max-w-xl text-lg leading-relaxed text-muted-foreground">
            Focused on high-performance systems, real-time AI, and turning complex ideas into working products.
            Feel free to explore my{" "}
            <Link to="/renderer" className="text-cyan-500 hover:underline">
              demos
            </Link>{" "}
            or reach out on{" "}
            <Link
                to="https://www.linkedin.com/in/artem-vozniuk-ai/"
                className="text-cyan-500 hover:underline"
            >
              LinkedIn.
            </Link>
             I’m always open to collaboration and new ideas.
          </p>
        </div>

        <div className="border-t border-gray-700" />

        <div className="text-center">
          <h2 className="text-xl font-semibold mb-4">Technologies I’ve worked with</h2>
        </div>

        <div className="flex flex-wrap justify-center gap-2 mt-6">
          {[
            "Python",
            "C++",
            "Generative AI",
            "LLMs",
            "Visual AI",
            "PyTorch",
            "ONNX Runtime",
            "FastAPI",
            "Kubernetes",
            "Docker",
            "AWS",
            "PostgreSQL",
            "Terraform",
            "Supabase",
            "Comfy UI",
            "Redis",
            "RabbitMQ",
            "Sentry",
            "Prometheus",
            "Grafana",
            "React",
            "Unreal Engine",
            "WebGPU",
          ].map((tag) => (
            <span
              key={tag}
              className="px-3 py-1 bg-gray-800 text-gray-300 rounded-full text-sm hover:bg-cyan-700 transition"
            >
              {tag}
            </span>
          ))}
        </div>

        <div className="border-t border-gray-700" />

        {/* Recommendations */}
        <div className="text-left">
          <h2 className="text-xl font-semibold mb-4 text-left">Recommendations</h2>
          <div className="space-y-4">
            <img
                src={recommendationsImage1}
                alt="Recommendations"
                className="rounded-2xl shadow-lg w-full mx-auto text-left"
            />
            <img
                src={recommendationsImage2}
                alt="Recommendations"
                className="rounded-2xl shadow-lg w-full mx-auto text-left"
            />
            <img
                src={recommendationsImage3}
                alt="Recommendations"
                className="rounded-2xl shadow-lg w-full mx-auto text-left"
            />
            <img
                src={recommendationsImage4}
                alt="Recommendations"
                className="rounded-2xl shadow-lg w-full mx-auto text-left"
            />
          </div>
        </div>
      </div>
    </main>
  );
};

export default Home;