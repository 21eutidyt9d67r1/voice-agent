// Bundles the page's modules and the Projects SDK into one browser script with esbuild.
// The preview SDK package targets Node.js. The page only uses its Live client, so the Node-only
// modules the package also imports (its ws transport, proxy agent, and file helpers) become
// empty stubs; the page always passes its own transport (public/live-transport.js).
import { build } from "esbuild";
import { fileURLToPath } from "node:url";

const ENTRY = fileURLToPath(new URL("./public/app.js", import.meta.url));
const NODE_ONLY = /^(ws|https-proxy-agent|node:.+)$/;

let bundle;

/** Builds public/app.js once per process and resolves with the JavaScript text. */
export function browserBundle() {
  bundle ??= build({
    entryPoints: [ENTRY],
    bundle: true,
    format: "esm",
    platform: "browser",
    target: "es2022",
    write: false,
    logLevel: "silent",
    plugins: [
      {
        name: "node-only-stubs",
        setup(builder) {
          builder.onResolve({ filter: NODE_ONLY }, ({ path }) => ({ path, namespace: "node-only" }));
          builder.onLoad({ filter: /.*/, namespace: "node-only" }, () => ({
            contents: "module.exports = {};",
            loader: "js",
          }));
        },
      },
    ],
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}
