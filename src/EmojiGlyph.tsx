import { useState } from "react";

import { getEmojiArtwork, getEmojiFallbackName } from "./emoji-artwork";

export type EmojiGlyphProps = {
  emoji: string;
  className?: string;
  /** Current reaction buttons provide their own complete accessible names. */
  decorative?: boolean;
  /** Required by callers using a non-decorative glyph; catalog name is the fallback. */
  label?: string;
};

function artworkKey(emoji: string, artwork: NonNullable<ReturnType<typeof getEmojiArtwork>>): string {
  return `${emoji}|${artwork.src}|${artwork.columns}|${artwork.rows}|${artwork.column}|${artwork.row}`;
}

export function EmojiGlyph({ emoji, className = "", decorative = true, label }: EmojiGlyphProps) {
  const artwork = getEmojiArtwork(emoji);
  const fallbackName = getEmojiFallbackName(emoji);
  const key = artwork ? artworkKey(emoji, artwork) : "";
  const [loadedKey, setLoadedKey] = useState("");
  const [failedKey, setFailedKey] = useState("");
  const loaded = Boolean(artwork && loadedKey === key && failedKey !== key);
  const canLoad = Boolean(artwork && failedKey !== key);
  const accessibleName = label ?? fallbackName ?? "Emoji";

  return (
    <span
      className={`emoji-glyph ${loaded ? "emoji-glyph--loaded" : "emoji-glyph--fallback"}${className ? ` ${className}` : ""}`}
      aria-hidden={decorative ? true : undefined}
      aria-label={decorative ? undefined : accessibleName}
      role={decorative ? undefined : "img"}
      data-emoji={emoji}
      data-emoji-name={fallbackName ?? undefined}
      data-artwork-state={loaded ? "loaded" : artwork && failedKey === key ? "error" : artwork ? "loading" : "missing"}
    >
      <span className="emoji-glyph__fallback" aria-hidden="true">18</span>
      {artwork && canLoad && (
        <img
          className="emoji-glyph__sprite"
          src={artwork.src}
          alt=""
          aria-hidden="true"
          draggable={false}
          decoding="async"
          style={{
            width: `${artwork.columns * 100}%`,
            height: `${artwork.rows * 100}%`,
            left: `${artwork.column * -100}%`,
            top: `${artwork.row * -100}%`,
          }}
          onLoad={() => setLoadedKey(key)}
          onError={() => setFailedKey(key)}
        />
      )}
    </span>
  );
}
