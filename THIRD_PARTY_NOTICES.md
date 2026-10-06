# Third-party notices

## Unicode Emoji data

Mesh Chat's reaction validator contains a generated, dependency-free index of
the fully-qualified emoji sequences in Unicode Emoji 18.0. The index is
derived from `emoji-test.txt` published by Unicode, Inc. at:

https://www.unicode.org/Public/18.0.0/emoji/emoji-test.txt

Source SHA-256:
`8F3735CDA1F92A779D78AF67CF86066BB1F07143DC22F2AC29394D9BC57AB21A`

### Unicode License V3

COPYRIGHT AND PERMISSION NOTICE

Copyright © 1991-2026 Unicode, Inc.

NOTICE TO USER: Carefully read the following legal agreement. BY
DOWNLOADING, INSTALLING, COPYING OR OTHERWISE USING DATA FILES, AND/OR
SOFTWARE, YOU UNEQUIVOCALLY ACCEPT, AND AGREE TO BE BOUND BY, ALL OF THE
TERMS AND CONDITIONS OF THIS AGREEMENT. IF YOU DO NOT AGREE, DO NOT
DOWNLOAD, INSTALL, COPY, DISTRIBUTE OR USE THE DATA FILES OR SOFTWARE.

Permission is hereby granted, free of charge, to any person obtaining a
copy of data files and any associated documentation (the "Data Files") or
software and any associated documentation (the "Software") to deal in the
Data Files or Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, and/or sell
copies of the Data Files or Software, and to permit persons to whom the
Data Files or Software are furnished to do so, provided that either (a)
this copyright and permission notice appear with all copies of the Data
Files or Software, or (b) this copyright and permission notice appear in
associated Documentation.

THE DATA FILES AND SOFTWARE ARE PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT OF
THIRD PARTY RIGHTS.

IN NO EVENT SHALL THE COPYRIGHT HOLDER OR HOLDERS INCLUDED IN THIS NOTICE
BE LIABLE FOR ANY CLAIM, OR ANY SPECIAL INDIRECT OR CONSEQUENTIAL DAMAGES,
OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS,
WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION,
ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THE DATA
FILES OR SOFTWARE.

Except as contained in this notice, the name of a copyright holder shall
not be used in advertising or otherwise to promote the sale, use or other
dealings in these Data Files or Software without prior written
authorization of the copyright holder.

## Twemoji artwork

Mesh Chat bundles a local, offline derivative of the Twemoji 17.0.3 graphics
from commit `b6b55fef1e8636b540a6d016a4729ca8cdf2e60b`:

https://github.com/jdecked/twemoji/releases/tag/v17.0.3

Copyright Twitter, Inc. and other contributors. Twemoji graphics are licensed
under the Creative Commons Attribution 4.0 International license (CC BY 4.0):

https://creativecommons.org/licenses/by/4.0/

Mesh Chat resizes, palette-optimizes, and combines the original 72-pixel PNG
files into local sprite sheets. The original Unicode sequence is still used for
storage and transport. The complete graphics license and pinned source metadata
are bundled at `emoji/twemoji/17.0.3/LICENSE-GRAPHICS.txt` and
`emoji/twemoji/17.0.3/ATTRIBUTION.txt` in the web assets. No Twemoji CDN or
other network service is contacted at runtime.
