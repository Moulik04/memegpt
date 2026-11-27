import type { UploadErrorCode } from "@/types";

/** Client-side limits, checked as photos are picked. The backend enforces
 * the real ones (config.py); these only save a wasted upload. */
export const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
export const MAX_IMAGES_PER_MESSAGE = 6;

/** Notices from the copy deck. Wording lives here, not in the backend. */
export const PICK_TOO_LARGE = "That image is over 10MB. Try a smaller one.";
export const PICK_TOO_MANY = "Up to 6 photos per message. Remove some before adding more.";
export const PICK_UNSUPPORTED = "That file isn't a supported image format. Try a JPEG, PNG, or WEBP.";
export const PICK_UNREADABLE = "That file couldn't be read as an image. It may be corrupted.";
/** The notice for a pick the format check turned away. */
export const PICK_FORMAT_NOTICE = { unsupported: PICK_UNSUPPORTED, unreadable: PICK_UNREADABLE } as const;

const UPLOAD_ERRORS: Record<UploadErrorCode, string> = {
  image_refused: "MemeGPT can't use this image. Try describing it in words instead.",
  file_too_large: PICK_TOO_LARGE,
  unrecognized_file_type: PICK_UNSUPPORTED,
  dimensions_too_large: "That image's dimensions are too large to process. Try a smaller one.",
  invalid_image: PICK_UNREADABLE,
  upload_failed: "Upload failed. The one engineer is still the whole department. Try a different photo.",
};

export interface Notice {
  heading?: string;
  text: string;
}

/** The deck's general error, for a failure the backend didn't name. */
export const GENERAL_FAILURE: Notice = { heading: "Something broke.", text: "Not you. Us. Try again in a moment." };

/**
 * What to show for a failed submission. An upload refusal is worded from
 * its code. A notice the backend named (busy, budget, limit) keeps its
 * message, which is the deck's wording. Anything else never shows the
 * backend's text, which can be a raw exception: a photo send gets the
 * general upload failure, a text send the general error.
 */
export function noticeFor(
  message: string,
  { code, hasReason, sentPhotos }: { code: UploadErrorCode | null; hasReason: boolean; sentPhotos: boolean },
): Notice {
  if (code) return { text: UPLOAD_ERRORS[code] };
  if (hasReason) return { text: message };
  if (sentPhotos) return { text: UPLOAD_ERRORS.upload_failed };
  return GENERAL_FAILURE;
}
