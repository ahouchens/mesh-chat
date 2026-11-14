// Narrow admission and post-removal evidence for the installed private fixture.
import { randomUUID } from "node:crypto";
import { win32 as windowsPath } from "node:path";
import { HelperCoreError } from "./public-process-helper.mjs";

// Caller supplies a transport only after a successful OS pipe connection.
// The server may close it during the preface write or during Core negotiation.
export async function requireDeniedBeforeReply(transport, mode, preface, openCore, ClosedError) {
  let client;
  try {
    if (preface !== null) await transport.writeLine(preface);
    client = await openCore(transport);
  } catch (error) {
    if (!(error instanceof ClosedError) || transport.socket?.bytesRead !== 0) throw error;
    return {v: 1, mode, connected: true, closed_before_core_reply: true};
  } finally {
    try { client?.close(); } finally { transport.close(); }
  }
  throw new Error("negative_client_admitted");
}

export async function requireRevokedHelper(helper, profile, settings, deadline) {
  try {
    await helper.request("settings.update", {profile, settings}, deadline, randomUUID());
  } catch (error) {
    if (!(error instanceof HelperCoreError) || error.code !== "unauthenticated") {
      throw new Error("helper_revocation_not_proven");
    }
    await helper.closeInput(deadline); // Exit 0, no stderr, no malformed output.
    return;
  }
  throw new Error("removed_helper_mutated");
}

export function hostWitnessScript(hostPid, ownerPid, executable) {
  if (![hostPid, ownerPid].every(pid => Number.isSafeInteger(pid) && pid > 0 && pid <= 0xffffffff)
      || hostPid === ownerPid || !windowsPath.isAbsolute(executable)) throw new Error("host_witness_arguments");
  // Encode the expected executable as data; it never becomes PowerShell source.
  const expected = Buffer.from(windowsPath.resolve(executable), "utf16le").toString("base64");
  return `$ErrorActionPreference='Stop'; `
    + `$p=[System.Diagnostics.Process]::GetProcessById(${hostPid}); $null=$p.Handle; `
    + `$info=Get-CimInstance -ClassName Win32_Process -Filter 'ProcessId = ${hostPid}'; `
    + `$expected=[System.Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('${expected}')); `
    + `if ($null -eq $info -or $p.HasExited -or $info.ProcessId -ne ${hostPid} `
    + `-or $info.ParentProcessId -ne ${ownerPid} -or [string]::IsNullOrWhiteSpace($info.ExecutablePath) `
    + `-or ![System.StringComparer]::OrdinalIgnoreCase.Equals(`
    + `[System.IO.Path]::GetFullPath($info.ExecutablePath),[System.IO.Path]::GetFullPath($expected))) `
    + `{ 'MISMATCH'; exit 3 }; `
    + `'READY'; if ($p.WaitForExit(20000)) { 'EXIT' } else { 'LIVE' }`;
}
