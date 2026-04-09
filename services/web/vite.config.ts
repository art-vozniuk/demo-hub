import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";
import https from "https";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const s3Public = env.VITE_S3_PUBLIC_BUCKETS_ENDPOINT || "";
  const rendererDataUrl = env.RENDERER_DATA_URL || "";

  return {
  server: {
    host: "::",
    port: 8085,
    proxy: s3Public
      ? {
          // Other renderer files (html, js, wasm) — proxy from Supabase
          "/renderer/": {
            target: `${s3Public}/media`,
            changeOrigin: true,
            secure: true,
            selfHandleResponse: true,
            configure: (proxy) => {
              // Request uncompressed so we can rewrite HTML body
              proxy.on("proxyReq", (proxyReq) => {
                proxyReq.setHeader("Accept-Encoding", "identity");
              });
              proxy.on("proxyRes", (proxyRes, req, res) => {
                delete proxyRes.headers["content-security-policy"];
                delete proxyRes.headers["x-frame-options"];
                proxyRes.headers["cache-control"] = "no-store";
                delete proxyRes.headers["etag"];

                if (!req.url?.endsWith(".html")) {
                  // Non-HTML: pipe through unchanged
                  res.writeHead(proxyRes.statusCode ?? 200, proxyRes.headers);
                  proxyRes.pipe(res);
                  return;
                }

                // HTML: buffer, strip locateFile redirect, fix Content-Type
                delete proxyRes.headers["content-encoding"];
                delete proxyRes.headers["transfer-encoding"];
                const chunks: Buffer[] = [];
                proxyRes.on("data", (c: Buffer) => chunks.push(c));
                proxyRes.on("end", () => {
                  let body = Buffer.concat(chunks).toString("utf-8");
                  // Remove the Module.locateFile override so .data loads via proxy
                  body = body.replace(
                    /var GH_RELEASE[\s\S]*?Module\.locateFile[\s\S]*?\};[\s]*\}/,
                    "/* locateFile removed — .data served via proxy */"
                  );
                  const buf = Buffer.from(body, "utf-8");
                  proxyRes.headers["content-type"] = "text/html";
                  proxyRes.headers["content-length"] = String(buf.length);
                  res.writeHead(proxyRes.statusCode ?? 200, proxyRes.headers);
                  res.end(buf);
                });
              });
            },
          },
        }
      : undefined,
  },
  plugins: [
    {
      name: "renderer-data-proxy",
      configureServer(server) {
        // Sandbox.data (~250MB) is on GitHub Releases, not Supabase.
        // GitHub 302s to Azure Blob — neither supports CORS.
        // Stream it through our dev server to avoid CORS issues.
        server.middlewares.use("/renderer/Sandbox.data", (_req, res) => {
          if (!rendererDataUrl) {
            res.writeHead(502);
            res.end("RENDERER_DATA_URL not set");
            return;
          }
          https.get(rendererDataUrl, (ghRes: any) => {
            const redirect = ghRes.headers.location;
            if (ghRes.statusCode === 302 && redirect) {
              https.get(redirect, (finalRes: any) => {
                res.writeHead(200, {
                  "content-type": "application/octet-stream",
                  "content-length": finalRes.headers["content-length"] || "",
                  "access-control-allow-origin": "*",
                });
                finalRes.pipe(res);
              });
            } else {
              res.writeHead(ghRes.statusCode ?? 200, {
                "content-type": "application/octet-stream",
                "access-control-allow-origin": "*",
              });
              ghRes.pipe(res);
            }
          });
        });
      },
    },
    react(),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
}});
