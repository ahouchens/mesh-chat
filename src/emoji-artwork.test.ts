import { describe, expect, it } from "vitest";

import { EMOJI_18_FULLY_QUALIFIED, EMOJI_18_FULLY_QUALIFIED_SIZE } from "./emoji-catalog";
import {
  TWEMOJI_ARTWORK_COMMIT,
  TWEMOJI_ARTWORK_GAPS,
  TWEMOJI_ARTWORK_VERSION,
  TWEMOJI_CURATED_SEQUENCES,
  TWEMOJI_GENERAL_SEQUENCES,
} from "./emoji-artwork.generated";
import { getEmojiArtwork, getEmojiFallbackName } from "./emoji-artwork";
import { ALL_REACTION_OPTIONS } from "./reactions";

describe("offline emoji artwork", () => {
  it("covers every curated picker choice with a local sprite", () => {
    expect(ALL_REACTION_OPTIONS).toHaveLength(253);
    expect(TWEMOJI_CURATED_SEQUENCES).toHaveLength(253);
    expect(TWEMOJI_CURATED_SEQUENCES).toEqual(ALL_REACTION_OPTIONS.map(({ emoji }) => emoji));

    for (const { emoji } of ALL_REACTION_OPTIONS) {
      const artwork = getEmojiArtwork(emoji);
      expect(artwork, emoji).not.toBeNull();
      expect(artwork?.src).toContain("/emoji/twemoji/17.0.3/curated.png");
      expect(artwork?.src, emoji).not.toMatch(/^https?:/);
    }
  });

  it("partitions the exact Emoji 18 catalog into artwork and named fallbacks", () => {
    let artworkCount = 0;
    let fallbackCount = 0;
    for (const emoji of EMOJI_18_FULLY_QUALIFIED) {
      const artwork = getEmojiArtwork(emoji);
      const fallback = getEmojiFallbackName(emoji);
      expect(Boolean(artwork) === Boolean(fallback), emoji).toBe(false);
      if (artwork) {
        artworkCount += 1;
        expect(artwork.src).not.toMatch(/^https?:/);
        expect(artwork.column).toBeGreaterThanOrEqual(0);
        expect(artwork.column).toBeLessThan(artwork.columns);
        expect(artwork.row).toBeGreaterThanOrEqual(0);
        expect(artwork.row).toBeLessThan(artwork.rows);
      } else {
        fallbackCount += 1;
        expect(fallback).toBeTruthy();
      }
    }

    expect(artworkCount).toBe(3944);
    expect(fallbackCount).toBe(19);
    expect(artworkCount + fallbackCount).toBe(EMOJI_18_FULLY_QUALIFIED_SIZE);
    expect(TWEMOJI_CURATED_SEQUENCES.length + TWEMOJI_GENERAL_SEQUENCES.length).toBe(3944);
  });

  it("pins the audited source and handles aliases and Emoji 18 gaps", () => {
    expect(TWEMOJI_ARTWORK_VERSION).toBe("17.0.3");
    expect(TWEMOJI_ARTWORK_COMMIT).toBe("b6b55fef1e8636b540a6d016a4729ca8cdf2e60b");
    expect(TWEMOJI_ARTWORK_GAPS).toHaveLength(19);
    expect(getEmojiArtwork("👁️‍🗨️")?.src).toContain("general-");
    expect(getEmojiFallbackName("🫫")).toBe("cracking face");
    expect(getEmojiFallbackName("🫹🏽")).toBe("leftwards thumb sign: medium skin tone");
    expect(getEmojiArtwork("not an emoji")).toBeNull();
    expect(getEmojiFallbackName("not an emoji")).toBeNull();
  });
});
