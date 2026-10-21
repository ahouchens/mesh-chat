let lastDiagnostics = "";

export function rememberWebRTCDiagnostics(value: string): void {
  lastDiagnostics = value;
}

export function lastWebRTCDiagnostics(): string {
  return lastDiagnostics;
}
