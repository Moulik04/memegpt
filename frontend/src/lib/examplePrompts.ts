// A large pool of example prompts shown as clickable chips on Chat's empty
// state. A random subset is drawn fresh on every page load (see
// ChatWindow.tsx) instead of always showing the same fixed few — see
// pickRandomPrompts() below.
export const EXAMPLE_PROMPTS_POOL: string[] = [
  // Work / tech life
  "waiting for my PR to get reviewed for 3 days",
  "when the deploy finally works on first try",
  "my manager asking who broke production",
  "fixing one bug and creating three more",
  "the meeting that could've been an email",
  "me explaining to QA why it's not a bug, it's a feature",
  "when the client changes requirements the day before launch",
  "staring at a stack trace at 2am",
  "when someone says 'quick call' and it's 90 minutes",
  "my code works and I have no idea why",
  "when the intern's PR is cleaner than mine",
  "explaining to my non-tech friends what I do for a living",
  "when the CI pipeline fails on the one thing you didn't touch",
  "me during my own code review a week later",
  "when Slack says 'is now a good time to talk'",
  "onboarding onto a codebase with zero documentation",
  "when the estimate was 2 days and it's been 2 weeks",
  "finding out the bug was a missing semicolon",
  "when someone reopens a ticket you closed 6 months ago",
  "my resume vs my actual daily tasks",
  "when the demo works perfectly until the client watches",
  "asking for a raise vs actually getting one",
  "when you push straight to main by accident",
  "the interview question I definitely didn't prepare for",
  "when the wifi goes out during a live presentation",
  "me pretending to understand the architecture diagram",
  "when someone asks if I tested it locally",
  "finding a Stack Overflow answer from myself, from 3 years ago",
  "when the standup goes 45 minutes over",
  "watching my own code run in production for the first time",

  // Everyday / mood
  "my plan was going great then suddenly it wasn't",
  "me vs my alarm clock at 7am",
  "my friend after 4 drinks claiming he's sober",
  "when you finally understand a joke 10 minutes later",
  "trying to fall asleep vs my brain at 3am",
  "when someone says 'we need to talk'",
  "me pretending I have my life together",
  "when the waiter asks if everything's okay and it's not",
  "checking my bank account after a night out",
  "when autocorrect ruins the entire message",
  "my face when the WiFi password doesn't work",
  "when you open the fridge for the fifth time hoping something changed",
  "me trying to act normal after tripping in public",
  "when the group chat goes silent after your joke",
  "waking up before the alarm and immediately regretting it",
  "when someone chews loudly next to you",
  "trying to remember why I walked into this room",
  "when you finally find the TV remote in the fridge",
  "me negotiating with myself about one more episode",
  "when your phone battery hits 1% mid-conversation",
  "when you say 'you too' after the waiter says enjoy your meal",
  "reading the same sentence five times and still not absorbing it",
  "when the elevator doors close right as you get there",
  "trying to parallel park while people watch",
  "when you catch yourself talking to the TV",
  "the specific chaos of losing your phone while calling it",
  "when someone says 'don't be mad but'",
  "me convincing myself 5 more minutes of scrolling won't hurt",
  "when you laugh at your own joke before finishing it",
  "the silence after you send a risky text",

  // Relationships / social
  "when your ex likes your old photo",
  "explaining to my mom why I'm still single",
  "when someone says 'we should hang out sometime' and never follows up",
  "reading a text 15 times before replying",
  "when your friend cancels plans 20 minutes before",
  "double texting and immediately regretting it",
  "when the group project has one person doing all the work",
  "me trying to introduce two friend groups",
  "when someone remembers something embarrassing you said years ago",
  "when your crush likes your Instagram story",
  "explaining an inside joke to someone who wasn't there",
  "when you and a stranger reach for the same item",
  "trying to end a phone call politely",
  "when someone asks 'so what do you do' at a party",
  "when the whole squad agrees on where to eat immediately",
  "when you're the only single one at the dinner table",
  "meeting your partner's parents for the first time",
  "when someone leaves you on read for 3 days",
  "explaining why I unfollowed someone",
  "when your friend's 'five minutes away' means 45",

  // Gaming / internet culture
  "when you finally beat the boss after 20 tries",
  "losing the game because of one teammate",
  "when the wifi lags right before the clutch play",
  "explaining why I need one more attempt at the game",
  "when you accidentally reply-all to the whole server",
  "finding the perfect meme for the group chat",
  "when your character dies right before the checkpoint",
  "rage quitting and coming right back",
  "when the update breaks everything you liked about the game",
  "me refreshing the page waiting for restock",
  "when your internet buffers at the worst possible moment",
  "explaining my screen time report to myself",
  "when the algorithm knows me better than my friends do",
  "opening 15 tabs and closing none of them",
  "when the show ends on a cliffhanger and no season 2",

  // Fitness / health
  "day 1 of the gym vs day 2",
  "me telling myself I'll start eating healthy tomorrow",
  "when leg day catches up with you two days later",
  "trying to convince myself the salad was worth it",
  "when the scale says something I don't agree with",
  "me buying gym clothes instead of actually going",
  "when you finally get 8 hours of sleep",
  "explaining why I skipped the gym again",
  "when someone asks how the diet is going",
  "the gap between my New Year's resolution and March",
  "when you finally do one pushup and feel unstoppable",
  "trying to drink more water and forgetting by noon",

  // Food
  "when the food takes longer than the delivery estimate",
  "me making dinner reservations I already regret",
  "when someone touches my food without asking",
  "the last slice of pizza and everyone's too polite to take it",
  "when the recipe says 'season to taste' and I have no idea",
  "explaining why I ordered dessert first",
  "when you're full but the food is still good",
  "reheated leftovers vs the same meal fresh",
  "when the coffee machine breaks on a Monday",
  "me convincing myself cereal counts as dinner",

  // Money / adulting
  "checking my savings account and immediately regretting it",
  "when rent is due and payday isn't",
  "explaining my budget spreadsheet to myself",
  "when a 'quick grocery run' costs way more than planned",
  "me signing up for a gym membership I'll use twice",
  "when the subscription renews and you forgot you had it",
  "trying to adult for one whole day",
  "when tax season sneaks up on you again",
  "me pretending to understand my payslip",
  "when the 'limited time offer' is still there a month later",

  // Weather / seasons
  "when it's freezing outside but the heater's broken",
  "me refusing to accept summer is over",
  "when the forecast says sunny and it immediately rains",
  "trying to function during daylight savings",
  "when winter arrives before you've bought a jacket",
  "the first hot day of the year vs my motivation",

  // Pets
  "my dog destroyed the couch again",
  "when the cat knocks something off the table on purpose",
  "trying to take a nice photo of my pet",
  "when my dog hears the treat bag from another room",
  "explaining to my pet why they can't come to work with me",
  "when the cat sits directly on my keyboard mid-task",

  // School / college
  "starting the essay the night before it's due",
  "when the professor says 'this won't be on the exam'",
  "group projects where one person disappears",
  "when finals week and my sleep schedule collide",
  "explaining my GPA to my parents",
  "when the exam has a question from week one you forgot existed",
  "the feeling of submitting an assignment 2 minutes before the deadline",

  // Travel
  "when the flight gets delayed for the third time",
  "packing for a trip and using half of it",
  "when airport security finds the water bottle I forgot about",
  "trying to nap on a plane and failing",
  "when the hotel room doesn't match the photos",
  "me pretending to know a foreign language while traveling",

  // Motivation / procrastination
  "saying I'll start Monday for the fifth Monday in a row",
  "when the to-do list gets longer instead of shorter",
  "cleaning my whole room to avoid one task",
  "when motivation shows up right as it's time for bed",
  "the gap between my plans for the weekend and what I actually did",
  "opening a new tab to 'research' and ending up somewhere unrelated",
  "when you finally start the task with 10 minutes left",

  // Random relatable chaos
  "when the printer jams right when you're already late",
  "explaining to IT that I definitely did restart it",
  "when autocomplete finishes your sentence wrong in a meeting",
  "the exact moment you realize you replied to the wrong chat",
  "when your phone autoplays a video at full volume in public",
  "trying to open a jar that clearly hates me",
  "when you finally organize your desktop and immediately mess it up again",
  "the audacity of Monday showing up every single week",
];

function shuffle<T>(arr: T[]): T[] {
  const copy = [...arr];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

/** Draws `count` distinct prompts at random from the pool. */
export function pickRandomPrompts(count = 6): string[] {
  return shuffle(EXAMPLE_PROMPTS_POOL).slice(0, count);
}
