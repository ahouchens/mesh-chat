# Published 0.9.66 release byte intake

`scripts/stage_core_release_baseline.py` checks explicitly supplied local
release files. It reads no network data and installs nothing. Supply the retained
public release metadata snapshot and a directory containing exactly these four
files: `Mesh-Chat_0.9.66_x64-setup.exe`,
`Mesh-Chat_0.9.66_x64_en-US.msi`,
`mesh-chat-0.9.66-android-arm64-release.apk`, and `SHA256SUMS.txt`.

```sh
python scripts/stage_core_release_baseline.py \
  --release-metadata tests/core-release-upgrade/release-metadata.json \
  --assets-dir <local-release-assets-directory> \
  --output <retained-report.json>
```

The validator requires the annotated `v0.9.66` tag object
`964848e68ed54ceffcbbb8b4a2355f46995e2efa`, source commit
`7c40f7b23eab3e9d83ff7ca1075c90c4d84ce516`, and tree
`96daefa74c38a5cfd7863e37e3effcb7a06dc6cd`. The pinned metadata
snapshot hashes to
`3543c26f91da885de97cd7389185e637abbf35e99863ccb1bc3d98f344685981`;
its retained checksum text hashes to
`6306c25b130e10287b857829a29a6ea9b4dbfa27acaa9c1a25550e95345410a4`.
The script checks release and asset IDs, sizes, SHA-256 digests, exact directory
inventory, and the checksum text. A failed input produces a bounded failure
report without private local paths.

The old SDK component rebuild fixture in `tests/core-sdk-upgrade/` remains
separate. Its source commit is
`174728edad62aae6ef16e95b075183d06c5cdda3` and cannot qualify as
the published release source. A passing byte intake reports only
`published_release_byte_intake_only`. It establishes no native upgrade,
installed Windows/Android pair, physical-device identity, or support window.
The committed metadata is a retained snapshot of the public release record;
the binaries themselves must be supplied locally for any passing intake.
