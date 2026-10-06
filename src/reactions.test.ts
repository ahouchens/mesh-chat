import { describe, expect, it } from "vitest";

import { EMOJI_18_FULLY_QUALIFIED, EMOJI_18_FULLY_QUALIFIED_SIZE } from "./emoji-catalog";
import { REACTION_CATEGORIES, validateSingleEmoji } from "./reactions";

describe("reaction emoji catalog and validation", () => {
  it("offers a broad catalog including useful farm reactions", () => {
    const options = REACTION_CATEGORIES.flatMap((category) => category.options);
    expect(new Set(options.map((option) => option.emoji)).size).toBeGreaterThan(150);
    for (const emoji of ["🧑‍🌾", "🌱", "🌻", "🐄", "🐓", "🍎", "🚀"]) {
      expect(options.some((option) => option.emoji === emoji)).toBe(true);
    }
  });

  it("accepts one bounded emoji sequence without depending on Intl.Segmenter", () => {
    const englandFlag = "\u{1F3F4}\u{E0067}\u{E0062}\u{E0065}\u{E006E}\u{E0067}\u{E007F}";
    for (const emoji of ["👍🏽", "🧑🏽‍🌾", "🇺🇸", "1️⃣", "❤️‍🔥", englandFlag]) {
      expect(validateSingleEmoji(emoji)).toEqual({ emoji, error: "" });
    }
  });

  it("pins the same 3,963 fully-qualified Emoji 18 sequences as the service", () => {
    expect(EMOJI_18_FULLY_QUALIFIED.size).toBe(EMOJI_18_FULLY_QUALIFIED_SIZE);
    expect(EMOJI_18_FULLY_QUALIFIED_SIZE).toBe(3963);
    let fingerprint = 0x811c9dc5;
    for (const byte of new TextEncoder().encode([...EMOJI_18_FULLY_QUALIFIED].join("\n"))) {
      fingerprint = Math.imul(fingerprint ^ byte, 0x01000193) >>> 0;
    }
    expect(fingerprint.toString(16)).toBe("f35d06e9");
    for (const emoji of EMOJI_18_FULLY_QUALIFIED) {
      expect(validateSingleEmoji(emoji)).toEqual({ emoji, error: "" });
    }
  });

  it("rejects text, multiple emoji, malformed UTF-16, and oversized input before dispatch", () => {
    expect(validateSingleEmoji("hello").error).not.toBe("");
    expect(validateSingleEmoji("😀😃").error).not.toBe("");
    expect(validateSingleEmoji("\uD83D").error).toBe("Enter one valid emoji.");
    expect(validateSingleEmoji(`😀${"\u0301".repeat(40)}`).error).toBe("That emoji sequence is too long.");
  });

  it("rejects non-fully-qualified and invented sequences accepted by broad regexes", () => {
    for (const emoji of [
      "❤", // unqualified red heart
      "☹", // minimally-qualified frown
      "🦰", // component, not a standalone fully-qualified emoji
      "😀‍🚀", // invented ZWJ sequence
      "👩‍🚀‍🌾", // concatenated professions
      "❤︎", // explicit text presentation
      "😀️", // redundant variation selector
    ]) {
      expect(validateSingleEmoji(emoji).error).not.toBe("");
    }
  });
});
