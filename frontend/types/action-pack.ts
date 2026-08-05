export interface EvidenceReference {
  resource_id: string;
  title: string;
  location: string | null;
  confidence: number;
  basis: "source_derived" | "ai_inferred";
  support: string;
}

export interface ResourceChoice {
  resource_id: string;
  title: string;
  reason: string;
  evidence: EvidenceReference[];
}

export interface ActionPack {
  title: string;
  executive_summary: string;
  backlog_reduction: {
    resource_count: number;
    estimated_original_minutes: number | null;
    repeated_content_percentage: number;
    metric_methodology: string;
    essential_resources: ResourceChoice[];
    optional_resources: ResourceChoice[];
    skippable_resources: ResourceChoice[];
  };
  start_here: {
    topic_or_resource: string;
    why: string;
    estimated_minutes: number | null;
    evidence: EvidenceReference[];
  };
  common_topics: Array<{
    topic: string;
    explanation: string;
    source_count: number;
    evidence: EvidenceReference[];
  }>;
  unique_insights: Array<{
    insight: string;
    why_it_matters: string;
    evidence: EvidenceReference[];
  }>;
  contradictions: Array<{
    topic: string;
    sides: Array<{ position: string; evidence: EvidenceReference[] }>;
    neutral_explanation: string;
    recommendation: string | null;
    recommendation_confidence: number | null;
  }>;
  resource_verdicts: Array<{
    resource_id: string;
    title: string;
    verdict:
      | "essential"
      | "use_selected_sections"
      | "reference_only"
      | "safe_to_skip"
      | "unavailable_or_low_confidence";
    reason: string;
    selected_sections: string[];
    evidence: EvidenceReference[];
  }>;
  merged_notes: Array<{
    topic: string;
    concise_notes: string[];
    syntax_or_pseudocode: string | null;
    recognition_clues: string[];
    common_mistakes: string[];
    memory_cues: string[];
    evidence: EvidenceReference[];
  }>;
  priority_problems: Array<{
    normalized_name: string;
    aliases: string[];
    priority: "must_do" | "useful" | "optional";
    reason: string;
    source_count: number;
    evidence: EvidenceReference[];
  }>;
}

export type OutputOption =
  | "complete_action_pack"
  | "quick_revision_notes"
  | "learning_workflow"
  | "voice_lesson"
  | "flashcards"
  | "priority_coding_problems"
  | "interview_revision_sheet";

export interface GeneratedAssetVersion {
  id: string;
  version_number: number;
  status: "generating" | "stored" | "failed";
  provider: string;
  model: string;
  mime_type: string;
  object_key: string | null;
  manifest_object_key: string | null;
  sha256: string | null;
  size_bytes: number | null;
  confidence: number | null;
  evaluation_summary: string | null;
  generation_time_ms: number | null;
  source_ids: string[];
  generation_settings: Record<string, unknown>;
  provenance: {
    classification: "source_derived" | "ai_generated" | "ai_inferred";
    resources: Array<{
      resource_id: string;
      title: string;
      link: string | null;
    }>;
    evidence_references: Array<Record<string, unknown>>;
    generation_timestamp: string;
    version_number: number;
  };
  genblaze_run_id: string | null;
  parent_version_number: number | null;
  failure_message: string | null;
  created_at: string;
  is_current: boolean;
  download_url: string | null;
}

export interface GeneratedAsset {
  id: string;
  action_pack_id: string;
  project_id: string;
  asset_type:
    | "complete_action_pack"
    | "note"
    | "learning_workflow"
    | "voice"
    | "flashcards"
    | "priority_problems"
    | "interview_revision_sheet";
  logical_key: string;
  display_name: string;
  current_version_number: number | null;
  created_at: string;
  updated_at: string;
  versions: GeneratedAssetVersion[];
}

export interface LearningWorkflowStage {
  stage_id: string;
  label: string;
  headline: string;
  summary: string;
  tone: "teal" | "blue" | "violet" | "amber" | "coral" | "green" | "navy";
  items: string[];
  evidence: Array<Record<string, unknown>>;
  estimated_minutes: number | null;
}

export interface LearningWorkflowAsset {
  schema_version: 1;
  action_pack_id: string;
  project_id: string;
  title: string;
  summary: string;
  mode: "guided" | "concise";
  focus_topics: string[];
  source_ids: string[];
  stages: LearningWorkflowStage[];
}

export interface ActionPackResponse {
  id: string;
  project_id: string;
  status: "completed";
  model: string;
  source_ids: string[];
  result_object_key: string;
  generated_at: string;
  action_pack: ActionPack;
  output_options: OutputOption[];
  assets: GeneratedAsset[];
}
