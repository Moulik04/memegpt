// Run by `npm test` and by prebuild: node --test, no test framework.
import { test } from "node:test";
import assert from "node:assert/strict";
import { correctTemplateName, templateDisplayName, templateNameFromId } from "./templateNames.ts";

test("ids title-case into names", () => {
  assert.equal(templateNameFromId("always_has_been"), "Always Has Been");
  assert.equal(templateNameFromId("drake"), "Drake");
});

test("the four ids that don't title-case cleanly get their real names", () => {
  assert.equal(templateNameFromId("i_m_the_captain_now"), "I'm The Captain Now");
  assert.equal(
    templateNameFromId("this_is_where_i_d_put_my_trophy_if_i_had_one"),
    "This Is Where I'd Put My Trophy If I Had One",
  );
  assert.equal(
    templateNameFromId("whe_i_m_in_a_competition_and_my_opponent_is"),
    "When I'm In A Competition And My Opponent Is",
  );
  assert.equal(templateNameFromId("x_x_everywhere"), "X, X Everywhere");
});

test("the backend's name is kept unless the id is one of the four", () => {
  assert.equal(templateDisplayName("drake", "Drake"), "Drake");
  assert.equal(templateDisplayName("x_x_everywhere", "X X Everywhere"), "X, X Everywhere");
});

test("a name alone is corrected when it is one of the four catalog names", () => {
  assert.equal(correctTemplateName("I M The Captain Now"), "I'm The Captain Now");
  assert.equal(correctTemplateName("Whe I M In A Competition And My Opponent Is"), "When I'm In A Competition And My Opponent Is");
  assert.equal(correctTemplateName("Always Has Been"), "Always Has Been");
  assert.equal(correctTemplateName("My MemeGPT Arc"), "My MemeGPT Arc");
});
