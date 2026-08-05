const STORAGE_KEY = "omniagent.onboarding.v1";

type OnboardingState = {
  emptyStateSeen: boolean;
  suggestionsSeen: boolean;
};

const DEFAULT_STATE: OnboardingState = {
  emptyStateSeen: false,
  suggestionsSeen: false,
};

/** Reads localStorage lazily -- callers must only call this from an effect,
 * never during render, so SSR and hydration agree. Any parse failure (bad
 * JSON, a future shape change) is treated as "never seen" rather than
 * thrown, since onboarding state is a nice-to-have, not load-bearing. */
export function readOnboardingState(): OnboardingState {
  if (typeof window === "undefined") return DEFAULT_STATE;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_STATE;
    const parsed = JSON.parse(raw) as Partial<OnboardingState>;
    return { ...DEFAULT_STATE, ...parsed };
  } catch {
    return DEFAULT_STATE;
  }
}

export function writeOnboardingState(patch: Partial<OnboardingState>): OnboardingState {
  const next = { ...readOnboardingState(), ...patch };
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // Storage unavailable (private mode, quota) -- onboarding just
      // re-shows next time, which is a harmless degradation.
    }
  }
  return next;
}

export function resetOnboardingState(): OnboardingState {
  if (typeof window !== "undefined") {
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // Ignore -- see writeOnboardingState.
    }
  }
  return DEFAULT_STATE;
}

export type { OnboardingState };
