# Pinned component upgrade fixtures

Baseline is exact accepted source `174728edad62aae6ef16e95b075183d06c5cdda3`,
tree `239d041f87b26f50879008ac947481464dcf4551`, public API1.0. The script
rebuilds its actual service wheel and TypeScript0.2 tarball from `git archive`.
Python0.2 was carried inside that service wheel; it was never a standalone SDK
wheel. Candidate Python0.3.0.dev0 is the first standalone wheel. Candidate
TypeScript/Kotlin use0.3.0-experimental. All combinations remain unpublished
and experimental, with no supported upgrade window.

Prepare current SDK artifacts first, then:

```sh
python scripts/check_core_sdk_upgrade.py --output-dir dist/sdk-upgrade
MESH_CORE_SDK_ARTIFACTS="$PWD/dist/sdk" \
MESH_CORE_SDK_UPGRADE_ARTIFACTS="$PWD/dist/sdk-upgrade" \
MESH_CORE_CONSUMER_TMP="$RUNNER_TEMP" \
python -m pytest service/tests/connection/test_core_sdk_upgrade.py
```

Use Node22+ (`MESH_NODE` may select its exact executable) and installed local
TypeScript/type declarations. `--tsc`, `--type-roots`, `--npm-cli` override tool
locations. No dependency download or package publication occurs. CI must fetch
the pinned commit before `git archive`; missing source/artifacts fail. Use a
short writable temporary root on Windows for pip/npm caches. Consumers always
install outside the checkout; no source aliases or private runtime substitution.

The eight cases run actual installed old Python/TypeScript clients against
candidate Core; candidate installed clients against the pinned installed host
with composer rejected locally before any composer frame; and a copied actual
v1 vault upgraded through candidate Core. The latter preserves an old queued
message/receipt/draft, injects migration commit failure and verifies v1 remains
readable by actual old code, then commits format2, sends/replays the migrated
draft after reopen, and starts the actual pinned old VaultStore to prove format2
refusal before constructing its service. No monkeypatched schema maximum is used.
Only the pinned format-1 component's exact `Unsupported vault schema` failure
qualifies as that refusal. Wrong-key, corrupt-record and corrupt-database
negative controls fail instead. Fixture admission requires the exact baseline
tree and the two expected artifact names before verifying archive hashes.

Host fixtures suppress network startup only. Parser/session, cryptography,
SQLite transactions, domain message writes, outbox and receipt handling are
real. This is component evidence on WindowsAMD64/Python3.13.15/Node24.22.1;
it is not packaged Windows/Android transport or retained binary upgrade proof.
The retained Android baseline archive/run42644737670 remains a separate D/lead
fixture. Baseline Windows reports did not retain a binary, so a future binary
rebuild must remain labeled rebuilt rather than retained. `upgrade-artifacts.json`
records the actual rebuilt artifact hashes, source/tree and tool/platform tuple.
