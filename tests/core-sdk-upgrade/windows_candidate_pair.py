"""Exact-artifact Windows candidate pair; a current-host check, not native upgrade."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
BASELINE = json.loads((ROOT / "tests/core-sdk-upgrade/fixtures.json").read_text())
VERSION_FIELDS = {
    "public_api_major": 1, "public_api_minor": 1, "internal_ipc": 1, "peer_wire": 1,
    "runtime": "0.9.66", "python": "0.3.0.dev0", "typescript": "0.3.0-experimental",
    "old_typescript": "0.2.0-experimental",
}
ARTIFACT_NAMES = {
    "runtime": "mesh-chat-service-x86_64-pc-windows-msvc.exe",
    "runtime_build": ".mesh-chat-service-x86_64-pc-windows-msvc.build.json",
    "python": "mesh_chat_core_client-0.3.0.dev0-py3-none-any.whl",
    "typescript": "mesh-chat-core-client-0.3.0-experimental.tgz",
    "old_typescript": "mesh-chat-core-client-0.2.0-experimental.tgz",
    "old_service": "mesh_chat_service-0.9.66-py3-none-any.whl",
    "sdk_staging": "core-sdk-staging.json",
    "old_staging": "upgrade-artifacts.json",
}
MAX_BYTES = {**dict.fromkeys(ARTIFACT_NAMES, 2 * 1024 * 1024), "runtime": 512 * 1024 * 1024}
LEVEL = "windows_installed_candidate_api_pair_current_normal_host"
CHECKS = {"major_refused_before_profile", "current_sdk_profile_created", "old_typescript_api_11",
          "python_same_identity", "reopened_same_identity", "old_typescript_after_reopen",
          "python_after_reopen", "efs_profile_directory", "efs_vault_file", "clean_host_exits"}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _artifact(base, record, name):
    if type(record) is not dict or set(record) != {"path", "sha256", "size_bytes"}:
        raise ValueError("Artifact manifest shape is invalid")
    relative = record["path"]
    if (type(relative) is not str or "\\" in relative or PurePosixPath(relative).is_absolute()
            or ".." in PurePosixPath(relative).parts or not relative
            or PurePosixPath(relative).name != ARTIFACT_NAMES[name]
            or type(record["sha256"]) is not str
            or re.fullmatch(r"[a-f0-9]{64}", record["sha256"]) is None
            or type(record["size_bytes"]) is not int
            or not 0 < record["size_bytes"] <= MAX_BYTES[name]):
        raise ValueError("Artifact manifest identity is invalid")
    path = base.joinpath(*PurePosixPath(relative).parts)
    if (not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(base)
            or path.stat().st_size != record["size_bytes"] or digest(path) != record["sha256"]):
        raise ValueError("Artifact bytes differ from manifest")
    return path


def validate_manifest(path, source, tree):
    """Bind explicit identities and actual bytes before installing or starting a host."""
    path = Path(path).resolve(strict=True)
    base = path.parent
    if not 0 < path.stat().st_size <= 16 * 1024:
        raise ValueError("Candidate manifest exceeds its bound")
    value = json.loads(path.read_text(encoding="utf-8"))
    fields = {"v", "source_commit", "source_tree", "baseline_source", "baseline_tree",
              "versions", "platform", "permissions", "artifacts", "baseline_native_binary"}
    if (type(value) is not dict or set(value) != fields or type(value["v"]) is not int or value["v"] != 1
            or value["source_commit"] != source or value["source_tree"] != tree
            or value["baseline_source"] != BASELINE["baseline_source"]
            or value["baseline_tree"] != BASELINE["baseline_tree"]
            or type(value["versions"]) is not dict or set(value["versions"]) != set(VERSION_FIELDS)
            or any(type(value["versions"][key]) is not type(expected)
                   or value["versions"][key] != expected for key, expected in VERSION_FIELDS.items())
            or value["platform"] != {"os": "Windows", "architecture": "AMD64"}
            or type(value["permissions"]) is not dict
            or set(value["permissions"]) != {"app_owned_normal_host", "dpapi_key", "efs_profile"}
            or any(value["permissions"][key] is not True for key in value["permissions"])
            or value["baseline_native_binary"] is not None
            or type(value["artifacts"]) is not dict
            or set(value["artifacts"]) != set(ARTIFACT_NAMES)):
        raise ValueError("Candidate pair manifest does not describe the declared source and scope")
    declared = json.loads((ROOT / "contracts/core-api/compatibility-v1.json").read_text())
    if (declared["public_api"] != {"major": 1, "minor": 1, "accepts_additive_minors": True}
            or declared["internal_ipc"]["version"] != 1 or declared["peer_wire"]["version"] != 1
            or declared["python_service"]["version"] != VERSION_FIELDS["runtime"]
            or declared["python_client"]["version"] != VERSION_FIELDS["python"]
            or declared["typescript_client"]["version"] != VERSION_FIELDS["typescript"]
            or declared["status"] != "experimental_unfrozen"):
        raise ValueError("Source compatibility declaration changed")
    artifacts = {name: _artifact(base, value["artifacts"][name], name) for name in ARTIFACT_NAMES}
    if artifacts["runtime"].parent != artifacts["runtime_build"].parent:
        raise ValueError("Runtime and exact build manifest are separated")
    staged = json.loads(artifacts["sdk_staging"].read_text(encoding="utf-8"))
    if (staged.get("passed") is not True or staged.get("source_commit") != source
            or staged.get("source_tree") != tree
            or staged.get("evidence_level") != "public_sdk_archive_and_isolated_import_staging"
            or staged.get("artifacts", {}).get("python", {}).get("sha256") != digest(artifacts["python"])
            or staged.get("artifacts", {}).get("typescript", {}).get("sha256") != digest(artifacts["typescript"])):
        raise ValueError("Candidate SDK staging is not source-bound")
    older = json.loads(artifacts["old_staging"].read_text(encoding="utf-8"))
    if (older.get("baseline_source") != BASELINE["baseline_source"]
            or older.get("baseline_tree") != BASELINE["baseline_tree"]
            or older.get("provenance") != BASELINE["provenance"]
            or older.get("artifacts", {}).get("typescript", {}).get("sha256") != digest(artifacts["old_typescript"])
            or older.get("artifacts", {}).get("python_service_carrier", {}).get("sha256") != digest(artifacts["old_service"])):
        raise ValueError("Pinned component artifacts are not bound to old source")
    return value, artifacts


PYTHON_CLIENT = r'''import json,sys
sys.path.insert(0,sys.argv[1])
from mesh_chat_core_client import CoreClient
from mesh_chat_core_client.windows import connect
expected=sys.stdin.readline().strip()
pipe=connect(sys.argv[2])
client=CoreClient.open(pipe.readline,pipe.write,pipe.close)
try:
 profile=client.capabilities["profiles"][0]
 view=client.request("profile.query",{"profile":profile})
 snap=client.application_snapshot()
 assert client.capabilities["api_major"]==1 and client.capabilities["api_minor"]==1
 assert view["destination"]==expected and snap["profile"]["destination"]==expected
 print(json.dumps({"passed":True}))
finally: client.close()
'''

OLD_TYPESCRIPT = r'''import {CoreClient} from '@mesh-chat/core-client';
import {connect} from 'node:net';
import {createInterface} from 'node:readline';
const input=createInterface({input:process.stdin});
const expected=(await input[Symbol.asyncIterator]().next()).value;
input.close();
const socket=connect(process.argv[2]);
await new Promise((yes,no)=>{socket.once('connect',yes);socket.once('error',no);});
const lines=createInterface({input:socket})[Symbol.asyncIterator]();
const transport={
  writeLine(line){return new Promise((yes,no)=>socket.write(line,error=>error?no(error):yes()));},
  async readLine(){const next=await lines.next();return next.done?null:next.value+'\n';},
  close(){socket.destroy();},
};
const client=await CoreClient.open(transport);
try {
 const profile=client.capabilities.profiles[0];
 const view=await client.request('profile.query',{profile});
 const snapshot=await client.request('application.snapshot',{});
 if(client.capabilities.api_major!==1||client.capabilities.api_minor!==1
    ||view.destination!==expected||snapshot.profile.destination!==expected)throw new Error();
 process.stdout.write(JSON.stringify({passed:true})+'\n');
}finally{client.close();}
'''

DRIVER = r'''import {CoreClient} from '@mesh-chat/core-client';
import {connectNamedPipe} from '@mesh-chat/core-client/node';
import {launchRuntime} from './runtime.mjs';
import {randomUUID} from 'node:crypto';
import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
const [runtimePath,dataDir,python,pythonSite,oldDir,node]=process.argv.slice(2);
let runtime,client,phase='first_start';
async function child(command,args,cwd,identity){
 const proc=spawn(command,args,{cwd,stdio:['pipe','pipe','ignore']});
 let output='';proc.stdout.on('data',part=>{output+=part; if(output.length>1024)proc.kill();});
 proc.stdin.end(identity+'\n');
 const timer=setTimeout(()=>proc.kill(),30000);
 const code=await new Promise((yes,no)=>{proc.once('exit',yes);proc.once('error',no);});
 clearTimeout(timer);
 if(code!==0||output.length>1024||JSON.parse(output).passed!==true)throw new Error('client_failed');
}
async function clients(pipe,identity){
 await child(python,['-I','-S','-B','-c',readFileSync('python_client.py','utf8'),pythonSite,pipe],process.cwd(),identity);
 await child(node,['old_client.mjs',pipe],oldDir,identity);
}
try{
 runtime=await launchRuntime(runtimePath,dataDir);
 phase='major_refusal';
 const invalid=await connectNamedPipe(runtime.pipe);
 await invalid.writeLine(JSON.stringify({api_version:2,request_id:'candidate:1',operation:'profile.create',
   params:{display_name:'Rejected'},idempotency_key:randomUUID()})+'\n');
 const refusal=JSON.parse(await invalid.readLine());invalid.close();
 if(refusal.ok!==false||refusal.error?.code!=='incompatible_version')throw new Error();
 phase='profile_create';
 client=await CoreClient.open(await connectNamedPipe(runtime.pipe));
 const before=await client.request('application.snapshot',{});
 if(before.profile!==null)throw new Error();
 const created=await client.request('profile.create',{display_name:'Candidate pair'},
   {idempotencyKey:randomUUID()});
 const profile=client.capabilities.profiles[0];
 const view=await client.request('profile.query',{profile});
 if(!created||typeof view.destination!=='string'||!view.destination)throw new Error();
 const identity=view.destination;
 phase='installed_clients';await clients(runtime.pipe,identity);
 client.close();client=null;await runtime.stop();runtime=null;
 phase='reopen';runtime=await launchRuntime(runtimePath,dataDir);
 client=await CoreClient.open(await connectNamedPipe(runtime.pipe));
 const reopened=await client.request('profile.query',{profile:client.capabilities.profiles[0]});
 if(reopened.destination!==identity)throw new Error();
 await clients(runtime.pipe,identity);
 client.close();client=null;await runtime.stop();runtime=null;
 process.stdout.write(JSON.stringify({passed:true,checks:{major_refused_before_profile:true,
   current_sdk_profile_created:true,old_typescript_api_11:true,python_same_identity:true,
   reopened_same_identity:true,old_typescript_after_reopen:true,python_after_reopen:true,
   clean_host_exits:2}})+'\n');
}catch{process.stdout.write(JSON.stringify({passed:false,phase})+'\n');process.exitCode=1;}
finally{try{client?.close();}catch{} try{await runtime?.stop();}catch{process.exitCode=1;}}
'''


def _install(command, *, cwd, env):
    subprocess.run(command, cwd=cwd, env=env, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=120)


def execute(manifest_path, expected_source):
    if sys.platform != "win32" or platform.machine() != "AMD64":
        raise RuntimeError("Candidate normal host requires Windows AMD64")
    sys.path.insert(0, str(ROOT / "scripts"))
    from native_windows_evidence import artifact_binding, require_unchanged
    from test_packaged_lifecycle import source_identity
    from stage_core_sdk import tools
    source, tree = source_identity(expected_source)
    manifest, artifacts = validate_manifest(manifest_path, source, tree)
    binary, binding = artifact_binding(source, artifacts["runtime"])
    if (binding["sidecar_sha256"] != manifest["artifacts"]["runtime"]["sha256"]
            or binding["build_manifest_sha256"] != manifest["artifacts"]["runtime_build"]["sha256"]):
        raise ValueError("Normal host build binding differs from manifest")
    node, npm = tools()
    parent = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()).resolve()
    work = Path(tempfile.mkdtemp(prefix="mesh-windows-candidate-pair-", dir=parent)).resolve()
    if work.parent != parent or work.is_relative_to(ROOT):
        raise ValueError("Candidate install must be outside checkout")
    env = {key: value for key, value in os.environ.items()
           if key.upper() not in {"PYTHONPATH", "PYTHONHOME", "NODE_PATH", "NODE_OPTIONS"}
           and not key.upper().startswith(("MESH_", "GITHUB_", "ACTIONS_", "INPUT_"))}
    env.update(PIP_CACHE_DIR=str(work / "pip-cache"), npm_config_cache=str(work / "npm-cache"),
               npm_config_update_notifier="false", PYTHONDONTWRITEBYTECODE="1")
    try:
        current, old, site = work / "current", work / "old", work / "python-site"
        current.mkdir(); old.mkdir(); site.mkdir()
        for directory, package in ((current, "typescript"), (old, "old_typescript")):
            (directory / "package.json").write_text('{"private":true,"type":"module"}')
            _install([node, npm, "install", str(artifacts[package]), "--offline", "--ignore-scripts",
                      "--no-audit", "--no-fund", "--package-lock=false"], cwd=directory, env=env)
        _install([sys.executable, "-m", "pip", "install", str(artifacts["python"]), "--target",
                  str(site), "--no-deps", "--no-index", "--no-compile"], cwd=work, env=env)
        for directory, version in ((current, VERSION_FIELDS["typescript"]), (old, VERSION_FIELDS["old_typescript"])):
            installed = json.loads((directory / "node_modules/@mesh-chat/core-client/package.json").read_text())
            if installed.get("version") != version:
                raise ValueError("Installed TypeScript package version changed")
        installed_python = site / "mesh_chat_core_client-0.3.0.dev0.dist-info/METADATA"
        if not installed_python.is_file() or "Version: 0.3.0.dev0" not in installed_python.read_text():
            raise ValueError("Installed Python wheel version changed")
        for name in ("runtime.mjs", "owner-pairing-diagnostic.mjs"):
            shutil.copyfile(ROOT / "examples/typescript-independent-consumer" / name, current / name)
        (current / "driver.mjs").write_text(DRIVER, encoding="utf-8")
        (current / "python_client.py").write_text(PYTHON_CLIENT, encoding="utf-8")
        (old / "old_client.mjs").write_text(OLD_TYPESCRIPT, encoding="utf-8")
        runtime = work / binary.name
        shutil.copy2(binary, runtime)
        if digest(runtime) != binding["sidecar_sha256"]:
            raise ValueError("Installed normal host changed")
        completed = subprocess.run([node, "driver.mjs", str(runtime), str(work / "app-data"),
                                    sys.executable, str(site), str(old), node], cwd=current, env=env,
                                   capture_output=True, timeout=180)
        if len(completed.stdout) > 4096 or len(completed.stderr) > 4096:
            raise ValueError("Candidate execution output exceeded its bound")
        observed = json.loads(completed.stdout)
        if (completed.returncode != 0 or type(observed) is not dict or set(observed) != {"passed", "checks"}
                or observed["passed"] is not True or type(observed["checks"]) is not dict
                or set(observed["checks"]) != CHECKS - {"efs_profile_directory", "efs_vault_file"}
                or any(value is not True for key, value in observed["checks"].items() if key != "clean_host_exits")
                or observed["checks"]["clean_host_exits"] != 2):
            raise ValueError("Installed candidate pair did not complete")
        profile = work / "app-data/mesh-core-runtime/profile-v1"
        for file in (profile, profile / "mesh-chat.vault"):
            if not file.is_file() and not file.is_dir():
                raise ValueError("Protected profile is missing")
            if not getattr(file.stat(), "st_file_attributes", 0) & 0x4000:
                raise ValueError("Normal host did not protect profile with EFS")
        require_unchanged(binary, binding)
        for name, path in artifacts.items():
            if digest(path) != manifest["artifacts"][name]["sha256"]:
                raise ValueError("Candidate artifact changed during execution")
        return {"v": 1, "passed": True, "source_commit": source, "source_tree": tree,
                "evidence_level": LEVEL, "scope": "Installed current normal Windows host, Python0.3/TypeScript0.3 and old TypeScript0.2 public clients; no old native binary or native upgrade, peer receipt, outbox or draft claim",
                "manifest_sha256": digest(Path(manifest_path)), "runtime_sha256": binding["sidecar_sha256"],
                "checks": {**observed["checks"], "efs_profile_directory": True, "efs_vault_file": True},
                "native_upgrade_qualified": False,
                "continuity": {"identity": "current_host_restart", "outbox": "not_exercised",
                               "draft": "not_exercised", "receipt": "not_exercised"}}
    finally:
        if work.parent != parent or not work.name.startswith("mesh-windows-candidate-pair-"):
            raise ValueError("Candidate cleanup ownership changed")
        target = str(work)
        if os.name == "nt":
            target = "\\\\?\\UNC\\" + target[2:] if target.startswith("\\\\") else "\\\\?\\" + target
        shutil.rmtree(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {"v": 1, "passed": False, "evidence_level": LEVEL}
    try:
        result = execute(args.manifest, args.expected_source)
    except Exception as error:
        result.update(failure_type=type(error).__name__)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "evidence_level": LEVEL}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
