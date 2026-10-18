"""CI-only red/green native regression for the observed unhosted restart race."""
import os
from pathlib import Path
import subprocess

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("Native qualification runs only in GitHub Actions")
source = Path("experiments/direct-fabric/src/recovery.rs")
fixed = source.read_text()
cases = [
    ("unhosted_restart_survives_listener_starting_during_a_listen_round",
     "dec191bbea6c63967cfcf5073abd7acc052a3333"),
    ("staggered_hosted_recovery_cannot_lock_into_equal_role_windows",
     "74976716d132f493dbb62101aaca824e6e96584b"),
]
for name, revision in cases:
    start = fixed.index("    #[tokio::test]\n    async fn " + name)
    end = fixed.index("    #[tokio::test]", start + 20)
    regression = fixed[start:end]
    baseline = subprocess.check_output(["git", "show", revision + ":experiments/direct-fabric/src/recovery.rs"], text=True)
    index = baseline.rfind("\n}")
    command = ["cargo", "test", "--locked", "--manifest-path", "experiments/direct-fabric/Cargo.toml",
               "recovery::tests::" + name, "--", "--exact"]
    try:
        source.write_text(baseline[:index] + "\n" + regression + baseline[index:])
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        print(result.stdout)
        assert result.returncode != 0 and "1 failed" in result.stdout and name + " ... FAILED" in result.stdout, "Baseline must fail the behavioral regression, not compilation"
    finally:
        source.write_text(fixed)
    subprocess.run(command, check=True)
