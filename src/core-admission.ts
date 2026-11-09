/** UI lifetime admission at the final transport invocation; never Core authority. */
export type CoreRequestAdmission = <T>(request: () => Promise<T>) => Promise<T>;
export const admitCoreRequest: CoreRequestAdmission = (request) => request();

/** A renderer owner's lifetime, not native authority or retirement proof. */
export interface CoreEffectScope {
  readonly admit?: CoreRequestAdmission;
  readonly admitCleanup?: CoreRequestAdmission;
  readonly isCurrent?: () => boolean;
}

export function captureEffectScope(scope: CoreEffectScope = {}): CoreEffectScope {
  return Object.freeze({ admit: scope.admit, admitCleanup: scope.admitCleanup, isCurrent: scope.isCurrent });
}

export function effectIsCurrent(scope: CoreEffectScope = {}): boolean {
  return scope.isCurrent?.() !== false;
}

export class ProfileRetiredError extends Error {
  readonly code = "profile_changed";
  constructor() { super("The profile lifetime changed."); }
}
