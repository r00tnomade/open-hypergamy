export type StepId =
  | "welcome"
  | "profile"
  | "opportunities"
  | "matching"
  | "notifications"
  | "ai"
  | "review";

export type Option<T = string> = { id: T; label: string };
export type CategoryOption = Option & { hint: string };

export type Catalog = {
  interests: Option[];
  fields: Option[];
  skills: Option[];
  degrees: Option[];
  institution_types: Option[];
  categories: CategoryOption[];
  regions: Option[];
  formats: Option[];
  countries: Option[];
  weekdays: Option<number>[];
  reminder_offsets: number[];
  timezones: string[];
};

export type SecretSource = "environment" | "keychain" | "unset";

export type ProfileData = {
  display_name: string | null;
  degree_level: string | null;
  current_year: number | null;
  expected_graduation_year: number | null;
  institution: string | null;
  institution_type: string;
  country: string;
  subject_tags: string[];
  research_tags: string[];
  skills: string[];
  everything: boolean;
  categories: string[];
  regions: string[];
  formats: string[];
  international_when_funded: boolean;
  needs_funding_or_low_cost: boolean;
  budget_limit_eur: number | null;
};

export type TelegramSettings = {
  enabled: boolean;
  digest_enabled: boolean;
  digest_weekday: number;
  digest_time: string;
  deadline_offsets_days: number[];
  minimum_fit_score_for_immediate_alert: number;
};

export type Onboarding = {
  steps: Partial<Record<StepId, "done" | "skipped">>;
  current_step: StepId;
  drafts: Record<string, Record<string, unknown>>;
  completed: boolean;
  completed_at: string | null;
  existing_install: boolean;
};

export type Snapshot = {
  version: string;
  catalog: Catalog;
  steps: StepId[];
  optional_steps: StepId[];
  llm_checklist: string;
  config_error: string | null;
  recoverable?: boolean;
  initialized?: boolean;
  onboarding: Onboarding;
  profile?: ProfileData | null;
  profile_problem?: string | null;
  settings?: {
    editable: boolean;
    timezone: string;
    telegram: TelegramSettings;
    llm: { enabled: boolean; effective: boolean; provider: string; model: string; base_url: string };
  };
  secrets?: {
    keychain_available: boolean;
    telegram_token: SecretSource;
    telegram_chat: SecretSource;
    llm_api_key: SecretSource;
  };
  llm_ack?: boolean;
};

export type Example = {
  title: string;
  category: string;
  location: string;
  fit: number;
  components: Record<string, number>;
  urgency: number;
  days_left: number | null;
  band: string;
  action: string;
  matched_interests: string[];
  reasons: string[];
  eligibility: {
    status: string;
    label: string;
    criteria: { text: string; assessment: string; why: string }[];
  };
  certainty: { level: "higher" | "medium" | "lower"; why: string };
};

export type LlmStatus = {
  enabled: boolean;
  effective: boolean;
  provider: string;
  model: string;
  base_url: string;
  acknowledged: boolean;
  api_key: SecretSource | "not_needed";
  reachable: boolean;
  model_listed: boolean | null;
  error?: string;
};

export type Summary = {
  profile: {
    name: string | null;
    degree_level: string;
    country: string;
    interests: number;
    subjects: number;
  } | null;
  profile_problem: string | null;
  categories: string[];
  everything: boolean;
  telegram: { enabled: boolean; connected: boolean; digest: boolean };
  ai: { enabled: boolean; effective: boolean; acknowledged: boolean; provider: string };
  sources: {
    target: number;
    configured: number;
    enabled: number;
    healthy_30d: number;
    review_required: number;
  } | null;
  todo: string[];
};
