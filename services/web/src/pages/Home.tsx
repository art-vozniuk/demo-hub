import Avatar from "@/components/Avatar";
import SocialIcons from "@/components/SocialIcons";
import {Link} from "react-router-dom";
import demoVideo from "@/assets/RoleCall.mp4";
import recommendationsImage from "@/assets/recommendations.png";

const Home = () => {
  return (
    <main className="flex min-h-[calc(100vh-8rem)] items-center justify-center px-6 py-16">
      <div className="max-w-2xl space-y-8 text-center animate-fade-in">
        <Avatar/>
        <SocialIcons/>

        <div className="space-y-4">
          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
            Senior Software Engineer & <span className="text-gradient">Generative AI Enthusiast</span>
          </h1>

          <p className="mx-auto max-w-xl text-lg leading-relaxed text-muted-foreground">
            For the past few years, I’ve been building Generative AI solutions from the ground up, from end-to-end MVPs
            and infrastructure to model deployment and optimization.
            With 10+ years of experience developing high-performance cross-platform systems in C++, supported by a
            background in Applied Mathematics.
            Feel free to checkout my <Link to="/face-fusion" className="text-cyan-500 hover:underline">demos</Link> and
            reach out on <Link to="https://www.linkedin.com/in/artem-vozniuk-6036b290/" className="text-cyan-500 hover:underline">LinkedIn</Link>,
            I’m always open to collaboration and new ideas.
          </p>
        </div>
        <div className="border-t border-gray-700"/>
        <div className="text-center">
          <h2 className="text-xl font-semibold mb-4">Technologies I’ve worked with</h2>
        </div>
        <div className="flex flex-wrap justify-center gap-2 mt-6">
          {['Python', 'C++', 'LLMs', 'Visual AI', 'Generative AI', 'FastAPI', 'Kubernetes', 'Docker Compose', 'AWS', 'PostgreSQL', 'Terraform',
            'Comfy UI', 'Redis', 'RabbitMQ', 'Sentry', 'Prometheus', 'Grafana', 'Unreal Engine'].map(tag => (
              <span key={tag}
                    className="px-3 py-1 bg-gray-800 text-gray-300 rounded-full text-sm hover:bg-cyan-700 transition">
                {tag}
              </span>
          ))}
        </div>
        <div className="border-t border-gray-700"/>
        <div className="text-center">
          <h2 className="text-2xl font-semibold mb-4">My Experience</h2>
        </div>

        <div className="text-left">
          <h2 className="text-xl font-semibold mb-4 text-left">Allegory (09.2024 - now)</h2>
          <div className="space-y-4">
            <p className="text-lg leading-relaxed text-muted-foreground text-left">
              Developing a Snapchat-like app with Generative AI.
            </p>

            <ul className="list-disc list-inside text-lg leading-relaxed text-muted-foreground text-left space-y-1">
              <li>Built end-to-end infrastructure for GenAI orchestration using FastAPI, Kubernetes, Terraform,
                TeamCity, PostgreSQL, Redis.
              </li>
              <li>Orchestrated APIs and custom diffusion models with deployment in Comfy UI, production-ready
                pipelines.
              </li>
              <li>Implemented full observability stack with Prometheus, Grafana, Sentry.</li>
              <li>Experimented with AI agents, including a chatbot for image & video generation.</li>
              <li>Collaborated with frontend engineers to deliver MVPs in Next.js, React Native, TypeScript.</li>
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

        <div className="text-left">
          <h2 className="text-xl font-semibold mb-4 text-left">Inworld AI (02.2022 - 09.2024)</h2>
          <div className="space-y-4">
            <p className="text-lg leading-relaxed text-muted-foreground text-left">
              <Link to="https://inworld.ai/" className="text-cyan-500 hover:underline">Inworld</Link> provides solutions
              for growing AI applications,
              allowing teams to build and deploy AI workloads at scale, cut the amount of time they spend on
              maintenance, and dramatically
              accelerate iteration speed.
            </p>

            <ul className="list-disc list-inside text-lg leading-relaxed text-muted-foreground text-left space-y-1">
              <li>Designed and launched SDKs for the platform from the ground up, successfully deploying them to
                production.
              </li>
              <li>Launched C++ edge inference.</li>
              <li>Implemented GitHub CI/CD for cross platform SDKs.</li>
              <li>Facilitated partner and client onboarding processes and provided continuous technical support.</li>
            </ul>
          </div>
        </div>

        <div className="text-left">
          <h2 className="text-xl font-semibold mb-4 text-left">Game Development (02.2014 - 01.2022)</h2>
          <div className="space-y-4">
            <p className="text-lg leading-relaxed text-muted-foreground text-left">
              Worked in the game development industry at <Link to="https://saber.games/"
                                                               className="text-cyan-500 hover:underline">Saber
              Interactive </Link>
              and <Link to="https://www.themultiplayergroup.com/" className="text-cyan-500 hover:underline">The
              Multiplayer Group</Link> , contributing to multiple AAA
              and mid-size projects in various roles.
              Experience includes gameplay programming, physics systems, and partial involvement in graphics and
              networking features.
              Skilled in working with Unreal Engine as well as proprietary in-house engines.
              Strong focus on C++, low-level optimizations, and cross-platform development to ensure performance and
              scalability across different platforms.
            </p>
          </div>
        </div>

        <div className="text-left">
          <h2 className="text-xl font-semibold mb-4 text-left">Recommendations</h2>
          <div className="space-y-4">
            <img
                src={recommendationsImage}
                alt="Gameplay Screenshot"
                className="rounded-2xl shadow-lg w-full mx-auto text-left"
            />
          </div>
        </div>
      </div>
    </main>
  );
};

export default Home;
