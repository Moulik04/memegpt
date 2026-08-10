#!/usr/bin/env node
// Drives the real Chat UI end to end: navigate, type a message, submit,
// wait for a rendered meme, screenshot. See SKILL.md for prerequisites
// (backend + frontend must already be running) and usage.
//
// Usage:
//   node driver.mjs chat "<message>" [outfile.png]
//   node driver.mjs screenshot <path> [outfile.png]

import { chromium } from "playwright";

const BASE_URL = process.env.MEMEGPT_FRONTEND_URL || "http://127.0.0.1:3000";
const [, , cmd, ...rest] = process.argv;

async function withPage(fn) {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1000, height: 900 } });
  try {
    return await fn(page);
  } finally {
    await browser.close();
  }
}

async function cmdChat(message, outfile = "chat-result.png") {
  await withPage(async (page) => {
    // networkidle, not domcontentloaded — Next.js hydration needs to finish
    // before this controlled input's React state will actually update.
    await page.goto(`${BASE_URL}/chat`, { waitUntil: "networkidle" });
    const input = page.locator('input[type="text"]');
    await input.waitFor({ state: "visible", timeout: 15000 });
    await input.click();
    // .fill() does not reliably trigger this input's onChange (confirmed:
    // the submit button stayed disabled after .fill()) — real keystrokes do.
    await page.keyboard.type(message, { delay: 15 });
    await page.locator('button[type="submit"]').click();

    // A real Groq round trip (segmentation + RAG + intent routing +
    // compositor) takes several seconds; 45s covers a cold path.
    const meme = page.locator(".meme-reveal img").first();
    await meme.waitFor({ state: "visible", timeout: 45000 });

    await page.screenshot({ path: outfile, fullPage: false });
    console.log(`OK: meme rendered, screenshot saved to ${outfile}`);
  });
}

async function cmdScreenshot(path, outfile = "screenshot.png") {
  await withPage(async (page) => {
    await page.goto(`${BASE_URL}${path}`, { waitUntil: "networkidle" });
    await page.screenshot({ path: outfile, fullPage: true });
    console.log(`OK: screenshot saved to ${outfile}`);
  });
}

try {
  if (cmd === "chat") {
    await cmdChat(rest[0], rest[1]);
  } else if (cmd === "screenshot") {
    await cmdScreenshot(rest[0], rest[1]);
  } else {
    console.error("Usage: node driver.mjs chat \"<message>\" [outfile.png]");
    console.error("       node driver.mjs screenshot <path> [outfile.png]");
    process.exit(1);
  }
} catch (err) {
  console.error("FAILED:", err.message);
  process.exit(1);
}
