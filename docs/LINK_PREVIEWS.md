# Links and embedded previews

Direct messages, groups, workspace channels, workspace direct messages and
threads share `MessageContent`. HTTP/HTTPS and www links are clickable. At most
three distinct preview cards appear per message; all links remain in the text.
Other websites show a destination card. This does not scrape arbitrary pages or
promise Open Graph previews for sites that prohibit browser-side access.

YouTube watch, short-link, Shorts, live and embed URLs support the provider's
inline player and optional start timestamps. X and legacy Twitter public-post
links support the provider's embedded post, including its media. Deleted,
private, age-restricted, region-blocked or embedding-disabled content may require
opening the provider or may remain unavailable.

No service is hosted or added. No third-party request is made just by displaying
a message. Loading a video or post explicitly contacts that provider, which can
observe the viewer's IP and request metadata. Closing the preview removes the
iframe and stops its playback. Message text and preview consent are unchanged on
the wire; consent is local to that mounted card and is not persisted.

Provider code runs only in cross-origin sandboxed frames. The app's script and
network policies remain restricted. Frame origins are allowlisted; arbitrary
message content cannot provide HTML, script, or an iframe origin. X resize
messages require the exact frame, provider origin and post ID, with bounded
dimensions. External links use the system browser, not the conversation WebView.

Provider references:
- [YouTube embeds](https://developers.google.com/youtube/player_parameters)
- [YouTube WebView identity and minimum player dimensions](https://developers.google.com/youtube/terms/required-minimum-functionality)
- [X embedded posts](https://help.x.com/en/using-x/how-to-embed-a-post)

The `?links` presentation fixture in `tests/connection-visual` uses production
components and synthetic chat messages. Browser checks can validate layout and
live public provider embeds without an app build. Packaged Windows and Android
testing is still needed, especially YouTube's WebView/referrer checks, external
browser opening, full screen and picture-in-picture. A browser preview is not
evidence of physical Android playback.

Local browser validation on 2026-10-29 rendered the public X post and YouTube
embed used in the fixture. After pressing Play, the YouTube video advanced past
five seconds with `paused=false`, `readyState=4` and no media error. At 393px,
the loaded previews had no horizontal overflow or page errors. These checks
used Edge in a development preview, not a packaged app.
