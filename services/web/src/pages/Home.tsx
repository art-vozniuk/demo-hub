import Avatar from "@/components/Avatar";
import SocialIcons from "@/components/SocialIcons";
import {Link} from "react-router-dom";

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
            Feel free to checkout my <Link to="/face-fusion" className="text-cyan-500 hover:underline">demos</Link> and reach out on LinkedIn, I’m always open to collaboration
            and new ideas.
          </p>
        </div>
        <div className="border-t border-gray-700"/>
        <div className="text-center">
          <h2 className="text-xl font-semibold mb-4">Technologies I’ve had hands-on experience with</h2>
        </div>
        <div className="flex flex-wrap justify-center gap-2 mt-6">
          {['Python', 'C++', 'LLMs', 'Visual AI','Generative AI', 'FastAPI', 'Kubernetes', 'Docker Compose', 'AWS', 'PostgreSQL', 'Terraform',
             'Comfy UI', 'Redis', 'RabbitMQ', 'Sentry', 'Prometheus', 'Grafana', 'Unreal Engine'].map(tag => (
              <span key={tag}
                    className="px-3 py-1 bg-gray-800 text-gray-300 rounded-full text-sm hover:bg-cyan-700 transition">
                {tag}
              </span>
          ))}
        </div>
      </div>
    </main>
  );
};

export default Home;
