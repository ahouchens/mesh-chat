/** UI lifetime admission at the final transport invocation; never Core authority. */
export type CoreRequestAdmission = <T>(request: () => Promise<T>) => Promise<T>;
export const admitCoreRequest: CoreRequestAdmission = (request) => request();

export class ProfileRetiredError extends Error {
  readonly code = "profile_changed";
  constructor() { super("The profile lifetime changed."); }
}
