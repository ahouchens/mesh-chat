import { serviceCommand } from "./api";
import { effectIsCurrent, ProfileRetiredError, type CoreEffectScope } from "./core-admission";

export function requestEffect<T>(scope: CoreEffectScope, command: string, payload?: Record<string, unknown>, cleanup = false): Promise<T> {
  const admit = cleanup ? scope.admitCleanup ?? scope.admit : scope.admit;
  if ((!cleanup || !scope.admitCleanup) && !effectIsCurrent(scope)) return Promise.reject(new ProfileRetiredError());
  if (admit) return serviceCommand<T>(command, payload, admit);
  return payload === undefined ? serviceCommand<T>(command) : serviceCommand<T>(command, payload);
}
