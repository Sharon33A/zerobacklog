import type { OutputOption } from "@/types/action-pack";

export interface LearnerProfileSettings {
  dsa_level: string | null;
  known_topics: string[];
  weak_topics: string[];
  preferred_language: string | null;
  target_role_or_company: string | null;
  available_study_minutes_per_day: number | null;
  target_interview_date: string | null;
}

export interface GenerationSettings {
  learner_profile: LearnerProfileSettings | null;
  output_options: OutputOption[];
  visual_topics: string[];
  voice_mode: "normal" | "quick_revision";
}

export const GENERATION_SETTINGS_KEY = "zerobacklog-generation-settings";

export const OUTPUT_OPTIONS: ReadonlyArray<{
  value: OutputOption;
  label: string;
}> = [
  { value: "complete_action_pack", label: "Complete Action Pack" },
  { value: "quick_revision_notes", label: "Quick Revision Notes" },
  { value: "visual_mind_map", label: "Visual Mind Map" },
  { value: "voice_lesson", label: "Voice Lesson" },
  { value: "flashcards", label: "Flashcards" },
  { value: "priority_coding_problems", label: "Priority Coding Problems" },
  { value: "interview_revision_sheet", label: "Interview Revision Sheet" },
];

export const DEFAULT_OUTPUT_OPTIONS: OutputOption[] = [
  "complete_action_pack",
  "visual_mind_map",
  "voice_lesson",
];

export const DEFAULT_GENERATION_SETTINGS: GenerationSettings = {
  learner_profile: null,
  output_options: DEFAULT_OUTPUT_OPTIONS,
  visual_topics: [],
  voice_mode: "normal",
};

const VALID_OUTPUTS = new Set(OUTPUT_OPTIONS.map((option) => option.value));

export function toggleOutputOption(
  current: OutputOption[],
  option: OutputOption,
  checked: boolean,
): OutputOption[] {
  if (checked) {
    return current.includes(option) ? current : [...current, option];
  }
  return current.filter((item) => item !== option);
}

export function parseGenerationSettings(raw: string | null): GenerationSettings {
  if (!raw) return { ...DEFAULT_GENERATION_SETTINGS };
  try {
    const parsed = JSON.parse(raw) as Partial<GenerationSettings>;
    const outputOptions = Array.isArray(parsed.output_options)
      ? parsed.output_options.filter(
          (option): option is OutputOption =>
            typeof option === "string" &&
            VALID_OUTPUTS.has(option as OutputOption),
        )
      : [];
    return {
      learner_profile: parsed.learner_profile ?? null,
      output_options:
        outputOptions.length > 0 ? outputOptions : [...DEFAULT_OUTPUT_OPTIONS],
      visual_topics: Array.isArray(parsed.visual_topics)
        ? parsed.visual_topics.filter(
            (topic): topic is string => typeof topic === "string",
          )
        : [],
      voice_mode:
        parsed.voice_mode === "quick_revision" ? "quick_revision" : "normal",
    };
  } catch {
    return { ...DEFAULT_GENERATION_SETTINGS };
  }
}

export function formatProfileSummary(
  profile: LearnerProfileSettings | null,
): string[] {
  if (!profile) return ["General learner profile"];
  const items: string[] = [];
  if (profile.dsa_level) {
    items.push(
      profile.dsa_level.charAt(0).toUpperCase() + profile.dsa_level.slice(1),
    );
  }
  if (profile.weak_topics.length > 0) {
    items.push(`Weak in ${profile.weak_topics.join(", ")}`);
  }
  if (profile.target_role_or_company) {
    items.push(profile.target_role_or_company);
  }
  if (profile.preferred_language) {
    items.push(profile.preferred_language);
  }
  if (profile.available_study_minutes_per_day) {
    items.push(`${profile.available_study_minutes_per_day} min/day`);
  }
  return items.length > 0 ? items : ["General learner profile"];
}
