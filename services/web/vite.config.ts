import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";
import fs from "fs";
import https from "https";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const s3Public = env.VITE_S3_PUBLIC_BUCKETS_ENDPOINT || "";
  const rendererDataUrl = env.RENDERER_DATA_URL || "";
  const rendererLocal = env.RENDERER_LOCAL === "true";
  const localBuildDir = path.resolve(__dirname, "../external/renderer/build-web");

  return {
  server: {
    host: "::",
    port: 8085,
    proxy: s3Public && !rendererLocal
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

                // Strip query string — iframe URLs carry ?scene_url=&eye=&fwd=.
                const pathOnly = req.url?.split("?")[0] ?? "";
                if (!pathOnly.endsWith(".html")) {
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
      name: "dev-log-sink",
      configureServer(server) {
        // POST /__dev_log → append to services/external/renderer/dev.log
        // and echo to the Vite terminal. The renderer iframe (Module.print
        // hook in patch_sandbox_html.py) and the React side both fire-and-
        // forget here so the agent has a single tailable timeline of what
        // happened. No request is ever rejected; this is dev-only.
        const devLogPath = path.resolve(__dirname, "../external/renderer/dev.log");
        server.middlewares.use("/__dev_log", (req, res) => {
          if (req.method !== "POST") {
            res.writeHead(405); res.end(); return;
          }
          const chunks: Buffer[] = [];
          req.on("data", (c: Buffer) => chunks.push(c));
          req.on("end", () => {
            const body = Buffer.concat(chunks).toString("utf-8").trim();
            const ts = new Date().toISOString();
            const line = `[${ts}] ${body}\n`;
            try { fs.appendFileSync(devLogPath, line); } catch {}
            process.stdout.write(`[dev-log] ${body}\n`);
            res.writeHead(204); res.end();
          });
        });
      },
    },
    {
      name: "renderer-local-or-proxy",
      configureServer(server) {
        if (rendererLocal) {
          // Serve renderer files from local Emscripten build directory.
          // Usage: RENDERER_LOCAL=true npm run dev
          const mimeTypes: Record<string, string> = {
            ".html": "text/html",
            ".js": "application/javascript",
            ".wasm": "application/wasm",
            ".data": "application/octet-stream",
          };
          // Also serve /renderer/data/<file> from the same local build dir
          server.middlewares.use("/renderer/data/", (req, res, next) => {
            const fileName = req.url?.split("?")[0]?.replace(/^\//, "") || "";
            if (!fileName) return next();
            const filePath = path.join(localBuildDir, fileName);
            if (!fs.existsSync(filePath)) return next();
            const stat = fs.statSync(filePath);
            res.writeHead(200, {
              "content-type": "application/octet-stream",
              "content-length": String(stat.size),
              "cache-control": "no-store",
            });
            fs.createReadStream(filePath).pipe(res);
          });

          server.middlewares.use("/renderer/", (req, res, next) => {
            const fileName = req.url?.split("?")[0]?.replace(/^\//, "") || "";
            if (!fileName) return next();
            const filePath = path.join(localBuildDir, fileName);
            if (!fs.existsSync(filePath)) return next();
            const ext = path.extname(fileName);
            const stat = fs.statSync(filePath);
            res.writeHead(200, {
              "content-type": mimeTypes[ext] || "application/octet-stream",
              "content-length": String(stat.size),
              "cache-control": "no-store",
            });
            fs.createReadStream(filePath).pipe(res);
          });
          return;
        }

        // Remote mode: proxy /renderer/data/<file> from GitHub Releases (302 → Azure Blob).
        server.middlewares.use("/renderer/data/", (req, res) => {
          if (!rendererDataUrl) {
            res.writeHead(502);
            res.end("RENDERER_DATA_URL not set");
            return;
          }
          // Replace Sandbox.data in the base URL with the requested filename
          const fileName = req.url?.split("?")[0]?.replace(/^\//, "") || "Sandbox.data";
          const fileUrl = rendererDataUrl.replace(/\/[^/]+$/, "/" + fileName);
          https.get(fileUrl, (ghRes: any) => {
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
