# Architecture diagram

`overview.svg` is the editable source for the architecture image used in the
root README. `overview.png` is a 1500x1080 raster of the same drawing for
viewers that do not render SVG.

Regenerate the PNG after editing the SVG (Windows, Edge installed):

```powershell
$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$svg  = (Resolve-Path docs\architecture\overview.svg).Path
& $edge --headless --disable-gpu --hide-scrollbars `
  --window-size=1500,1080 `
  --screenshot="docs\architecture\overview.png" `
  ("file:///" + ($svg -replace '\\','/'))
```

The diagram separates the three reconnect responsibilities: the renderer owns
the fresh `RTCPeerConnection`, the Python service owns consent, signatures,
capability profiles, and replay, and the optional Cloudflare Worker owns only a
transient authenticated rendezvous. It also shows that the mailbox is not a
message store and that no background daemon is involved.
