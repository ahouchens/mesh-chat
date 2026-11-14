// Compare two bounded readbacks; this does not attest installation or upgrade.
import { lstatSync, readFileSync } from "node:fs";
import { compareReports } from "./windows_release_ui_contract.mjs";

function boundedReport(path) {
  const stat = lstatSync(path);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size < 1 || stat.size > 16 * 1024) {
    throw new Error("ui_report_invalid");
  }
  const data = readFileSync(path);
  if (data.length !== stat.size) throw new Error("ui_report_changed");
  return JSON.parse(data.toString("utf8"));
}

try {
  if (process.argv.length !== 6) throw new Error("ui_arguments_invalid");
  const before = boundedReport(process.argv[2]);
  const after = boundedReport(process.argv[3]);
  const reopened = boundedReport(process.argv[4]);
  process.stdout.write(JSON.stringify(compareReports(before, after, reopened, process.argv[5])) + "\n");
} catch {
  process.stdout.write(JSON.stringify({ v: 1, passed: false,
    evidence_level: "windows_release_ui_readback_comparison_only",
    failure_kind: "ui_reports_not_continuous" }) + "\n");
  process.exitCode = 1;
}
