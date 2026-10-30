# Links and embedded previews

Direct messages, groups, workspace channels, workspace direct messages and
threads share `MessageContent`. HTTP/HTTPS and www links are clickable. At most
three distinct preview cards appear per message; all links remain in the text.
Other websites show a destination card. This does not scrape arbitrary pages or
promise Open Graph previews for sites that prohibit browser-side access.

`Load preview` requests a native card first: YouTube title, creator and thumbnail,
or X author and plain-text post excerpt from the provider's public oEmbed API.
Cards render locally and remain visible if an interactive embed fails. The
optional `Try playing here` / `Try interactive post` action loads the provider's
iframe separately. Hiding the player stops playback and keeps the card. `Open`
always opens the original URL externally. YouTube timestamps are preserved.
Deleted, private, age-restricted, region-blocked or embedding-disabled content
may require opening the provider or may remain unavailable. A metadata failure
shows an explicit unavailable message without disabling the link.

No service is hosted or added. No third-party request is made just by displaying
a message. Loading a preview explicitly contacts that provider (and YouTube's
thumbnail host), which can observe the viewer's IP and request metadata. The
existing native Python service makes these requests on the viewer's device;
there is no hosted unfurling proxy, scraping service, or API key. Closing the preview removes the
iframe and stops its playback. Message text and preview consent are unchanged on
the wire; consent is local to that mounted card and is not persisted. Fetches
already in flight may finish after closing. Results are cached only in service
memory for five minutes (15 seconds for failures), with at most 32 entries.

The `link_preview` service command only accepts an allowlisted provider and a
validated post/video ID. It returns immediately while at most two background
workers fetch data; it never waits for HTTP while holding the messaging dispatch
lock. Frontend polling stops after 15 seconds, closing, unmounting or editing.
The command does not persist preview responses in the vault's command cache.
HTTP has a three-second socket timeout, bounded response sizes and no redirects.
Endpoints and thumbnail URLs are constructed locally; provider-supplied URLs
cannot choose a request destination. YouTube thumbnails are returned as bounded
JPEG data URLs. X fallback HTML is parsed into text, never rendered or executed.

Provider code runs only in cross-origin sandboxed frames. The app's script and
network policies remain restricted. Frame origins are allowlisted; arbitrary
message content cannot provide HTML, script, or an iframe origin. X resize
messages require the exact frame, provider origin and post ID, with bounded
dimensions. External links use the system browser, not the conversation WebView.

Provider references:
- [YouTube embeds](https://developers.google.com/youtube/player_parameters)
- [YouTube WebView identity and minimum player dimensions](https://developers.google.com/youtube/terms/required-minimum-functionality)
- [X embedded posts](https://help.x.com/en/using-x/how-to-embed-a-post)
- [X oEmbed and fallback markup](https://docs.x.com/x-for-websites/oembed-api)

The `?links` presentation fixture in `tests/connection-visual` uses production
components, synthetic chat messages and deterministic card data. Browser checks can validate layout and
live public provider embeds without an app build. Packaged Windows and Android
testing is still needed, especially YouTube's WebView/referrer checks, external
browser opening, full screen and picture-in-picture. A browser preview is not
evidence of physical Android playback. In particular, YouTube requires a valid
HTTP Referer/app identity for its player. This card fallback does not change
native WebView identity handling or bypass provider restrictions.

Local browser validation on 2026-10-29 rendered the public X post and YouTube
embed used in the fixture. After pressing Play, the YouTube video advanced past
five seconds with `paused=false`, `readyState=4` and no media error. At 393px,
the loaded previews had no horizontal overflow or page errors. These checks
used Edge in a development preview, not a packaged app.

The subsequent card fallback smoke test fetched the public YouTube sample's
title, author and JPEG thumbnail, and the public X sample's author and post text,
using the production Python fetcher. Regression tests exercise consent, provider
failure, late responses, closing/poll cancellation, plaintext rendering,
redirect/URL restrictions, bounded concurrency and both mobile/desktop dispatch.
