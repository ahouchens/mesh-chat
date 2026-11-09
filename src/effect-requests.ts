import { serviceCommand } from "./api";
import { effectIsCurrent, ProfileRetiredError, type CoreEffectScope, type CoreRequestAdmission } from "./core-admission";

export function requestEffect<T>(scope: CoreEffectScope, command: string, payload?: Record<string, unknown>, cleanup = false): Promise<T> {
  const admit = cleanup ? scope.admitCleanup ?? scope.admit : scope.admit;
  const check = () => (cleanup && scope.admitCleanup) || effectIsCurrent(scope);
  if (!check()) return Promise.reject(new ProfileRetiredError());
  if (admit || scope.isCurrent) {
    const guarded: CoreRequestAdmission = (request) => {
      if (!check()) return Promise.reject(new ProfileRetiredError());
      const invoke = () => check() ? request() : Promise.reject(new ProfileRetiredError());
      return admit ? admit(invoke) : invoke();
    };
    return serviceCommand<T>(command, payload, guarded);
  }
  return payload === undefined ? serviceCommand<T>(command) : serviceCommand<T>(command, payload);
}
