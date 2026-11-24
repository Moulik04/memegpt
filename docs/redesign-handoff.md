# MemeGPT Round 3: implementation handoff

**Chosen direction:** Front Page  
**Status:** Round 2 complete. This is the implementation spec for the selected direction, with all accepted carry-forward notes folded in. It contains no React code.

**Review pass, November 17, 2026:** checked against the live code and corrected where the two disagreed: Lore's source-line data, the full token layer, theme and status-bar colors, Chat's photo limit, Make's notices, missing copy, and the tabloid red. Mockup stand-ins and sample data are marked as such; the product shows real MemeGPT renders.

**Keeping today's site:** the redesign has to be easy to abandon. Today's main is tagged pre-redesign, and all visible work happens on a redesign branch that is merged only at launch. Backend changes the redesign needs go to main first, and today's frontend must not notice them: new response fields are optional additions it ignores, the new Arc card is a second style used only when the request asks for it, and thinking-stage wording changes in the frontend, not the backend. The redesign needs no database changes. The watermark fix is a bug fix that ships on its own and stays either way. Dropping the redesign after launch means reverting its merge into main, not resetting main to pre-redesign: backend fixes like the watermark one land on main after the tag, and a reset would throw them away.

## 1. Art direction

MemeGPT should feel like a tabloid front page built around a real meme desk: a compact masthead, black editorial type, tabloid red rules, and the meme as the lead photograph. The reference is newspaper hierarchy and information design, not fake newsprint. Keep the interface white, black, and red; use no paper texture, gradients, glows, decorative illustration, or generic SaaS cards.

Three references guide the direction:

- **New York Post front pages:** take the direct masthead-to-headline hierarchy and decisive red rule. Do not imitate its logo or headline wording.
- **Daily Mirror back-page sports coverage:** take the clear scoreboard staging for Arc. Use solid red content bars only inside Arc.
- **Newspaper classifieds:** take the single-listing rhythm for Make. Each template is one searchable listing with its full thumbnail and concise details.

The meme is the loudest object on every app screen. Meme captions remain uppercase Anton, white with a heavy black stroke. All meme images keep their natural aspect ratio, receive the same light gray mat and hairline edge, and retain the bottom-right watermark. The user's words are small Archivo display text above the image. Action rows are quiet, unboxed text with small icons and accessible tap areas.

### Brand and surface rules

- Product wordmark: **MemeGPT**, mixed case. Use Anton. Lowercase **memegpt** is reserved for the meme watermark and the Arc-card URL.
- Page ground: white. Body and headline text: near black. Quiet text: accessible gray. Accent: tabloid red.
- Red is for rules, underlines, and type across the product. Solid red blocks are reserved for Arc content. Shared navigation always marks the active tab with a red underline.
- Use square or slightly softened rectangular controls. Do not make every control a pill or card.
- No invented trust or press marks, testimonials, user counts, reviews, or marketing ratings. Thumbs feedback remains a product feature. Use Google's provider mark only inside Google's official sign-in button.
- One column on narrow screens. At wide sizes, use editorial columns that keep source text beside its meme.
- Meme output is immutable product media: never crop, stretch, rewrap, or recompose it inside the interface.

### Reusable stand-in memes

These four stand-ins exist only in the round 2 mockups. None of them is a template in the catalog, so the product never shows them. Where a screen in this spec shows one, the build uses a real MemeGPT render of the same shape: a wide meme on white, a wide photo, a tall photo, a tall drawing.

1. **Empty Meeting Room:** wide line drawing on plain white; chairs are not red.
2. **Gate Change:** wide airport photo with no readable gate number. Keep the R2-1B scene.
3. **Last-Minute Draft:** tall 2:3 photo of a student at a desk. Keep this version everywhere.
4. **Low Battery:** tall 2:3 drawing on plain white, with no interface red.

Every one gets the same #E7E8EA mat and hairline edge. Preserve each image's actual dimensions. The product's output range is about 2:1 wide through 2:3 tall; the client uses the source dimensions rather than guessing from image content.

Fixed system-response memes are existing product assets; keep them. The 404 meme is the live **IS THIS A PAGE?** render (frontend/public/landing/404_example.png). The error meme is the live **THE SERVER, RIGHT NOW** render on a burning room (500_example.png), which already reads as broken rather than asleep. The budget-used-up meme is one of the ten live images in frontend/public/budget-memes, none of which borrows the user's prompt. Landing stories use the real prompt-to-meme pairs that already exist, and Lore examples are real Lore renders of the shared group chat. Once the compositor fix lands, re-render any of these that carry see-through watermark pixels.

## 2. Tokens

Map the existing token names below to the Front Page palette. The existing names are retained to keep the implementation handoff compatible with the current app token layer.

~~~css
:root {
  --ink-0: #FFFFFF; /* page canvas; replaces the current near-black canvas */
  --ink-1: #F7F7F7; /* quiet white surface for drawers and secondary regions */
  --ink-2: #E7E8EA; /* shared meme mat and restrained neutral surface */
  --line: #C9C9C9; /* decorative rules only; at 1.7:1 it is too light to outline a control */
  --paper: #111111; /* primary text and black buttons */
  --paper-dim: #555555; /* secondary text with accessible contrast on white */
  --accent-color: #CD1F35; /* tabloid red, as in every approved screen; 5.5:1 as red text on white and as white text on red, so AA both ways */
  --radius: 0.25rem; /* shared small corner radius; avoid pill-like controls */
  --font-display: "Anton", Impact, sans-serif; /* headline, wordmark, and meme-caption family */
  --font-sans: "Archivo", Arial, sans-serif; /* body, labels, controls, and user story titles */
  --font-mono: "Archivo", Arial, sans-serif; /* no monospace in this direction; existing font-mono uses fall back to Archivo */
  --text-display: clamp(3rem, 6.2vw, 6.5rem); /* main landing headline */

  --text-title: clamp(2rem, 3.6vw, 3.75rem); /* new: section and story headline scale */
  --text-heading: clamp(1.375rem, 2vw, 2rem); /* new: component heading scale */
  --text-body: 1rem; /* new: body and control base, never below 16px */
  --text-small: 0.875rem; /* new: secondary copy; reserve for nonessential details */
  --space-1: 0.25rem; /* new: 4px spacing step */
  --space-2: 0.5rem; /* new: 8px spacing step */
  --space-3: 0.75rem; /* new: 12px spacing step */
  --space-4: 1rem; /* new: 16px spacing step */
  --space-5: 1.5rem; /* new: 24px spacing step */
  --space-6: 2rem; /* new: 32px spacing step */
  --space-7: 3rem; /* new: 48px spacing step */
  --space-8: 4rem; /* new: 64px spacing step */
  --focus-ring: #111111; /* new: keyboard focus, drawn with a 2px offset so it shows around black buttons */
  --control-border: #111111; /* new: outline of text fields and outlined buttons, as in the mockups; needs 3:1 against white */
  --meme-mat: #E7E8EA; /* new: consistent mat behind every meme */
  --meme-edge: #BFC1C4; /* new: hairline around each image and mat */
  --shadow-overlay: 0 4px 16px rgb(0 0 0 / 12%); /* new: restrained shadow for popovers only */
  --ease-settle: cubic-bezier(0.16, 1, 0.3, 1); /* existing name, retained for short editorial moves */
  --duration-fast: 150ms; /* existing family name, for small state changes */
  --duration-settle: 240ms; /* existing family name, for drawers and swaps */
  --duration-arrive: 320ms; /* new: signature story move and route transitions */
}
~~~

### Token use

- Body, controls, text fields, and caption-box labels use Archivo at 16px or larger. User story titles use Archivo and stay visually subordinate to the meme caption.
- Anton is for the page headline, section headlines where emphasis is needed, wordmark, Arc display numbers, and rendered meme captions. Do not set every label in Anton.
- No monospace in this direction. Labels and metadata use Archivo.
- The red accent is #CD1F35. Use red on white for links, rules, and selected tabs. For filled Arc bars, use white text. Keep the red out of meme imagery.
- The --ink-2 token is a background surface, not body text. Use --paper-dim for secondary text.
- Draw text fields and outlined buttons with --control-border and at least 44px height. Keep field text 16px or larger to avoid iOS Safari zoom. --line is for decorative rules only.
- No shadows except the small overlay shadow on drawers and popovers. Prefer a visible rule to a card.

### The rest of the token layer

The map above covers the app's own tokens. The app also styles with shadcn's variables in globals.css and with raw Tailwind classes tuned for the dark theme: text-gray-100 to text-gray-600, text-white and hover:bg-white/5 appear in 18 of the 46 .tsx files, and bg-card or border-border in more. Flipping only the tokens above would leave light gray text on white in all of those places. So the build also:

- maps shadcn's variables to this palette: --background, --card and --popover to white; --foreground, --card-foreground and --popover-foreground to --paper; --muted and --accent (shadcn's hover surface, not the brand red) to --ink-1; --muted-foreground to --paper-dim; --border to --line; --input to --control-border; --ring to --focus-ring; --primary to --paper with a white --primary-foreground; --destructive to --accent-color, for text only;
- replaces every raw gray and white class with these tokens;
- restyles the twelve files that use bg-accent fills today, for main buttons, the active tab and the letter avatar. In this direction a main button is solid black (destructive ones too, like the Forget me button), the active tab is a red underline, and red fills nothing outside Arc.

The kept names now read backwards for a newspaper: the --ink-* tokens are light surfaces and --paper is the dark text. They stay for compatibility; rename them in a follow-up if that's cheaper than living with it.

## 3. Breakpoints and shared geometry

Use these as layout thresholds, not device detection:

| Range | Layout |
| --- | --- |
| 0–767px | Phone. One column, shared bottom tab bar, 16px minimum body/input text, 44px minimum interactive targets. |
| 768–1023px | Small tablet. One main column where editorial pairing would make captions too small; use two columns only when each remains readable. |
| 1024px and up | Desktop. Shared top tabs, editorial columns, and a centered content measure inside the full viewport. |

At 1440px, keep page content within a generous editorial measure, but do not center every task into a narrow chatbot column. Use 24–32px desktop gutters and 16px phone gutters. Reserve safe space for the phone bottom bar and device inset. The bottom bar must not cover a focused field, validation message, or final action.

All pages:

- At desktop, use one header row with the wordmark, top tabs where the app shell applies, and account actions.
- At phone width, the header contains the wordmark, Sign in or the signed-in avatar, and Forget me where the live service is available. Chat, Lore, Make, and Arc appear only in the bottom bar.
- Header account controls are at least 44px tall; if the phone width is tight, keep them as separate accessible targets rather than compressing them.
- The phone bottom bar has four equal destinations, each with a 44px or larger target. It is the only phone tab navigation.
- Landing has no active tab. Inside the app, exactly one tab is active. The active tab uses a red underline, never a solid red navigation tile.
- System routes outside the app use a wordmark-only header. The shared-meme page also uses the wordmark only.
- Focus order follows reading order. Sticky navigation and overlays must not hide focus.

## 4. Screen layouts

### 4.1 Landing page, root route

#### Desktop

The first 900px contains the masthead, headline, short subline, one lead story, story title and Next story control, and the prompt composer. The masthead is smaller than the headline. Keep the thin red rule below the masthead. Do not put a red underline through the headline.

Use a fixed-height lead slot. Fit the complete source meme inside it, centered and uncropped. The image keeps its natural ratio and gets only its own thin gray mat and hairline; unused slot area stays white. A tall 2:3 lead must not turn the entire slot gray or resemble a video player. The slot height must still leave the composer above the fold at 1440×900.

The lead story title is the original prompt in small Archivo. Keep Next story on the same title line. The headline and prompt never compete with the meme caption. A single lead is shown at a time.

Below the cover, continue as one scrolling page:

1. One editorial story for each mode: Chat, Lore, Make, Arc. Each has a real prompt or real task, a real MemeGPT render or feature view, and a concise link into that mode. Arc tells the stats story, not an essay-prompt story: show an Arc share card rendered from sample data with a real catalog template, labeled **Example**, since its numbers are nobody's real stats.
2. A compact **In brief** column for product facts, privacy, and the five FAQ entries.
3. End on the prompt field. Do not add numbered steps, a generic feature-card grid, a banner CTA, or a separate pricing section.

The Lore example uses the shared group chat below, collapsed with two or three exact messages and a more messages affordance. Show two or three real Lore renders of that chat from distinct moments, each beside the line or lines that produced it. Never reuse or invent transcript lines.

#### Phone

Draw at 390×844 with the full bottom bar. Header: wordmark, Sign in or account avatar, Forget me. The bottom bar has four links and no active state. The landing cover fits the prompt and lead slot above the fold. The fixed-height slot keeps the meme's natural aspect ratio and uses white around the thin mat. Next story remains beside the story title. Below the cover, the four mode stories, In brief, FAQ, and final prompt field form one continuous scroll.

The composer is stacked: full-width text field at 16px or larger, then Photo and the black main action on the next row. Field and buttons each have 44px minimum height. No desktop split hero.

The landing page has no composer today, so its behavior is new: **Make a meme** opens Chat and sends the text, plus any photo picked on the landing page, as the first message. With nothing typed or picked, it simply opens Chat.

#### Landing copy

- Headline: **The group chat has a front page.**
- Subline: **Say what happened, paste the group chat or add a screenshot. MemeGPT sends back the meme.**
- Story control: **Next story**
- Prompt field: **What happened?**
- Main action: **Make a meme**
- In Brief sign-in line: **Google sign-in saves Chat and Lore history across devices.**

### 4.2 Shared Chat shell and Chat route

#### Desktop front page

The composer sits at the top under the masthead, where the next lead story will appear. Below it, the newest reply is the lead: a small Archivo line with the user's words, the full meme in a fixed-height slot, and its quiet action row. Older replies sit in a narrower column beside the lead under an **Earlier** rule. Every earlier meme keeps its small Archivo message line above it. Do not center all replies in one narrow column.

The lead slot preserves the source aspect ratio, centers the full image, and mats only the image. A tall image stays tall and does not stretch to fill the column. History opens as an overlay drawer from a History button in the header; it is not a separate Chat page.

#### Phone

The newest answer is the lead story. The small user line appears above it. Earlier replies sit below an Earlier rule at smaller size. Tapping an earlier meme opens it at full size with its message and actions. Use the common phone composer from the Chat component section and the shared bottom tab bar with Chat active.

#### States

- **Empty:** brief, deadpan empty-state line and distinct starter prompts. Do not use “How can I help you today?” or a 2×2 grid of suggestion chips.
- **Photo waiting:** text and the photo remain inside the composer until Send. Show a small attached thumbnail and a separate 44px Remove control. Keep other already attached photos if a new pick fails validation. No “use as meme / use for context” choice.
- **Thinking:** the sent user message stays above the response, with its sent photo thumbnail if one was attached. Show only completed stages in muted text and the current stage in black. Do not show stages that have not started, a percentage, or a progress bar. The backend's thinking events carry a stage field (looking, analyzing, rendering) along with their own message text ("Reading your vibe...", "Crafting the perfect ... meme..."), which hooks/useMemeStream.ts prints today. Key the new copy off the stage field in the frontend, and leave the backend strings alone, since today's site prints them.
- **Lead reply:** small Archivo user line, full meme, action row.
- **Earlier reply:** small Archivo user line, smaller full meme, action row available on open.
- **History drawer:** signed-in only, overlays the Chat. Includes New chat, a Delete action on every row, and **History saved across devices.**
- **New chat:** starts an empty conversation; history stays in the drawer.
- **Delete chat:** row-level confirmation before removing the saved chat and related meme records.
- **Signed out:** no saved text or Chat history. Meme records persist as described in Privacy.

#### Phone composer

Stack the full-width text field above the Photo and Send row. All three controls have a minimum 44px target. Text is 16px minimum. Chat accepts up to six photos per message, as the live app does. With no photo, placeholder is **What happened?** With a photo attached, it becomes **Add a caption (optional)**. Waiting thumbnails remain inside the composer and each has its own 44px Remove control. A pick that would go past six is rejected whole with the count error. The main action is solid black Send. Photo is outlined. Sent photos are shown beside the sent message without Remove.

### 4.3 Lore route

Lore is for long dumps. It turns a pasted chat or a stack of screenshots into a sequence of memes, one per moment, in chat order.

#### Input state

- One message per line with the speaker names exactly as in the shared transcript.
- Screenshot stand-ins show screenshots of this same group chat, with one message per line. Do not use a code editor, chart, or project checklist as a Lore screenshot.
- Show a long paste as a collapsed transcript preview with two or three exact lines and a more messages affordance. Expand to read the rest.
- Paste field and screenshot attachments share the input area. Each attached image has an independent 44px Remove target.
- Meme count control: Auto or 1, 2, 3, 4, 5.
- Remember lore switch is off by default, has no emoji, and is black when on.
- Under the Drop the lore black button, show the correct signed-out or signed-in retention copy.
- Photo button is outlined. Drop the lore is the solid black main action and has a 44px target.
- If a pick would go beyond six images, reject the whole pick, keep existing images, and show the count error under the composer.

#### Progress state

Show exactly four non-overlapping moments from the shared transcript in order. For the sample, flight and meeting are complete, essay is being captioned, battery is queued. While Lore works, the status reads **Found 4 moments worth memeing**; the rows already show which memes are done. As in the live app, the count is added only if Lore finishes short: **Found 4 moments worth memeing. 3 of 4 memes made**. The moment that failed keeps its row and source lines with **This one didn't come out.** Completed memes appear beside their source lines.

The active row identifies its selected template and has the only spinner. Waiting rows name the moment, not a predicted template, for example **Maya's 1% is up next**. No spinner on waiting rows. Each source line is credited beside the meme it produced:

1. Flight: Maya's “Flight delayed again. Third time.” and Leo's “That gate has your mail now.”
2. Meeting: June's “This meeting could've been an email.”, your “It has a follow-up meeting.”, and Leo's “Do we get an agenda?”
3. Essay: June's “I haven't started the essay.” and your “It's due tomorrow. Opening the doc at 11:58.”
4. Battery: Maya's “Phone's at 1%.”, Leo's “You sent that with one percent?”, and Maya's “I'm committed to the bit.”

#### Data this needs

The backend sends source lines now, but only to a request that asks for them. The redesign's Lore asks with `include_source_lines: true` in the /lore/ JSON body, and with the `include_source_lines` form field on /lore/image/. Without the flag, Lore's segmentation (backend/nlp/segmentation.py) returns only the short situation summaries the model writes, and the plan event carries those summaries, not lines. With it:

- Segmentation returns, for each moment, the numbers of the pasted lines it drew on. The backend keeps only numbers that point at real lines of the paste and drops the rest. It never sends quoted text the model wrote.
- The browser quotes those lines from the paste it already holds, so nothing new is stored.
- For screenshots, and for any moment without valid line numbers, show the moment's summary instead of quotes. Every finished meme already carries its summary (situationText in hooks/useMemeStream.ts).
- Saved history keeps storing summaries only, as the privacy page says, so a reopened Lore chat shows summaries, not quotes.
- Line numbers are opt-in: only a request that asks for them (the redesign's Lore) gets the numbered prompt, so today's Chat and Lore keep today's prompt exactly.
- Lines are numbered on the text as the backend received it, after the max_dump_chars cut (20,000 characters) and before any strip. The browser quotes from the same cut text.
- The browser numbers and quotes the exact string it sent, not what is in the textarea. LoreView already trims the paste before sending (frontend/src/components/LoreView.tsx, line 236), so blank lines at the start or end of the textarea never count.
- The cut counts code points, as Python slicing does, not UTF-16 units. In the browser that is `Array.from(sent).slice(0, 20000).join("")`, so an emoji near the limit lands on the same side of the cut in both places.
- Split the cut text on "\n" only. Line 1 is the first piece. Blank lines keep their number but are never cited, so numbers can skip. Leading spaces stay part of the line.
- The plan event carries `source_lines`: one entry per situation, in the same order as `situations`. Each entry is a sorted list of line numbers, or null. Null, or an empty list, means show the moment's summary instead of quotes.
- source_lines is sent even when Lore finds only one moment, although the plan event otherwise goes out only for more than one.
- A take reuses the lines of the moment it retakes (take_of names it), so its row keeps the quote.

#### Results state

Results is separate from progress. All four memes are finished. Wide memes use the full available width. Tall essay and battery memes pair side by side when that preserves their real ratio and readable captions. Never force equal boxes, crop, or reshape. On desktop, each moment block takes the meme's natural height: source lines form a pull quote beside the narrower image column. On phone, put each moment's lines above its full meme.

Every result has **Another take**, **Thumbs up**, **Thumbs down**, **Share**, and **Download**. Action controls remain quiet and unboxed with 44px hit areas.

### 4.4 Make route

Make has no AI judgment. Users browse and select a template, write the captions, then render.

#### Template library

Use a classifieds rhythm: one listing per template, searchable across name, vibe, and tag. Every listing has a full, uncropped template thumbnail fitted inside the row, even when the template itself is tall. Never crop the image to make all rows look alike. Search has a 16px minimum and 44px target. A selected listing is marked with a rule, not a large red fill.

#### Captioning

One screen for this state. Show the bare template image with numbered markers for every caption box. Caption boxes are numbered 1 through the template's real count, up to 5. Each input has a matching number. An empty field shows only its number; a field with text shows only its own caption. Never place the template name in a caption field. Provide **Change template** back to the library and the solid black **Render** action.

#### Finished

One screen for the rendered result. Show the complete meme at natural size inside its gray mat and hairline. Actions: **Make another**, **Share**, **Download**. No ratings. Do not show Render on an already finished meme. Make another sits beside Share and Download.

#### Other states

- No matches: plain text that says no templates matched and keeps the search field active.
- Caption refused: the backend checks the captions together and returns one message without saying which failed, so show **That caption couldn't be used. Try different text.** under the caption fields and keep everything typed. Pointing at one field would need the backend to check each caption separately.
- Rendering: show a short text status without a percentage or faux terminal.
- Render failure: plain retry guidance, preserve template and entered captions.
- Change template: returns to library without converting the selected template name into a caption.
- Limits: Make hits the same busy, daily budget, personal and network limit notices as Chat. The live Make already shows the budget notice with its ready-made meme.

### 4.5 Arc route

Arc is a Wrapped-style tap-through story staged as a tabloid sports back page. Solid red content blocks are allowed here. The shared navigation remains white/black with the active red underline.

#### Sample data for the handoff only

47 memes; 14 different templates; busiest hour 2 AM; 6-day streak; +12,480 Aura; tier certified menace; most-used template Empty Meeting Room, 9 times; split 26 Chat / 15 Lore / 6 Make. These are mockup values only, never marketing claims. Do not invent the season date range; derive it from actual records; when they don't fit one season, the label is **YOUR ARC**, still with the record dates. Every roast, the verdict, the tier and the period label come from backend/arc/copy.py; the strings in this section are what it returns for the sample. Empty Meeting Room is a mockup stand-in, so its roast is sample-only; real templates get the roast arc/copy.py assigns them. **14 different templates** needs the Arc API to send distinct_templates, which the backend already counts for the aura score but doesn't return.

#### Story frames

Every phone frame contains all five progress segments and the bottom navigation as the way out. On desktop retain the app navigation and include a clear Close control. Frame label is the frame number plus name, with no repeated heading.

| Frame | Display and supporting copy |
| --- | --- |
| 01 Volume | If dates from the actual records fit in one season, headline **AUTUMN ARC** with the derived date range, as in **AUTUMN ARC • SEP 3–NOV 17, 2026**. Otherwise **YOUR ARC** with the same record dates, as in **YOUR ARC • JUN 2–NOV 17, 2026**. Count **47**. Roast: **memes generated this arc. no thoughts, just memes.** |
| 02 Signature | Template name **Empty Meeting Room**, count **9 times**. Roast: **your most-summoned template. (still waiting on the agenda)**. Show the template image at its true ratio (in the sample, the wide line drawing). |
| 03 Witching hour | **2 AM**. Roast: **we're not asking questions.** Do not repeat the headline as a label. |
| 04 The split | Scoreboard values **26 / 15 / 6**, labels Chat / Lore / Make, all three bars the same width so the labels remain readable. Roast: **chat / lore / make. yappacino.** |
| 05 Streak | **6 days**. Roast: **consecutive days. still an arc.** |

#### Finale

- Main score: **+12,480 AURA FARMED**
- Tier: **certified menace**
- The six-tier table is ordered top to bottom: aura farming god, baby aura farmer, certified menace, main character (unwell), side character energy, npc arc.
- Thresholds: 20,000; 17,501; 10,000; 5,000; 2,000; 0, respectively.
- Mark certified menace as the current tier and show **5,021 to baby aura farmer**.
- Verdict in large, bold type: **we've seen growth. we're a little scared.**
- Main action: **Share your Arc**

#### Share card

Render a 1080×1350 card image on the server. Do not share a screenshot of the interactive finale. Do not put a captioned meme or group-chat text on the card. Top to bottom, the left column holds:

- the **MemeGPT Arc** masthead with a red rule under it
- the season line in uppercase with the record span: **AUTUMN ARC • SEP 3–NOV 17, 2026** when the records fit one season, otherwise **YOUR ARC • JUN 2–NOV 17, 2026**, with the label chosen by arc/copy.py exactly as frame 01 does. Dates use an en dash and the year. A span across years reads **DEC 20, 2026–FEB 10, 2027**, and a single day reads **NOV 17, 2026**. Without any dates the line is just **YOUR ARC**.
- **+12,480** and **AURA FARMED** in white inside one solid red block, as on the approved R2-10 card
- the tier (**certified menace**) in white on a solid #111 block
- the verdict in large bold type
- **47 memes • 14 different templates**

The bare signature template sits on the meme mat with its hairline, labelled directly under the mat with **Empty Meeting Room • 9 times**. It is laid out one of two ways. Below the text, as wide templates are, using the full content width. Or in a right-hand column whose top lines up with the top of the red score block, whose left edge sits 48px past the left column's widest element (the red score block, the tier block or the counts line, and at least 520px), and whose bottom is the same limit as below. The column is used only when it shows the template at least 1.5× bigger by area. In the column layout the verdict wraps to the left column's width, and the label wraps to the mat's width without ever splitting **• 9 times** across lines. A very tall template like American Chopper takes the column. A GIF's first frame and wide templates stay below.

Reserve the bottom-right 75px for the backend watermark. The footer **memegpt.app/arc** and its red footer bar must end before that clear corner. The card is drawn in Python by compose_arc_card in backend/image_processing/compositor.py, which still uses today's glow style, so the new design is backend work: add it as a second style next to today's card, used only when the request asks for it, so today's site keeps getting today's card. It needs Archivo on the server too: commit the Archivo font file and its OFL license to backend/fonts. The card has no fallback font, so a missing Archivo fails loudly rather than shipping a card in the wrong face.

#### Empty state

Until five meme records exist, show no story segments. Show **Your arc hasn't started yet.** in Anton, then **Go be unwell somewhere. Five memes minimum before MemeGPT has anything to judge you for.**, then the count as a small line, **2 of 5 memes so far.** in the sample, then **Start in Chat**. Do not invent extra stats.

### 4.6 Shared meme page

Wordmark-only header. Show the saved meme at its natural size with mat, edge, caption, and watermark. Under it, use the live line **Made with MemeGPT. It only replies in memes.** Then **Make your own**. No app tabs, Sign in, or Forget me. A deleted meme's shared URL resolves to the designed 404 page.

Each shared meme uses its own image for link preview metadata. It does not use the site-wide link-preview card.

### 4.7 Sign-in and account

#### Sign-in popover

Triggered from the header Sign in. Use a small rectangular panel, not a full-page sign-in flow. Copy: **Every part works without an account. Signing in only adds saved chat history across devices.** One rectangular Google button in Google's black or outlined style, labeled **Continue with Google**. No email option; the email flow was removed because the configured mailer did not reach real users.

Landing In brief uses **Google sign-in saves Chat and Lore history across devices.**

#### Signed-in account menu

Letter avatar opens a menu containing the signed-in email, History, and Sign out. No Sign in entry and no Forget me entry.

#### Forget me link and confirmation

Forget me is a header link for signed-in and signed-out visitors. The confirmation names the data erased, confirms share links stop working, says Arc starts over, and states **This can't be undone.**

Signed out copy:

**This erases your memes, ratings and remembered lore from this browser.** Share links to those memes stop working. Your Arc starts over. This can't be undone. Chats saved to an account are only erased while you're signed in to it.

Signed in copy:

**This erases your chats, memes, ratings and remembered lore.** Share links to those memes stop working. Your Arc starts over. This can't be undone. Your account itself stays. To delete it, email support.memegpt@gmail.com.

Failure remains inside the dialog:

- **MemeGPT couldn't finish erasing your data. Please try again.** Actions: Try again, Cancel.
- If the UI still shows a signed-in M avatar but the server cannot confirm the session: **MemeGPT couldn't confirm your sign-in, so nothing was erased. Sign in again and retry.** Actions: Sign in, Cancel.

Do not say that data is still present after a partial erase. Images can have been deleted before the remaining records fail.

### 4.8 404, error, maintenance

All use a wordmark-only header. No app tabs or account controls.

#### 404

- Headline: **404: not a page.**
- Body: **Whatever you were looking for isn't here. The chatbot is, though.**
- Show the live **IS THIS A PAGE?** meme (frontend/public/landing/404_example.png).
- One black button: **Open MemeGPT**
- No Back to Chat.

#### Error

- Headline: **Something broke.**
- Body: **Not you. Us. Try again in a moment.**
- Show the live **THE SERVER, RIGHT NOW** meme (500_example.png), a burning room: broken, not asleep, so it doesn't repeat the maintenance page's nap joke.
- Black button **Try again**, plain link **Back home**.

#### Maintenance

The maintenance page is served for every address, including app routes and the API. No buttons or links. Show one of the six established headline/body pairs per visit, selected randomly and stable for that page visit. Do not rotate it on a timer.

Pair 1, the primary example:

- **brb, MemeGPT is touching grass**
- **We're off rebuilding something even more unhinged. The servers needed a nap. Back soon.**

Keep the other five existing live pairs unchanged in the copy deck below. Under **From the archives**, show three or four still memes in a Front Page grid. No tilted cards, glow, animated lanes, or other motion.

### 4.9 Privacy page

One column at phone and desktop width. Preserve all live privacy wording below. The visual redesign changes type, spacing, navigation, and section links only.

- Wordmark-only header.
- Title **Privacy**.
- Intro and date as in the copy deck.
- Twelve vertical section links, each with a minimum 44px target.
- Sections render in the same order, one column.
- In **Who else touches this**, keep an opening sentence, a distinct list item for each company, and the closing sentence. Keep the warning to readers as a pull quote inside Gemini's item.
- Footer includes the existing live footer plus the support email.
- The implementation can visually break this long page across phone captures; it remains one continuous page.

## 5. Component and state inventory

This section is the build checklist. Every listed state must be designed and reachable by keyboard.

| Component | Required states and behavior |
| --- | --- |
| Site masthead | Landing/app/system variants; desktop tabs; phone wordmark and account controls; red rule; no active tab on landing; wordmark-only for shared meme and system pages. |
| App navigation | Desktop top tabs; phone bottom bar; Chat/Lore/Make/Arc; 44px minimum targets; active red underline only; accessible current-page state. |
| Wordmark | Mixed-case MemeGPT, Anton; phone display size 24px; no lowercasing except watermark. |
| Sign-in popover | Closed, open, submitting, provider failure, success; Google only; close with Escape and outside click; focus returns to trigger. |
| Account menu | Closed/open; letter avatar; signed-in email, History, Sign out; no Sign in or Forget me. |
| Forget me dialog | Signed-out confirmation; signed-in confirmation; busy; erase failure; sign-in confirmation failure; retry/cancel; focus trap and return. |
| Prompt composer | Empty, focused, typed, attached photo(s), attachment removal, immediate size/count validation, sending, disabled while sending, post-send result. Stacked phone layout and 16px text. |
| Meme frame | Natural source ratio; gray mat and hairline; captions; solid watermark; loading; broken image fallback; full-size open; no crop or stretch. |
| Meme actions | Quiet unboxed thumbs-up/down, Share, Download; hover/focus/pressed; selected rating; share success/failure; download state. Each action has an accessible label and 44px target. |
| Chat lead story | Empty, user request, sent photo, thinking stages, finished meme, daily budget fallback, limit response, safety refusal, general failure. |
| Earlier story | Message line, natural-size image, quiet actions, open-full-size interaction. |
| Thinking stages | Photo path: Looking at the photo, Reading the message, Captioning [template]. Text-only path: Reading the message, Captioning [template]. Completed stages muted, current black, future stages hidden. |
| History drawer | Closed/open; list; New chat; Delete on every row; row confirmation; empty history; History saved across devices; signed-out access directs to Google sign-in. |
| Lore transcript | Empty, pasted, collapsed two/three-message preview, expanded full text, multiple screenshots, six-photo maximum, per-image Remove, paste validation. |
| Lore count | Auto or 1–5 selected; accessible radio/select behavior. |
| Remember lore | Off/on; off by default; black switch when on; help copy; no emoji. |
| Lore progress | Found-moments status; completed, active, queued; only active has spinner and template; queued rows name moment; finished meme actions; finished-short status and failed-moment row. |
| Lore results | Four complete items; source lines from validated line numbers, or the moment summary for screenshots; Another take; selected rating; Share; Download; full natural ratios; phone and desktop pairing rules. |
| Template search | Idle, focused, typed, matching listings, no matches, clear query. Search name/vibe/tag. |
| Template listing | Full fitted thumbnail, name/tags, hover/focus, selected. One listing per row; no red card fill. |
| Caption editor | Bare template image with numbered markers; up to five matching fields; empty/text/error; Change template; Render disabled/enabled; render in progress/error. |
| Rendered meme | Finished meme; Make another; Share; Download; no rating and no Render button. |
| Arc story | Empty, frames 01–05, finale, share card; progress segments; next/back; Close or bottom navigation; readable focus state. |
| Arc score table | Six tiers, current-tier marker, thresholds, distance to next tier; no fabricated rank or odds language. |
| Arc share card | Rendered 1080×1350 output, MemeGPT Arc masthead, season line, tier, score, verdict, bare template drawing, source-safe footer area, watermark. |
| Shared meme page | Existing shared image, no account nav; removed/missing image routes to 404. |
| Privacy | Twelve section links, current section anchor, long one-column content, vendor list and Gemini pull quote, support footer. |
| Error notices | Busy, daily budget, personal limit, network limit, upload size, upload count, wrong type, pixel dimensions, unreadable image, safety refusal, generic upload failure, caption refused, delete-chat failure. Limit notices apply in Chat, Lore and Make; upload notices in Chat and Lore. Each notice is announced accessibly without stealing focus. |
| System pages | 404, error, maintenance; distinct copy/art; only permitted action links/buttons. |

## 6. Motion and transitions

Motion is used to explain state changes, not to decorate the page. Never use a typewriter, decrypting text, shimmering button, progress percentage, cursor spotlight, glowing orbs, or perpetual ambient movement. Motion must be disabled or reduced when prefers-reduced-motion is set to reduce.

| Trigger | What moves | Duration and easing | Reduced-motion version |
| --- | --- | --- | --- |
| A new Chat answer becomes the lead story | The old lead moves into the Earlier column/list while the new user line and meme take the lead slot. Preserve image dimensions and avoid overlap. This is the signature moment. | 320ms, --ease-settle; use FLIP-style geometry transition. | No translation or scaling. Old lead immediately takes its Earlier position; new lead appears in place. |
| User activates a different app tab | Outgoing and incoming route content crossfade through View Transitions; a small horizontal position change may orient direction. Navigation stays fixed. | 240ms, --ease-settle. | Instant route swap with no transform; keep focus and scroll-position rules. |
| History or account menu opens | Drawer/popover moves from its owning edge and fades in; background dim is restrained. | 240ms, --ease-settle. | Show immediately; no movement. |
| Dialog opens | Dialog fades in; page dim appears. No scale bounce. | 150ms, ease-out. | Show immediately. |
| Photo is attached or removed before Send | Thumbnail enters/leaves the composer with a short opacity and size change; text field remains stable. | 150ms, --ease-settle. | Immediate insert/remove. |
| Chat advances through a real thinking stage | Status line changes to the newly active stage; the finished line becomes muted. No bar or percentage. | 150ms, ease-out. | Immediate text change. |
| Lore discovers and completes a moment | The moment row receives its meme in place. Only the active row uses the spinner. Do not rearrange source order. | 240ms, --ease-settle. | Replace the status and image in place with no motion. |
| Another take completes | The current image is replaced in the same frame after the new image is ready. Avoid a blank placeholder or image morph. | 240ms crossfade, --ease-settle. | Swap immediately. |
| Arc advances or goes back one frame | Story content changes while the five segment indicators update. Do not animate the indicators as a timer. | 240ms, --ease-settle; move in the direction of navigation. | Immediate frame change, segments update at once. |
| User expands a collapsed Lore transcript or FAQ answer | Text block opens to its natural height; other content follows normally. | 150ms, ease-out. | Immediate expansion/collapse. |
| User focuses or hovers a control | Only underline, border, or text color changes. | 150ms, ease-out. | State change remains; no transition needed. |

The maintenance page, static archives, meme images, and watermark do not animate. Never animate the watermark or caption. Keep animation out of the share-card render.

Two more reduced-motion rules: the Lore spinner becomes a static marker, and animated GIF memes show their first frame with a Play control.

## 7. Full copy deck

Text below is the source for UI copy. Interface copy uses no em dash. Keep the user's deadpan voice, and do not invent alternative claims.

### 7.1 Product and landing

- Site title: **MemeGPT: a chatbot that only replies in memes**
- One description used for site metadata and manifest: **A chatbot that only replies in memes.**
- Landing headline: **The group chat has a front page.**
- Landing subline: **Say what happened, paste the group chat or add a screenshot. MemeGPT sends back the meme.**
- Landing In brief sign-in: **Google sign-in saves Chat and Lore history across devices.**
- Prompt field: **What happened?**
- Prompt field with photo: **Add a caption (optional)**
- Main action: **Make a meme**
- Story action: **Next story**
- Product facts:
  - **120+ meme templates, including a few animated GIFs.**
  - **Every part works without an account.**
  - **Google sign-in saves Chat and Lore history across devices.**
  - **Original photos are never kept.**
  - **Signed out, your text isn't kept either. Only the memes MemeGPT makes are.**
  - **Forget me erases your anonymous identity, history and memes.**
  - **Thumbs up or down teaches MemeGPT your sense of humor.**
  - **Works on phones and installs like an app.**
  - **There's a Discord bot: /meme.**
  - **Open source on GitHub.**
- Starter prompts: **the meeting that could've been an email**, **day 1 of the gym vs day 2**, **starting the essay the night before it's due**, **when the flight gets delayed for the third time**.
- Empty Chat line: **Something happened. We can work with that.** (the line approved in R2-3)
- Empty Arc: **Your arc hasn't started yet. Go be unwell somewhere. Five memes minimum before MemeGPT has anything to judge you for.**
- Mode stories, each with its kicker, title, line and link:
  - **Chat**: **Talk to MemeGPT like any chatbot.** / **Type a thought, attach a photo if you want, and get a meme back. MemeGPT never breaks character. Every reply comes back as a meme.** / **Open Chat**. Example prompt: **day 1 of the gym vs day 2**, with its real render.
  - **Lore**: **Drop in the whole story.** / **Paste a whole group chat or upload a stack of screenshots. Get back several memes, one for every moment worth remembering.** / **Open Lore**
  - **Make**: **Pick the template yourself.** / **Skip the AI's judgment entirely. Search the full template library, write your own captions box by box, and render it exactly your way.** / **Open Make**. Example: Drake, box 1 **letting the AI pick**, box 2 **picking it yourself**.
  - **Arc**: **See your meme era.** / **Your most-summoned template, your longest streak, an aura score that goes up whether you like it or not. Roast copy included, free of charge.** / **Open Arc**. The card is labeled **Example** and uses the sample counts scored by the real formula.
- In brief heading: **In brief**; FAQ heading: **Questions, answered**
- Footer: **Privacy**, **View source on GitHub**, **MemeGPT. Built for fun, not for profit.**

### 7.2 FAQ

Use these five questions and answers:

1. **Is MemeGPT free?** Yes. Every part works without signing in: no email, no account. Signing in only adds saved Chat and Lore history across devices.
2. **What's the difference between Chat, Lore and Make?** Chat is a normal back-and-forth, usually one meme per reply. Lore is for big dumps: paste a whole group chat or a stack of screenshots and get several memes back at once. Make skips the AI's judgment: you pick the template and write the captions.
3. **What if it picks the wrong template?** Thumbs it down. Every reply has feedback buttons, and MemeGPT learns from what actually lands.
4. **Can I upload photos or screenshots?** Yes. Attach up to six at a time in Chat or Lore. MemeGPT reads what's in them the same way it reads text.
5. **Does it work on my phone?** Yes. It's a full mobile site, and you can add it to your home screen. On Android you can share a screenshot straight from Photos into Lore.

### 7.3 Shared group chat for all Lore examples

Use this same transcript in every Lore design, screenshot, example, and sample-data state. Keep one message per line:

> Maya: Flight delayed again. Third time.  
> Leo: That gate has your mail now.  
> June: This meeting could've been an email.  
> You: It has a follow-up meeting.  
> Leo: Do we get an agenda?  
> June: I haven't started the essay.  
> You: It's due tomorrow. Opening the doc at 11:58.  
> Maya: Phone's at 1%.  
> Leo: You sent that with one percent?  
> Maya: I'm committed to the bit.

Collapsed preview shows two or three real lines plus **more messages**. Credit every line used by each meme. Do not repeat quoted lines as a story title. The flight, meeting, essay, and battery moments are distinct and use the source lines listed in the Lore progress spec.

### 7.4 Chat, Lore, Make

- Chat composer: **What happened?**
- Chat composer with image: **Add a caption (optional)**
- Send: **Send**
- Attach button: **Photo**
- Thinking stages: **Looking at the photo** (**Looking at the photos** for more than one), **Reading the message**, **Captioning [template name]**, for example **Captioning Distracted Boyfriend**. Only show the current stage and completed stages.
- Chat history heading: **History**
- History helper: **History saved across devices.**
- History action: **New chat**
- Row action: **Delete**
- Delete confirmation: **Delete this chat?** Button: **Delete chat** (**Deleting…** while busy). Failure: **MemeGPT couldn't delete that chat. Please try again.**
- Lore action: **Drop the lore**
- Lore paste field, label and placeholder: **Paste the group chat**
- Link under the Lore retention copy, to the privacy page: **Privacy**
- Lore count: **Auto**, **1**, **2**, **3**, **4**, **5**
- Remember lore switch: **Remember lore**
- Remember lore helper, on: **Remember lore is on. Short recurring names and jokes are kept for future memes until you use Forget me.**
- Remember lore helper, off (the default): **Remember lore is off. Turn it on to carry recurring names and jokes into future memes.**
- Signed-out Lore retention: **Your text and original photos aren't saved. Only the memes MemeGPT makes are.**
- Signed-in Lore retention: **You're signed in, so this is saved to your history, usually as a short summary of each moment. Original photos aren't kept.**
- Lore progress: **Found 4 moments worth memeing**. Only if Lore finishes short: **Found 4 moments worth memeing. 3 of 4 memes made**
- Failed moment: **This one didn't come out.**
- Example queued row: **Maya's 1% is up next**
- Queued row in the built app, where the moment has no written name: its quoted source lines with **Up next** (its summary with **Up next** when it has no lines)
- Collapsed transcript preview: two or three lines, then **7 more messages** (**1 more message** for one)
- Paste longer than the backend's cut: **Only the first 20,000 characters are used.**
- Lore progress when an explicit count adds takes: **Found 4 moments worth memeing, plus 1 more take**
- Dragging files over Lore: **Drop screenshots here**
- Another take when no different template is left (the current meme stays): **MemeGPT couldn't find a different template for this one.**
- In-progress status names the actual template, for example **Captioning Low Battery**
- Lore result action: **Another take**
- Label above a take row (from an explicit count larger than the moments found), over its repeated source lines: **Another take**
- Rating actions: **Thumbs up**, **Thumbs down**
- Share: **Share**
- Download: **Download**
- Meme that fails to load, in any meme frame: **MemeGPT couldn't load this meme.** Action: **Try again**
- Full-size view of a meme: open control label **Open full size**, dismiss with **Close**
- Thinking stage when a photo is captioned directly, with no catalog template: **Captioning the photo**
- Share where the browser has no share sheet, which copies the meme's share link: **Link copied**. Failure: **Couldn't share. Try Download.**
- History drawer with no saved chats: **No chats yet.**
- Delete confirmation body: **This also removes the memes MemeGPT made in it, any ratings on them, and any lore terms it picked up. Share links to those memes stop working. This can't be undone.**
- Make search placeholder: **Search templates by name, vibe or tag**
- Clear the search: **Clear search**
- Tag on an animated template's listing (its thumbnail is the first frame, still): **GIF**
- Library that couldn't load: **Something broke.** with **Not you. Us. Try again in a moment.** and **Try again**
- Make status while rendering: **Rendering…**
- Template action: **Choose template**
- Caption control labels: **Caption 1**, **Caption 2**, **Caption 3**, **Caption 4**, **Caption 5**. An empty field may show only its matching number.
- Return to library: **Change template**
- Render action: **Render**
- Finished Make action: **Make another**
- No matches: **No templates found. Try another search.**
- Generic render error: **That didn't render. Your captions are still here. Try again.**
- Caption refused: **That caption couldn't be used. Try different text.**
- Chat messages have no visible You or MemeGPT speaker labels. The user's text is the small Archivo line above the meme.
- If a sent photo includes text, it is blank or a moment caption such as **opening the doc at 11:58**. Never caption it as a request to the bot, such as “can you use this photo?” or “here's the photo”.

### 7.5 Limits, uploads, and safety

These occur on ordinary requests such as **Day 1 of the gym vs day 2**, never on a request asking for permission to make another meme.

- Busy: **MemeGPT is busy, try again in a minute.**
- Daily budget, shown after the user's line with one independent ready-made meme and no action row: **MemeGPT runs on a free daily AI budget, and today's is used up. It refills gradually, so try again in a few hours.**
- Own daily limit, text only: **That's your 10 memes for today. They refill over the next 24 hours.**
- Network daily limit, text only: **Everyone on your network has used today's 30 memes. They refill over the next 24 hours.**
- Pick rejected for size: **That image is over 10MB. Try a smaller one.**
- Pick rejected because Chat or Lore would go past six photos: **Up to 6 photos per message. Remove some before adding more.**
- Unsupported image format: **That file isn't a supported image format. Try a JPEG, PNG, or WEBP.**
- Pixel dimensions too large: **That image's dimensions are too large to process. Try a smaller one.**
- Unreadable/corrupt image: **That file couldn't be read as an image. It may be corrupted.**
- Safety refusal after Send, with the sent photo thumbnail: **MemeGPT can't use this image. Try describing it in words instead.**
- General post-send failure: **Upload failed. The one engineer is still the whole department. Try a different photo.**

Size and count checks happen as images are picked. Reject the entire attempted pick if it breaches the limit. Existing attached images remain. Every attached thumbnail in Chat and Lore has a separate 44px Remove target. The one-guy joke appears only on the maintenance page and this upload error.

The budget meme is not personalized. It is one of ten fixed memes, unrelated to the request, with no action row and no share page.

### 7.6 Sign-in, account, Forget me

- Sign-in intro: **Every part works without an account. Signing in only adds saved chat history across devices.**
- Google button: **Continue with Google**
- Signed-in menu: signed-in email, **History**, **Sign out**
- Sign-in failures, under the Google button: **Google sign-in didn't load. A content blocker may be stopping it.** and **That sign-in didn't go through. Try again.**
- Header link: **Forget me**
- Forget me dialog title and main (black) button: **Forget me**; while it works: **Erasing…**; other action: **Cancel**
- Signed-out confirmation: **This erases your memes, ratings and remembered lore from this browser.** Share links to those memes stop working. Your Arc starts over. This can't be undone. Chats saved to an account are only erased while you're signed in to it.
- Signed-in confirmation: **This erases your chats, memes, ratings and remembered lore.** Share links to those memes stop working. Your Arc starts over. This can't be undone. Your account itself stays. To delete it, email support.memegpt@gmail.com.
- Erase failure: **MemeGPT couldn't finish erasing your data. Please try again.** Actions: **Try again**, **Cancel**.
- Sign-in confirmation failure, only while the interface still shows the M avatar: **MemeGPT couldn't confirm your sign-in, so nothing was erased. Sign in again and retry.** Actions: **Sign in**, **Cancel**.
- Forget me erases data, not the Google/Supabase account itself.

### 7.7 Arc

These are the sample outputs; the live strings come from backend/arc/copy.py.

- Frame 01 label: **01 Volume**
- Frame 01 title: **AUTUMN ARC** with the actual data-derived date range if it fits one season; otherwise **YOUR ARC** with the same record dates, e.g. **YOUR ARC • JUN 2–NOV 17, 2026**
- Frame 01 value: **47**
- Frame 01 roast: **memes generated this arc. no thoughts, just memes.**
- Frame 02 label: **02 Signature**
- Frame 02 value: **Empty Meeting Room**, **9 times**
- Frame 02 roast: **your most-summoned template.** plus the template's own roast from arc/copy.py; the sample's **(still waiting on the agenda)** belongs to the stand-in
- Frame 03 label: **03 Witching hour**
- Frame 03 value: **2 AM**
- Frame 03 roast: **we're not asking questions.**
- Frame 04 label: **04 The split**
- Frame 04 values: **26 Chat**, **15 Lore**, **6 Make**
- Frame 04 roast: **chat / lore / make. yappacino.**
- Frame 05 label: **05 Streak**
- Frame 05 value: **6 days**
- Frame 05 roast: **consecutive days. still an arc.**
- Finale: **+12,480 AURA FARMED**
- Current tier: **certified menace**
- Tier table, top to bottom: **aura farming god 20,000**, **baby aura farmer 17,501**, **certified menace 10,000**, **main character (unwell) 5,000**, **side character energy 2,000**, **npc arc 0**
- Distance to next tier: **5,021 to baby aura farmer**
- Verdict: **we've seen growth. we're a little scared.**
- Share action: **Share your Arc**
- Share card facts: **47 memes • 14 different templates**
- Signature art label: **Empty Meeting Room • 9 times**
- Share card footer: **memegpt.app/arc**
- Loading: **Calculating your Arc…**
- Empty state heading: **Your arc hasn't started yet.**
- Empty state text: **Go be unwell somewhere. Five memes minimum before MemeGPT has anything to judge you for.**
- Empty state count: **2 of 5 memes so far.**
- Empty state link: **Start in Chat**
- Rendering the card: **Rendering…**
- Under the rendered card: **Back to your Arc**, beside Share and Download

### 7.8 Shared meme, 404, error, maintenance

- Shared meme description: **Made with MemeGPT. It only replies in memes.**
- Shared meme action: **Make your own**
- 404 heading: **404: not a page.**
- 404 body: **Whatever you were looking for isn't here. The chatbot is, though.**
- 404 meme caption: **IS THIS A PAGE?**
- 404 action: **Open MemeGPT**
- Error heading: **Something broke.**
- Error body: **Not you. Us. Try again in a moment.**
- Error meme caption: **THE SERVER, RIGHT NOW**
- Error action: **Try again**
- Error link: **Back home**
- Maintenance archive heading: **From the archives**
- Maintenance pair 1: **brb, MemeGPT is touching grass** / **We're off rebuilding something even more unhinged. The servers needed a nap. Back soon.**
- Maintenance pair 2: **ONE DOES NOT SIMPLY ship features without downtime** / **MemeGPT is getting a glow-up. Enjoy the archives while we pretend this was always the plan.**
- Maintenance pair 3: **MemeGPT is currently unavailable due to unprecedented demand for unhinged content** / **Our engineers are working around the clock. (They are not. It's one guy. He's tired.)**
- Maintenance pair 4: **THIS IS FINE.** / **Everything is on fire. We lit it. On purpose. For good reasons. Mostly.**
- Maintenance pair 5: **EXPANDING BRAIN: just 5 minutes of maintenance** / **Three days later: 40 new bugs, 2 existential crises, 1 slightly better meme engine.**
- Maintenance pair 6: **Still loading, since forever** / **Somewhere between a quick patch and a total rebuild we lost track of time. It'll be worth it. Probably.**

Maintenance pairs are the live wording. Choose one randomly on each page visit and keep it still for that visit. Show three or four archive memes in a static Front Page grid. No controls while maintenance is active.

### 7.9 Privacy page copy

Keep this copy unchanged except for the new section link list, date, and support footer below. Preserve the heading and section order. Do not compress the meaning or remove any service/provider disclosures.

**Privacy**

MemeGPT is a small, self-funded side project, not a company with a data team. This page says exactly what happens to what you send, in plain language, because that's more useful than a legal document nobody reads.

**Last updated October 8, 2026**

Section links, in order: **Without signing in** · **Your memes** · **Photos and screenshots** · **Lore's "remember lore" toggle** · **If you sign in** · **What MemeGPT doesn't keep** · **Daily limits** · **Analytics** · **Who else touches this** · **Forget me** · **Kids** · **Changes**

#### Without signing in

The first time you use MemeGPT, your browser makes up a random id and saves it on your device. That id is sent with your requests so MemeGPT can recognize the same browser next time. On its own it isn't tied to your name or your email.

Kept against that id: a record of each meme you make (which template, when, and whether it came from Chat, Lore or Make), the meme image itself, and your 👍/👎 ratings. That record is what Arc counts. It is also how MemeGPT avoids repeating templates and leans toward the ones you like.

The words you type are not saved. They are sent to the AI model that picks a template and writes the captions (in Make, it only checks that your captions are safe), and that is the end of them. The captions live on only as part of the meme image.

#### Your memes

Every meme MemeGPT makes is saved as an image so it can be shown and shared. Each one gets a link with a random address that can't be guessed. Anyone you give that link to can see the meme, without signing in. MemeGPT never lists or publishes your memes anywhere, and they stay until you delete them.

#### Photos and screenshots

Every image goes through the same safety steps before anything else touches it: size and type checks, all metadata (like your phone's GPS tags) removed by rebuilding the image from its pixels, and a content-safety check. For that check, and to understand what's in the picture, the image is sent to Groq, the same service that runs the AI model.

Your original file is not kept. MemeGPT holds it only while your request is being handled and drops it when your memes are done or the request fails.

If the safety check turns a photo down, MemeGPT counts that it happened and under which broad category (violence, for example). Nothing about the photo, its file name or who sent it is kept with that count.

There is one exception, and you choose it: if you ask MemeGPT to "make this a meme", your own photo becomes the meme. The captioned copy, with its metadata removed, is saved like any other meme.

A photo sent from your phone's share sheet waits on the server for about 10 minutes so MemeGPT can pick it up when the app opens. If you never open it, the photo is dropped.

#### Lore's "remember lore" toggle

Off by default. When you turn it on, MemeGPT pulls short recurring names and running jokes out of what you paste, never the whole text, so later memes can make callbacks. Turning it off again only stops new ones being added. What is already remembered stays until you erase it.

#### If you sign in

Sign-in is through Google, handled for MemeGPT by Supabase. Your Google name, email address and profile picture are stored with your account. MemeGPT never sees your password.

Signing in turns on saved history, and saved history does store text. In Chat, MemeGPT saves your messages as you typed them, together with the memes they produced, so a conversation can be shown again on any device. In Lore, what is saved is a short summary of each moment MemeGPT found in your paste. When the paste is short, or MemeGPT can't split it into moments, the paste itself is saved. For a photo, the saved text is MemeGPT's description of the photo, not the photo. If you asked for your own photo to be captioned, your request and the captions are saved.

Signing in also links the history already on that browser to your account.

Every saved chat has its own delete button. Deleting a chat removes its messages, the memes it produced and their images, the ratings on those memes, and any lore picked up from it. Share links to those memes stop working.

#### What MemeGPT doesn't keep

Signed out, the text you send is not saved, and neither are your original photos. The one exception is remembered lore, and only if you turn it on. Signed in, your text is also saved as chat history, as described above. There's no ad tracking and no cross-site tracking pixel on this app.

#### Daily limits

MemeGPT runs on a free daily AI budget, so each browser and each network can make a limited number of memes a day. To count them, the server keeps your browser's id and your network address (your IP address) in its memory next to a number, for up to 24 hours. That count is never written to the database, and it is gone whenever the server restarts.

Separately, the companies that host MemeGPT see your network address, as the host of any website does, and keep their own access logs.

#### Analytics

MemeGPT uses Google Analytics to see aggregate things like which pages get visited and roughly how much traffic the app gets, not what you typed, uploaded, or generated. It's not linked to any ad network, and it's separate from the anonymous id described above.

#### Who else touches this

MemeGPT runs on other companies' services. Each one gets only what its job needs.

- **Vercel:** Vercel serves the website and passes your Chat and Lore messages on to the backend.
- **Render:** Render runs the backend that makes the memes.
- **Groq:** Groq runs the AI model. It receives your messages, and your photos when you upload them.
- **Gemini:** Google's Gemini turns your message into a search of the template library, so it receives your message text too. For a photo, it receives MemeGPT's description of the photo, not the photo. MemeGPT uses Gemini's free tier. Under Google's terms for that tier, Google may use what it receives to improve its products, and people at Google may read it.

  > Please don't put anything in a message that you wouldn't want a stranger to read.

- **Cloudflare:** Cloudflare stores the finished meme images.
- **Supabase:** Supabase runs sign-in and hosts the database that holds everything described on this page.
- **Google:** Google provides the sign-in button and Analytics.

MemeGPT doesn't sell your data.

#### Forget me

The "Forget me" link in the header erases what MemeGPT holds about you and clears the id from your device.

Signed in, that means everything on your account: saved chats and their messages, your memes and their images, your ratings, and any remembered lore. It also covers anything from this browser that isn't part of an account. Signed out, it means everything tied to this browser's id that isn't part of an account. History that belongs to an account can only be erased while you are signed in to it, because a browser id on its own doesn't prove who is asking.

Deleted memes are really deleted, so share links to them stop working. If MemeGPT can't finish the erase, it says so instead of pretending it worked, and you can try again.

Forget me doesn't delete the sign-in account itself. If you want that gone too, email support.memegpt@gmail.com and it will be deleted by hand.

#### Kids

MemeGPT isn't directed at children under 13, and knowingly doesn't collect data from them.

#### Changes

If what MemeGPT collects changes in a way that matters, this page changes first. No silent updates.

Footer: **Questions? Email support.memegpt@gmail.com or open an issue on GitHub.**

## 8. Brand assets, metadata, and rendering

### Wordmark

Set **MemeGPT** in Anton with exact mixed case. Provide a vector source for the masthead and a compact wordmark sized 24px high in the phone header. The desktop masthead can scale from this source, but the site headline remains more visually dominant on the cover.

### App icon

Use full-bleed white with an Anton **M** and one tabloid-red rule, both placed inside the central 80% maskable safe area. Do not draw a frame, border, rounded square, or device tile. Export maskable and standard platform assets from the same source. Review it in context at 16×16 and 32×32 browser-tab sizes and at the actual 24px phone-header wordmark size. Keep enough clear space that the red rule and M remain distinct after Android's mask and iOS corner rounding.

### Link preview

Create a 1200×630 (1.91:1) site-wide social preview for links to the website. Use the Front Page cover, with:

- **The group chat has a front page.**
- **A chatbot that only replies in memes.**

Do not use the Lore headline. Do not use a 3:1 layout or the old square Drake meme. Shared meme URLs continue to preview the actual shared meme.

### Metadata and manifest

- HTML title: **MemeGPT: a chatbot that only replies in memes**
- Meta description: **A chatbot that only replies in memes.**
- App manifest description: **A chatbot that only replies in memes.**
- Manifest background color: **#FFFFFF**
- Manifest theme color: **#FFFFFF**
- Manifest app name and short name: **MemeGPT**
- Manifest start route stays /chat.
- Replace the square Drake global preview with the 1200×630 Front Page social card.
- Viewport theme color: **#FFFFFF**. app/layout.tsx still sets #030712, which would tint the browser bar near-black above the white page.
- iOS status bar style: **default**. layout.tsx sets black-translucent, which would put white status-bar text over the white page in the installed app.

### Meme watermark and compositor

The watermark is lowercase **memegpt**, white fill, solid black outline, and the same caption treatment as the meme text. Keep its current size and position: about 3.5% of the image height, bottom-right, with its current padding. Apply it to every static meme and GIF. Do not lower opacity for white-background memes. Fix the server compositor so static output is solid rather than saving see-through fill pixels, and flatten transparent templates (chill_guy.png, party_parrot.gif) onto white before captioning so every meme comes out fully opaque. Keep the bottom-right safe zone clear on the Arc share card footer because the backend stamps the watermark there too. Captions and the watermark are drawn into the image by the Python compositor, so they have no CSS tokens.

### Meme output and shell image rules

- Captions: Anton, uppercase, white with heavy solid black stroke.
- Watermark: exact treatment above.
- Interface mat: #E7E8EA plus a hairline edge on every meme, even if the image background is white.
- Never add interface red to the four reusable stand-in images.
- Never crop or stretch image bytes in the browser, card, or share action.
- Animated GIFs keep their animation in app views; a static thumbnail can use its first frame. Do not apply a motion effect on top of the GIF.

## 9. Fonts and licenses

Self-host fonts at build time so page use does not depend on an external font request. Use WOFF2 subsets and include the license files with the assets. Do not use Inter, Geist, Poppins, Montserrat, Space Grotesk, DM Sans, Manrope, Plus Jakarta Sans, Satoshi, Clash Display, or Instrument Serif.

| Family | Roles | License and source |
| --- | --- | --- |
| Anton | Landing headline, selected editorial headings, wordmark, meme captions | SIL Open Font License 1.1. [Google Fonts specimen](https://fonts.google.com/specimen/Anton) · [Google Fonts source metadata](https://github.com/google/fonts/blob/main/ofl/anton/METADATA.pb) |
| Archivo | Body, navigation, controls, user message/story lines, form labels | SIL Open Font License 1.1. [Google Fonts specimen](https://fonts.google.com/specimen/Archivo) · [Google Fonts source metadata](https://github.com/google/fonts/blob/main/ofl/archivo/METADATA.pb) |

Bundle only the weights and subsets in use. Anton is a display face, not the body font. Body copy and controls stay at accessible sizes in Archivo. The server needs Archivo as a TTF in backend/fonts too, for the Arc share card, committed with its license and with no fallback font; Anton is already there.

## 10. Accessibility and acceptance checks

Before implementation is called complete, check these states at 390×844, 768px, 1024px, and 1440×900:

- Every control and field can be reached and activated by keyboard. Focus is obvious against white, black, red, and gray.
- Text and icon labels meet WCAG AA contrast. Red used for text and underlines remains readable on white. Do not use pale gray for required instructions.
- Every tap target is at least 44×44px, including Photo, Send, Remove, action-row items, section links, bottom tabs, dialog buttons, and progress navigation.
- Text fields use at least 16px. Long headlines, group chat lines, consent copy, captions, and actions do not clip.
- Phone screens show only the bottom app navigation, never a second tab row in the header.
- Landing has no active app tab. Chat, Lore, Make, and Arc show exactly one active tab. Arc never changes the navigation styling.
- Every meme keeps its actual dimensions, gray mat, edge, caption treatment, and watermark.
- Chat photo remains in the composer until Send. A rejected photo pick is all-or-nothing, and previously attached items remain removable.
- Lore quotes only lines the backend validated, and shows summaries for screenshots. Progress and results are separate states; only the active row spins.
- Make shows full thumbnails, numbered caption boxes, and no rating controls.
- With the sample fixture, Arc shows the stated figures, three equal-width split bars and a tier table that marks the current tier.
- Sign-in is Google only. Forget me is available in the header for signed-in and signed-out users; failures remain in its dialog.
- Privacy copy has twelve linked sections, vendor list, Gemini pull quote, and support footer.
- The global preview is 1200×630. The Arc card is 1080×1350. The app icon is unframed full-bleed white with its content inside the safe zone.
- The browser theme color is white, the iOS status bar style is default, and no dark-theme class remains: no raw text-gray-*, text-white or bg-white/* classes, and no bg-accent fill outside Arc.
- Reduced-motion mode removes transforms and animated swaps while preserving the same state order and all controls.
- No user count, testimonial, claim, review, press mark, or marketing statistic has been added.

## 11. Implementation order

1. Backend first, on main, since several screens depend on it, with each change invisible to today's site: Lore line numbers and distinct_templates as optional new fields, and the new Arc card as a second style with Archivo on the server. The watermark fix ships separately, followed by re-rendering the frontend/public memes that carry see-through watermark pixels.
2. Ship the full light token layer (shadcn's variables and the raw gray and white classes included), font files, masthead, desktop top tabs, phone bottom tabs, common focus states, and shared meme frame.
3. Implement Chat composer, lead story, earlier stories, thinking stages, history drawer, ratings/actions, and limit/error states.
4. Implement Lore input, transcript, image validation/removal, sequential progress, and result layout.
5. Implement Make search/listing, caption editor, finished-meme state, and its notices.
6. Implement Arc empty state, frames, tier finale, server-rendered card, and its safe footer area.
7. Implement landing cover and lower editorial stories, the landing composer's hand-off to Chat, shared meme page, sign-in/account/Forget me, system pages, and the full privacy page.
8. Update the metadata, manifest, theme color, iOS status bar style, icon exports (scripts/render_icons.py), and site-wide link preview.
9. Apply and verify the motion map, reduced-motion behavior, keyboard paths, text contrast, and 44px targets.

Steps 2 to 9 happen on the redesign branch. Merge it into main only when you decide to launch it.

