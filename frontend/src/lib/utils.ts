import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"
import { templateNameFromId } from "./templateNames"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Template ids are snake_case slugs ("always_has_been"). This turns one into
// its display name ("Always Has Been"), corrected for the few ids that don't
// title-case into real words (lib/templateNames.ts).
export function templateLabel(id: string): string {
  return templateNameFromId(id);
}
