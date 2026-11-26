/**
 * The image formats the backend accepts, told apart by their first bytes
 * the way uploads/safe_ingest.py does it. The file's name and the type the
 * picker reports are never trusted. Checking at pick time only saves a
 * wasted upload; the backend still makes the real check.
 */
export function isSupportedImageHead(head: Uint8Array): boolean {
  const starts = (sig: number[], at = 0) => sig.every((b, i) => head[at + i] === b);
  if (starts([0xff, 0xd8, 0xff])) return true; // JPEG
  if (starts([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) return true; // PNG
  return starts([0x52, 0x49, 0x46, 0x46]) && starts([0x57, 0x45, 0x42, 0x50], 8); // RIFF....WEBP
}

export type PickFormat = "ok" | "unsupported" | "unreadable";

/**
 * Whether a pick can be attached: "ok" when every file is a JPEG, PNG or
 * WEBP. If any file's first bytes can't be read (a file moved or deleted
 * after it was picked, or a cloud file the device can't open), the pick
 * is "unreadable", since that file's format can't be known. Never throws.
 */
export async function checkPickFormat(files: File[]): Promise<PickFormat> {
  const heads = await Promise.allSettled(files.map((f) => f.slice(0, 12).arrayBuffer()));
  if (heads.some((h) => h.status === "rejected")) return "unreadable";
  return heads.every((h) => h.status === "fulfilled" && isSupportedImageHead(new Uint8Array(h.value)))
    ? "ok"
    : "unsupported";
}
