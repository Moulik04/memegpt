// Fails the build when a class from the old dark theme comes back, or when
// the brand red is used as a fill outside Arc. Runs as `prebuild`, so a
// Vercel preview build fails on a violation. See docs/redesign-handoff.md,
// sections 2 and 10.
//
// It also fails on pill-shaped controls and on em dashes in UI strings
// (TEXT_RULES below), which the handoff rules out.

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const SRC = join(ROOT, "src");

// Arc is the one place solid red blocks are allowed.
const ARC_FILES = [/^components\/ArcView\.tsx$/, /^app\/arc\//];

const RULES = [
  {
    name: "raw gray, white or black class (use the tokens)",
    pattern:
      /(?<![\w-])(?:[a-z-]+:)*(?:text|bg|border|ring|divide|placeholder|fill|stroke|outline|from|to|via|shadow|decoration)-(?:gray|zinc|neutral|slate|stone|white|black)(?:-\d+)?(?:\/\d+)?(?![\w-])/g,
  },
  {
    name: "raw palette color class (use the tokens: brand for red, destructive for error text)",
    pattern:
      /(?<![\w-])(?:[a-z-]+:)*(?:text|bg|border|ring|divide|placeholder|fill|stroke|outline|from|to|via|shadow|decoration|accent|caret)-(?:red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d+(?:\/\d+)?(?![\w-])/g,
  },
  {
    name: "dark: variant (there is no dark theme)",
    pattern: /(?<![\w-])(?:[a-z-]+:)*dark:[\w[\]/.:-]+/g,
  },
  {
    name: "brand-red fill outside Arc (red is for rules, underlines and type)",
    pattern: /(?<![\w-])(?:[a-z-]+:)*bg-brand(?:\/\d+)?(?![\w-])/g,
    skip: (file) => ARC_FILES.some((re) => re.test(file)),
  },
];

// Text rules: checked on code and copy only, with comments stripped, and
// not in tests, whose fixtures may hold these characters on purpose.
const TEXT_RULES = [
  { item: "pill-shaped controls (rounded-full); the handoff avoids pills", pattern: /(?<![\w-])rounded-full(?![\w-])/ },
  // Comment lines are skipped below, so this only flags code and copy.
  { item: "em dash in a UI string", pattern: /\u2014/, code: true },
];

const COMMENT = /^\s*(?:\/\/|\/\*|\*|\{\/\*)/;

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path);
    return /\.(tsx?|css)$/.test(name) ? [path] : [];
  });
}

const failures = [];
for (const path of files(SRC)) {
  const file = relative(SRC, path).split(sep).join("/");
  const lines = readFileSync(path, "utf8").split("\n");
  lines.forEach((line, i) => {
    for (const rule of RULES) {
      if (rule.skip?.(file)) continue;
      for (const match of line.matchAll(rule.pattern)) {
        failures.push(`  src/${file}:${i + 1}  ${match[0]}  (${rule.name})`);
      }
    }
    if (/\.test\.tsx?$/.test(file)) return;
    for (const { item, pattern, code } of TEXT_RULES) {
      if (code && file.endsWith(".css")) continue;
      const text = code ? (COMMENT.test(line) ? "" : line.replace(/\/\*.*?\*\//g, "").replace(/\s\/\/.*$/, "")) : line;
      if (pattern.test(text)) failures.push(`  src/${file}:${i + 1}  (${item})`);
    }
  });
}

if (failures.length) {
  console.error(`check-tokens: ${failures.length} violation(s):\n${failures.join("\n")}`);
  process.exit(1);
}
console.log("check-tokens: OK");
