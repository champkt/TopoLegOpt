import { build } from "esbuild";
import { cp, mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Marked, Renderer } from "marked";

const app = fileURLToPath(new URL("..", import.meta.url));
const repository = path.dirname(app);
const output = path.join(app, "dist-next");
const dist = path.join(app, "dist");
const previous = path.join(app, "dist-old");
const pages = [
  ["README.md", "index.html", "Overview"],
  ["docs/ALGORITHM.md", "algorithm.html", "How it works"],
  ["docs/NPZ_SPEC.md", "npz-spec.html", "NPZ specification"],
  ["docs/DEVELOPMENT.md", "development.html", "Development"],
  ["brick-planner/EXPERIMENTS.md", "experiments.html", "Experiments"],
  ["examples/README.md", "example.html", "Example topology"],
];
const escape = (text) => String(text).replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[char]);

function documentLink(href, source) {
  if (/^(?:[a-z][a-z\d+.-]*:|\/|#)/i.test(href)) return href;
  const [relative, fragment] = href.split("#", 2);
  const target = path.posix.normalize(path.posix.join(path.posix.dirname(source), relative));
  const page = pages.find(([file]) => file === target);
  const suffix = fragment === undefined ? "" : `#${fragment}`;
  if (page) return page[1] + suffix;
  if (target === "docs/references.bib") return "references.bib" + suffix;
  if (target.startsWith("examples/") && !target.endsWith(".md")) return `/${target}${suffix}`;
  return `https://github.com/champkt/TopoLegOpt/blob/main/${target}${suffix}`;
}

async function renderDocument([source, filename, title]) {
  const headings = [];
  const identifiers = new Map();
  const markdown = new Marked();
  markdown.use({ renderer: {
    heading({ tokens, depth, text }) {
      const base = text.toLowerCase().replace(/<[^>]*>/g, "").replace(/[^\p{L}\p{N}_\s-]/gu, "").replace(/\s/g, "-");
      const count = identifiers.get(base) || 0;
      identifiers.set(base, count + 1);
      const id = count ? `${base}-${count}` : base;
      const content = this.parser.parseInline(tokens);
      if (depth === 2) headings.push({ id, text: text.replace(/[`*]/g, "") });
      return `<h${depth} id="${escape(id)}">${content}</h${depth}>\n`;
    },
    link({ href, title, tokens }) {
      return `<a href="${escape(documentLink(href, source))}"${title ? ` title="${escape(title)}"` : ""}>${this.parser.parseInline(tokens)}</a>`;
    },
    table(token) {
      return `<div class="table-scroll" tabindex="0" role="region" aria-label="Reference table">${Renderer.prototype.table.call(this, token)}</div>`;
    },
  } });
  const content = markdown.parse(await readFile(path.join(repository, source), "utf8"));
  const nav = pages.slice(0, 4).map(([, url, label]) => `<a href="${url}"${url === filename ? ' aria-current="page"' : ""}>${escape(label)}</a>`).join("");
  const toc = headings.map(({id, text}) => `<a href="#${escape(id)}">${escape(text)}</a>`).join("");
  await writeFile(path.join(output, "docs", filename), `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="TopoLegOpt documentation: ${escape(title)}"><title>${escape(title)} · TopoLegOpt</title>
<link rel="stylesheet" href="/docs.css"></head><body>
<a class="skip-link" href="#content">Skip to content</a>
<header><a class="brand" href="/">▦ TopoLegOpt</a><a class="back" href="/">← Open planner</a></header>
<nav class="doc-nav" aria-label="Documentation">${nav}</nav>
<div class="doc-layout"><aside><p>On this page</p><nav aria-label="Table of contents">${toc}</nav>
<a class="source-link" href="https://github.com/champkt/TopoLegOpt/blob/main/${source}">View Markdown source ↗</a></aside>
<main id="content"><article>${content}</article><footer>Built from the repository documentation. <a href="/">Return to TopoLegOpt</a></footer></main></div>
</body></html>\n`);
}

await rm(output, { recursive: true, force: true });
await mkdir(path.join(output, "docs"), { recursive: true });
await cp(path.join(app, "web"), output, { recursive: true });
await build({
  absWorkingDir: app,
  entryPoints: {
    app: "src/app.js",
    "topology.bundle": "src/topology.js",
    "topology-worker.bundle": "src/topology-worker.js",
    "assembly.bundle": "src/assembly.js",
  },
  outdir: output,
  bundle: true,
  splitting: true,
  chunkNames: "chunks/[name]-[hash]",
  format: "esm",
  minify: true,
  target: "es2022",
  legalComments: "linked",
});
await Promise.all(pages.map(renderDocument));
await cp(path.join(repository, "docs/references.bib"), path.join(output, "docs/references.bib"));
await cp(path.join(repository, "examples"), path.join(output, "examples"), { recursive: true });
// Publish a completed build; a failed compilation leaves the served files intact.
await rm(previous, { recursive: true, force: true });
let moved = false;
try { await rename(dist, previous); moved = true; }
catch (error) { if (error.code !== "ENOENT") throw error; }
try { await rename(output, dist); }
catch (error) { if (moved) await rename(previous, dist); throw error; }
await rm(previous, { recursive: true, force: true });
console.log("Built planner and shared documentation in dist/.");
