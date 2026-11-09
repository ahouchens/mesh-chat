/** UI lifetime admission at the final transport invocation; never Core authority. */
export type CoreRequestAdmission = <T>(request: () => Promise<T>) => Promise<T>;
export const admitCoreRequest: CoreRequestAdmission = (request) => request();
