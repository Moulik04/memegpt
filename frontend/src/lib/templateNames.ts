/**
 * Display names for the templates whose ids don't title-case into real
 * words ("i_m_the_captain_now" would read "I M The Captain Now"). Display
 * only: the catalog's own names, and the embedding text built from them,
 * stay as they are until they are fixed at the source.
 */
const DISPLAY_NAMES: Record<string, string> = {
  i_m_the_captain_now: "I'm The Captain Now",
  this_is_where_i_d_put_my_trophy_if_i_had_one: "This Is Where I'd Put My Trophy If I Had One",
  whe_i_m_in_a_competition_and_my_opponent_is: "When I'm In A Competition And My Opponent Is",
  x_x_everywhere: "X, X Everywhere",
};

/** The id title-cased, the way the backend builds a catalog name. */
function titleFromId(id: string): string {
  return id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** A template's display name from its id: "always_has_been" gives "Always Has Been". */
export function templateNameFromId(id: string): string {
  return DISPLAY_NAMES[id] ?? titleFromId(id);
}

/** The backend's name for a template, corrected when the id is one of the above. */
export function templateDisplayName(id: string, name: string): string {
  return DISPLAY_NAMES[id] ?? name;
}

const BY_CATALOG_NAME = new Map(Object.entries(DISPLAY_NAMES).map(([id, shown]) => [titleFromId(id), shown]));

/** For a page that gets only the backend's name (the share page), not the id. */
export function correctTemplateName(name: string): string {
  return BY_CATALOG_NAME.get(name) ?? name;
}
