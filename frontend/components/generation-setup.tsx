"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  DEFAULT_OUTPUT_OPTIONS,
  GENERATION_SETTINGS_KEY,
  OUTPUT_OPTIONS,
  parseGenerationSettings,
  toggleOutputOption,
} from "@/lib/generation-settings";
import type { OutputOption } from "@/types/action-pack";

export function GenerationSetup() {
  const router = useRouter();
  const [level, setLevel] = useState("");
  const [known, setKnown] = useState("");
  const [weak, setWeak] = useState("");
  const [language, setLanguage] = useState("");
  const [minutes, setMinutes] = useState("");
  const [target, setTarget] = useState("");
  const [date, setDate] = useState("");
  const [topics, setTopics] = useState("");
  const [voiceMode, setVoiceMode] = useState<"normal" | "quick_revision">(
    "normal",
  );
  const [outputs, setOutputs] = useState<OutputOption[]>([
    ...DEFAULT_OUTPUT_OPTIONS,
  ]);

  useEffect(() => {
    const saved = parseGenerationSettings(
      window.localStorage.getItem(GENERATION_SETTINGS_KEY),
    );
    const profile = saved.learner_profile;
    if (profile) {
      setLevel(profile.dsa_level || "");
      setKnown(profile.known_topics.join(", "));
      setWeak(profile.weak_topics.join(", "));
      setLanguage(profile.preferred_language || "");
      setMinutes(profile.available_study_minutes_per_day?.toString() || "");
      setTarget(profile.target_role_or_company || "");
      setDate(profile.target_interview_date || "");
    }
    setOutputs(saved.output_options);
    setTopics(saved.visual_topics.join(", "));
    setVoiceMode(saved.voice_mode);
  }, []);

  function continueToResources(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (outputs.length === 0) return;
    const learnerProfile = {
      dsa_level: level || null,
      known_topics: known.split(",").map((item) => item.trim()).filter(Boolean),
      weak_topics: weak.split(",").map((item) => item.trim()).filter(Boolean),
      preferred_language: language.trim() || null,
      available_study_minutes_per_day: minutes ? Number(minutes) : null,
      target_role_or_company: target.trim() || null,
      target_interview_date: date || null,
    };
    const hasProfile = Object.values(learnerProfile).some((value) =>
      Array.isArray(value) ? value.length > 0 : value !== null,
    );
    window.localStorage.setItem(
      GENERATION_SETTINGS_KEY,
      JSON.stringify({
        learner_profile: hasProfile ? learnerProfile : null,
        output_options: outputs,
        visual_topics: topics
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean)
          .slice(0, 3),
        voice_mode: voiceMode,
      }),
    );
    router.push("/upload");
  }

  return (
    <form className="setup-form" onSubmit={continueToResources}>
      <section>
        <p className="section-kicker">Optional learner profile</p>
        <h2>Make the pack fit the interview ahead.</h2>
        <p>Skip every field for a complete, general Action Pack.</p>
        <div className="setup-grid">
          <label>
            Current experience level
            <select value={level} onChange={(event) => setLevel(event.target.value)}>
              <option value="">General</option>
              <option value="beginner">Beginner</option>
              <option value="intermediate">Intermediate</option>
              <option value="advanced">Advanced</option>
            </select>
          </label>
          <label>
            Known topics
            <input
              value={known}
              onChange={(event) => setKnown(event.target.value)}
              placeholder="arrays, recursion"
            />
          </label>
          <label>
            Weak topics
            <input
              value={weak}
              onChange={(event) => setWeak(event.target.value)}
              placeholder="graphs, dynamic programming"
            />
          </label>
          <label>
            Preferred language
            <input
              value={language}
              onChange={(event) => setLanguage(event.target.value)}
              placeholder="English"
            />
            <small>
              English is the primary analysis language. Other languages are
              best-effort for generated text and voice.
            </small>
          </label>
          <label>
            Study minutes per day
            <input
              type="number"
              min="10"
              max="1440"
              value={minutes}
              onChange={(event) => setMinutes(event.target.value)}
              placeholder="45"
            />
          </label>
          <label>
            Target role or company
            <input
              value={target}
              onChange={(event) => setTarget(event.target.value)}
              placeholder="Backend engineer"
            />
          </label>
          <label>
            Target interview date
            <input
              type="date"
              value={date}
              onChange={(event) => setDate(event.target.value)}
            />
          </label>
        </div>
      </section>

      <section>
        <p className="section-kicker">Output selection</p>
        <h2>Choose what should be generated.</h2>
        <div className="setup-output-grid">
          {OUTPUT_OPTIONS.map((option) => (
            <label htmlFor={`output-${option.value}`} key={option.value}>
              <input
                id={`output-${option.value}`}
                type="checkbox"
                checked={outputs.includes(option.value)}
                onChange={(event) =>
                  setOutputs((current) =>
                    toggleOutputOption(
                      current,
                      option.value,
                      event.target.checked,
                    ),
                  )
                }
              />
              <span>{option.label}</span>
            </label>
          ))}
        </div>
        {outputs.includes("visual_mind_map") && (
          <label className="setup-wide-field">
            Visual topics (up to three)
            <input
              value={topics}
              onChange={(event) => setTopics(event.target.value)}
              placeholder="Leave blank to visualize the Start Here topic"
            />
          </label>
        )}
        {outputs.includes("voice_lesson") && (
          <label className="setup-wide-field">
            Voice lesson mode
            <select
              value={voiceMode}
              onChange={(event) =>
                setVoiceMode(event.target.value as "normal" | "quick_revision")
              }
            >
              <option value="normal">Normal narration</option>
              <option value="quick_revision">Quick revision</option>
            </select>
          </label>
        )}
      </section>

      <button type="submit" disabled={outputs.length === 0}>
        Continue to resources
      </button>
      {outputs.length === 0 && <p role="alert">Choose at least one output.</p>}
    </form>
  );
}
