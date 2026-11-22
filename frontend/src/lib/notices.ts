import type { UploadErrorCode } from "@/types";

/** Client-side limits, checked as photos are picked. The backend enforces
 * the real ones (config.py); these only save a wasted upload. */
export const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
export const MAX_IMAGES_PER_MESSAGE = 6;

/** Notices from the copy deck. Wording lives here, not in the backend. */
export const PICK_TOO_LARGE = "That image is over 10MB. Try a smaller one.";
export const PICK_TOO_MANY = "Up to 6 photos per message. Remove some before adding more.";

const UPLOAD_ERRORS: Record<UploadErrorCode, string> = {
  image_refused: "MemeGPT can't use this image. Try describing it in words instead.",
  file_too_large: PICK_TOO_LARGE,
  unrecognized_file_type: "That file isn't a supported image format. Try a JPEG, PNG, or WEBP.",
  dimensions_too_large: "That image's dimensions are too large to process. Try a smaller one.",
  invalid_image: "That file couldn't be read as an image. It may be corrupted.",
  upload_failed: "Upload failed. The one engineer is still the whole department. Try a different photo.",
};

/**
 * What to show for a failed submission. An upload refusal is worded from
 * its code. A photo send that failed some other way, without a reason the
 * backend named (busy, budget, limit), gets the general upload failure.
 * Anything else keeps the backend's message.
 */
export function noticeText(
  message: string,
  { code, hasReason, sentPhotos }: { code: UploadErrorCode | null; hasReason: boolean; sentPhotos: boolean },
): string {
  if (code) return UPLOAD_ERRORS[code];
  if (sentPhotos && !hasReason) return UPLOAD_ERRORS.upload_failed;
  return message;
}
