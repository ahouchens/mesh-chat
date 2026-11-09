/** Preserve presentation fixture assertions while exercising explicit admission. */
export function admittedApiFixture<T extends Record<string, unknown>>(api: T): T {
  return Object.fromEntries(Object.entries(api).map(([name, operation]) => {
    if (!/^(coreApi.+|saveCallSettings|saveNetworkSettings|serviceCommand)$/.test(name)) return [name, operation];
    return [name, (...args: unknown[]) => {
      const admit = args.at(-1);
      if (typeof admit !== "function") return (operation as (...args: unknown[]) => unknown)(...args);
      const params = args.slice(0, -1);
      while (params.length && params.at(-1) === undefined) params.pop();
      return admit(() => (operation as (...args: unknown[]) => unknown)(...params));
    }];
  })) as T;
}
