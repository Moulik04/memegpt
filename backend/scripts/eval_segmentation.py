"""
Segmentation eval — pastes with a known number of distinct moments, run
through the real segment_contexts() on the configured model with an explicit
meme count, the way Lore calls it.

Three separate metrics, because they fail for different reasons:
  - Count honoured: asking for N returns exactly N entries. A miss means the
    fill-up logic is broken, since takes exist to guarantee this.
  - Nothing repeats: no two entries presented as moments are exact or
    reworded copies of each other, and every extra is marked as a take. A
    miss means a repeat reached the plan.
  - Moments found: the number of distinct moments equals the number really
    in the paste. Fewer means a real moment was missed (or a real one was
    wrongly merged as a repeat), more means one moment was split in two.
    This is the model's judgment, and the only one of the three that can
    legitimately vary from run to run.

Each case runs several times: segmentation runs at a non-zero temperature,
so one pass says little. Runs where the model call failed outright (the
single-context fallback) are reported and left out of every denominator, the
same way eval_template_matching.py treats a hard-fallback pick — a rate
limit is not a segmentation result.

Paced at 10s per case — Groq's free tier is ~8000 tokens/min.

Run: cd backend && python -m scripts.eval_segmentation [passes]
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from itertools import combinations

from nlp.segmentation import _combine_raw, _is_near_duplicate, segment_contexts

_PACE_SECONDS = 10
_DEFAULT_PASSES = 3


@dataclass
class Case:
    name: str
    known_moments: int
    requested: int
    text: str


# Rebuilt from a real Lore plan that listed these four. The last two are
# consecutive lines from one person about one subject (anticipating a
# release, then having already heard it live), which makes them the hardest
# pair here to keep apart.
_FOUR_MOMENTS = """\
jay: has anyone seen the mail room key
jay: i have checked the front desk, the kitchen drawer, the plant pot and INSIDE THE MICROWAVE
priya: it was in the fridge door last week lol
jay: i am losing my mind, nobody can find it for the life of them. it hides in the most ridiculous places
sam: i have it
jay: WHAT. give it to me, i need to send a package out right now, it is urgent
sam: nah i'll hand it over on monday
jay: MONDAY?? you are acting insane, i have a task due today
sam: monday.
priya: ok unrelated but i am fully on the hype train for the new drake album
priya: the song is called nitrous, i am convinced, just waiting for the big drop any day now
priya: i already heard the track live at the show and now i literally cannot wait another second for the official release, i am begging
"""

_FIVE_MOMENTS = """\
dev: flight update. delayed six hours and they have changed the gate three times, i have walked the whole terminal twice
dev: also my landlord just texted "quick question" at 11pm and the question was whether i am ok with rent going up 300
noor: mine does that. unrelated, my sourdough starter exploded in the fridge overnight, there is dough on the ceiling of the fridge
noor: like it lifted the lid off and kept going
dev: lol
noor: went to the gym to cope and a guy was doing bicep curls in the only squat rack while four of us stood there waiting
dev: my boss just scheduled a meeting to plan the agenda for the meeting we are having tomorrow
dev: a meeting about the meeting
"""

# Five different moments that share the same two people and one trip — the
# case most likely to trip a near-duplicate check into merging real moments.
_FIVE_MOMENTS_SAME_PEOPLE = """\
me: road trip recap for everyone who bailed
me: leo swore he knew a shortcut and it added two hours, we drove past the same water tower three times
me: maya was on aux the whole way and her playlist was one song, the same song, for forty minutes straight
tess: no
me: the motel advertised a pool and it was a puddle with a ladder in it
me: then leo locked the keys in the car at a gas station in the middle of nowhere and we waited ninety minutes for a guy with a coat hanger
me: and while we waited maya paid eighteen dollars for a gas station sandwich and has spent every hour since insisting it was worth it
"""

_THREE_MOMENTS = """\
ok three things from today. my cat looked me dead in the eye and slowly pushed the plant off the shelf, did not break eye contact once.
then the hoodie i ordered arrived, it says medium on the tag and it would fit a toddler, the sleeves stop at my elbows.
and my neighbor has been drilling into the shared wall since seven this morning, on a sunday, for what i can only assume is a mural made of holes.
"""

_TWO_MOMENTS = """\
group project is due friday. i wrote the whole report, built the slides and ran the survey, and last night the other three opened the doc just long enough to add their names to the title page.
and then at midnight the professor emailed to say the deadline is now wednesday, not friday, "to give everyone more time to prepare for the presentation".
"""

# One subject, three separate punchlines: the frozen interview, the router
# that keeps losing, and the rota. Same topic throughout, so this checks
# that a shared subject alone does not collapse distinct beats into one.
_ONE_TOPIC_THREE_BEATS = """\
my wifi dies every single time someone uses the microwave. every time. i was mid-interview on a video call and my roommate reheated soup and i froze with my mouth open for a full minute.
i have moved the router twice. i have bought a new router. the new router also loses to the microwave. the microwave is undefeated.
at this point we announce it in the group chat before heating anything so people can save their work. we have a rota. for a microwave.
"""

CASES: list[Case] = [
    Case("four moments, ask 5", 4, 5, _FOUR_MOMENTS),
    Case("five moments, ask 5", 5, 5, _FIVE_MOMENTS),
    Case("five moments same people, ask 5", 5, 5, _FIVE_MOMENTS_SAME_PEOPLE),
    Case("five moments, ask 3", 5, 3, _FIVE_MOMENTS),
    Case("three moments, ask 5", 3, 5, _THREE_MOMENTS),
    Case("two moments, ask 5", 2, 5, _TWO_MOMENTS),
    Case("one topic three beats, ask 5", 3, 5, _ONE_TOPIC_THREE_BEATS),
]


@dataclass
class Run:
    case: Case
    failed: bool
    total: int = 0
    moments: list[str] | None = None
    takes: int = 0
    repeats: int = 0

    @property
    def expected_moments(self) -> int:
        return min(self.case.known_moments, self.case.requested)

    @property
    def count_honoured(self) -> bool:
        return self.total == self.case.requested

    @property
    def nothing_repeats(self) -> bool:
        return self.repeats == 0

    @property
    def moments_found(self) -> int:
        return len(self.moments or [])


async def run_case(case: Case) -> Run:
    contexts = await segment_contexts(case.text, None, case.requested)
    if len(contexts) == 1 and contexts[0].situation == _combine_raw(case.text, []):
        return Run(case, failed=True)
    moments = [c.situation for c in contexts if c.take_of is None]
    repeats = sum(1 for a, b in combinations(moments, 2) if _is_near_duplicate(a, b))
    return Run(
        case,
        failed=False,
        total=len(contexts),
        moments=moments,
        takes=sum(1 for c in contexts if c.take_of is not None),
        repeats=repeats,
    )


async def main() -> None:
    passes = int(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_PASSES
    runs: list[Run] = []
    first = True
    for p in range(passes):
        print(f"\n=== pass {p + 1}/{passes} ===")
        for case in CASES:
            if not first:
                await asyncio.sleep(_PACE_SECONDS)
            first = False
            run = await run_case(case)
            runs.append(run)
            if run.failed:
                print(f"  [FAILED ] {case.name}: model call failed, excluded")
                continue
            verdict = "OK" if run.count_honoured and run.nothing_repeats and run.moments_found == run.expected_moments else "CHECK"
            print(
                f"  [{verdict:7s}] {case.name}: returned {run.total}/{case.requested}, "
                f"{run.moments_found} moments (expected {run.expected_moments}) + {run.takes} takes, "
                f"repeats {run.repeats}"
            )
            for i, moment in enumerate(run.moments or []):
                print(f"              {i + 1}. {moment}")

    scored = [r for r in runs if not r.failed]
    excluded = len(runs) - len(scored)
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    if not scored:
        print(f"Every run failed ({excluded}) — nothing to score. Check the provider and rate limits.")
        return
    n = len(scored)
    honoured = sum(1 for r in scored if r.count_honoured)
    clean = sum(1 for r in scored if r.nothing_repeats)
    exact = sum(1 for r in scored if r.moments_found == r.expected_moments)
    under = sum(1 for r in scored if r.moments_found < r.expected_moments)
    over = sum(1 for r in scored if r.moments_found > r.expected_moments)
    print(f"Runs scored:          {n}  (excluded as failed model calls: {excluded})")
    print(f"Count honoured:       {honoured}/{n} ({100 * honoured / n:.0f}%)")
    print(f"Nothing repeats:      {clean}/{n} ({100 * clean / n:.0f}%)")
    print(f"Moments found exact:  {exact}/{n} ({100 * exact / n:.0f}%)  — missed a real one: {under}, split one: {over}")
    print("\nPer case (moments found across passes, expected):")
    for case in CASES:
        found = [r.moments_found for r in scored if r.case is case]
        if found:
            print(f"  {case.name:34s} {found}  expected {min(case.known_moments, case.requested)}")


if __name__ == "__main__":
    asyncio.run(main())
