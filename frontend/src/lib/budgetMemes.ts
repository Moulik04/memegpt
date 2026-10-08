// The pre-made memes shown with the "daily AI budget used up" notice. They
// are static files (public/budget-memes), rendered once by the backend's
// compositor and checked in, so showing one costs no model call. They are
// not the visitor's memes: nothing saves them, counts them in Arc, or takes
// them out of a daily allowance, and they get no share or rating controls.
//
// The notice text is always shown with the image and is its alt text too,
// so the information never lives only inside a picture.

const BUDGET_MEMES = [
  "pawn_stars_best_i_can_do",
  "this_is_where_i_d_put_my_trophy_if_i_had_one",
  "waiting_skeleton",
  "y_all_got_any_more_of_that",
  "drake",
  "one_does_not_simply",
  "well_yes_but_actually_no",
  "anakin_padme",
  "dhoni_calm",
  "this_is_fine",
] as const;

const STORAGE_KEY = "memegpt_last_budget_meme";

// Used when the browser refuses storage (a private window, blocked site
// data): the no-repeat rule then holds for the life of the page.
let lastShownThisPage: string | null = null;

function readLast(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? lastShownThisPage;
  } catch {
    return lastShownThisPage;
  }
}

function rememberLast(name: string): void {
  lastShownThisPage = name;
  try {
    window.localStorage.setItem(STORAGE_KEY, name);
  } catch {
    // The page-level copy above still holds.
  }
}

/** A random budget meme's URL, never the one this browser was shown last. */
export function pickBudgetMeme(): string {
  const last = readLast();
  const choices = BUDGET_MEMES.filter((name) => name !== last);
  const name = choices[Math.floor(Math.random() * choices.length)];
  rememberLast(name);
  return `/budget-memes/${name}.jpg`;
}
