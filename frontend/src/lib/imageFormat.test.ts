// Run by `npm test` and by prebuild: node --test, no test framework.
import { test } from "node:test";
import assert from "node:assert/strict";
import { allSupportedImages, isSupportedImageHead } from "./imageFormat.ts";

const bytes = (...parts: (number[] | string)[]) =>
  new Uint8Array(parts.flatMap((p) => (typeof p === "string" ? [...p].map((c) => c.charCodeAt(0)) : p)));

const JPEG = bytes([0xff, 0xd8, 0xff, 0xe0]);
const PNG = bytes([0x89], "PNG", [0x0d, 0x0a, 0x1a, 0x0a]);
const WEBP = bytes("RIFF", [0x24, 0, 0, 0], "WEBPVP8 ");
const GIF = bytes("GIF89a");

test("JPEG, PNG and WEBP are accepted by their first bytes", () => {
  assert.ok(isSupportedImageHead(JPEG));
  assert.ok(isSupportedImageHead(PNG));
  assert.ok(isSupportedImageHead(WEBP));
});

test("GIF, other RIFF files and short or empty files are refused", () => {
  assert.equal(isSupportedImageHead(GIF), false);
  assert.equal(isSupportedImageHead(bytes("RIFF", [0, 0, 0, 0], "WAVE")), false);
  assert.equal(isSupportedImageHead(bytes([0xff, 0xd8])), false);
  assert.equal(isSupportedImageHead(new Uint8Array()), false);
});

test("a pick passes only when every file is supported", async () => {
  const file = (b: Uint8Array, name: string) => new File([b.buffer as ArrayBuffer], name, { type: "image/jpeg" });
  assert.equal(await allSupportedImages([file(JPEG, "a.jpg"), file(PNG, "b.png")]), true);
  // The name and the reported type say JPEG; the bytes say GIF.
  assert.equal(await allSupportedImages([file(JPEG, "a.jpg"), file(GIF, "b.jpg")]), false);
});
