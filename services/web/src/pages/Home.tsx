import Avatar from "@/components/Avatar";
import SocialIcons from "@/components/SocialIcons";
import { Link } from "react-router-dom";
import demoVideo from "@/assets/RoleCall.mp4";
import recommendationsImage from "@/assets/recommendations.png";

const Home = () => {
  return (
    <main className="flex min-h-[calc(100vh-8rem)] items-center justify-center px-6 py-16">
      <div className="max-w-2xl space-y-8 text-center animate-fade-in">
        <Avatar />
        <SocialIcons />

        <div className="space-y-4">
          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl leading-tight">
            Senior Software Engineer<br/>
            <span className="text-gradient">AI Infrastructure & R&D</span>
          </h1>

          <p className="mx-auto max-w-xl text-lg leading-relaxed text-muted-foreground">
            I’m a software engineer with over a decade of experience building high-performance systems and
            end-to-end infrastructure for Generative AI.
            My background in C++ and applied mathematics helps me bridge low-level performance engineering with
            modern AI infrastructure.
            Feel free to explore my{" "}
            <Link to="/face-fusion" className="text-cyan-500 hover:underline">
              demos
            </Link>{" "}
            or reach out on{" "}
            <Link
              to="https://www.linkedin.com/in/artem-vozniuk-6036b290/"
              className="text-cyan-500 hover:underline"
            >
              LinkedIn
            </Link>
            — I’m always open to collaboration and new ideas.
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
            "Docker Compose",
            "AWS",
            "PostgreSQL",
            "Terraform",
            "Comfy UI",
            "Redis",
            "RabbitMQ",
            "Sentry",
            "Prometheus",
            "Grafana",
            "Unreal Engine",
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

        <div className="text-center">
          <h2 className="text-2xl font-semibold mb-4">My Experience</h2>
        </div>

        {/* Allegory */}
        <div className="text-left">
          <h2 className="text-xl font-semibold mb-4 text-left">Allegory (09.2024 – now)</h2>
          <div className="space-y-4">
            <p className="text-lg leading-relaxed text-muted-foreground text-left">
              Building a Generative AI platform with an orchestration system for image, video, and multimodal
              workflows.
            </p>

            <ul className="list-disc list-inside text-lg leading-relaxed text-muted-foreground text-left space-y-1">
              <li>
                Designed and implemented full backend and infrastructure using FastAPI, Kubernetes, Terraform, AWS,
                PostgreSQL, and Redis.
              </li>
              <li>
                Created a declarative YAML-based workflow engine integrating LLMs, diffusion pipelines (SDXL, Flux,
                Hedra), and OpenAI APIs for multimodal generation.
              </li>
              <li>
                Implemented observability stack with Prometheus, Grafana, and Sentry, and CI/CD with GitHub Actions.
              </li>
              <li>
                Enabled rapid prototyping by allowing non-engineers to define and deploy new workflows within minutes.
              </li>
              <li>
                Collaborated with frontend engineers to deliver AI-powered MVPs in Next.js and React Native.
              </li>
            </ul>

            <div className="mt-8">
              <h3 className="text-lg font-semibold mb-2">Demo Video</h3>
              <video
                className="max-w-xs w-full rounded-2xl shadow-lg"
                controls
                playsInline
                src={demoVideo}
              />
            </div>
          </div>
        </div>

        {/* Inworld AI */}
        <div className="text-left">
          <h2 className="text-xl font-semibold mb-4 text-left">Inworld AI (02.2022 – 09.2024)</h2>
          <div className="space-y-4">
            <p className="text-lg leading-relaxed text-muted-foreground text-left">
              <Link to="https://inworld.ai/" className="text-cyan-500 hover:underline">
                Inworld
              </Link>{" "}
              provides a scalable AI infrastructure platform that enables developers to deploy real-time, multi-modal AI experiences.
              I worked on cross-platform C++ SDKs and on-device inference systems to support low-latency workflows, optimized for production at scale.
            </p>

            <ul className="list-disc list-inside text-lg leading-relaxed text-muted-foreground text-left space-y-1">
              <li>
                Designed and launched cross-platform C++ SDKs with gRPC-based real-time communication for AI
                characters.
              </li>
              <li>
                Implemented edge inference for low-latency features such as VAD (Silero) and Whisper speech-to-text.
              </li>
              <li>
                Built Unreal Engine SDK from scratch, reducing integration time to minutes.
              </li>
              <li>
                Created CI/CD pipelines for cross-platform builds via GitHub Actions (Windows, macOS, Linux, iOS,
                Android).
              </li>
              <li>
                Collaborated with partners including NVIDIA, Ubisoft, and Disney to develop technical demos and
                integrations.
              </li>
            </ul>
          </div>
        </div>

        {/* Game Development */}
        <div className="text-left">
          <h2 className="text-xl font-semibold mb-4 text-left">Game Development (02.2014 – 01.2022)</h2>
          <div className="space-y-4">
            <p className="text-lg leading-relaxed text-muted-foreground text-left">
              Worked at{" "}
              <Link to="https://saber.games/" className="text-cyan-500 hover:underline">
                Saber Interactive
              </Link>{" "}
              ,{" "}
              <Link
                to="https://www.themultiplayergroup.com/"
                className="text-cyan-500 hover:underline"
              >
                The Multiplayer Group
              </Link>
              {" "}and{" "}
              <Link
                to="https://playrix.com/"
                className="text-cyan-500 hover:underline"
              >
                Playrix
              </Link>
              , contributing to AAA and mobile titles such as <strong>Quake Champions</strong>, {" "}
              <strong>World War Z</strong>, <strong>Gardenscapes</strong> and more.
              Specialized in gameplay, and engine systems, with deep experience in C++, low-level
              optimizations, and cross-platform performance (PC, consoles, mobile).
            </p>
          </div>
        </div>

        {/* Recommendations */}
        <div className="text-left">
          <h2 className="text-xl font-semibold mb-4 text-left">Recommendations</h2>
          <div className="space-y-4">
            <img
              src={recommendationsImage}
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