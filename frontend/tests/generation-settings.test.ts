import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_OUTPUT_OPTIONS,
  OUTPUT_OPTIONS,
  parseGenerationSettings,
  toggleOutputOption,
} from "../lib/generation-settings.ts";
import type { OutputOption } from "../types/action-pack.ts";

test("Quick Revision Notes can be selected and deselected independently", () => {
  const selected = toggleOutputOption(
    [...DEFAULT_OUTPUT_OPTIONS],
    "quick_revision_notes",
    true,
  );

  assert.equal(selected.includes("quick_revision_notes"), true);
  assert.equal(selected.includes("visual_mind_map"), true);
  assert.equal(selected.includes("voice_lesson"), true);

  const deselected = toggleOutputOption(
    selected,
    "quick_revision_notes",
    false,
  );
  assert.equal(deselected.includes("quick_revision_notes"), false);
  assert.equal(deselected.includes("visual_mind_map"), true);
});

test("all seven outputs support independent multi-selection without duplicates", () => {
  const selected = OUTPUT_OPTIONS.reduce<OutputOption[]>(
    (current, option) =>
      toggleOutputOption(current, option.value, true),
    [],
  );

  assert.equal(selected.length, 7);
  assert.deepEqual(new Set(selected).size, 7);

  const unchanged = toggleOutputOption(
    selected,
    "quick_revision_notes",
    true,
  );
  assert.deepEqual(unchanged, selected);

  const withoutVoice = toggleOutputOption(
    selected,
    "voice_lesson",
    false,
  );
  assert.equal(withoutVoice.includes("voice_lesson"), false);
  assert.equal(withoutVoice.length, 6);
});

test("saved multi-output choices parse without resetting to defaults", () => {
  const saved = parseGenerationSettings(
    JSON.stringify({
      learner_profile: null,
      output_options: [
        "quick_revision_notes",
        "flashcards",
        "interview_revision_sheet",
      ],
      visual_topics: [],
      voice_mode: "normal",
    }),
  );

  assert.deepEqual(saved.output_options, [
    "quick_revision_notes",
    "flashcards",
    "interview_revision_sheet",
  ]);
});
