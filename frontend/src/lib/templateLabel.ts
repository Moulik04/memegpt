/**
 * A template's short label: the all-caps line its description opens with
 * ("SETTLED PREFERENCE: …"). The rest of the description is the matcher's
 * prompt, with routing notes meant for the model, so Make neither shows nor
 * searches it. A few templates have no label and show no line.
 */
export function templateLabel(description: string): string | null {
  const m = /^([A-Z0-9][^a-z:]*?):\s/.exec(description);
  return m ? m[1].trim() : null;
}
