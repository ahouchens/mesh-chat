import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { EmojiGlyph } from "./EmojiGlyph";

afterEach(cleanup);

describe("EmojiGlyph", () => {
  it("uses a stable neutral tile until bundled artwork loads", () => {
    const { container } = render(<EmojiGlyph emoji="🫠" />);
    const glyph = container.querySelector<HTMLElement>('[data-emoji="🫠"]');
    const image = glyph?.querySelector("img");

    expect(glyph?.dataset.artworkState).toBe("loading");
    expect(glyph?.textContent).toBe("18");
    expect(glyph?.getAttribute("aria-hidden")).toBe("true");
    expect(image?.getAttribute("alt")).toBe("");
    expect(image?.getAttribute("aria-hidden")).toBe("true");
    expect(image?.getAttribute("src")).toMatch(/^\.?\/emoji\/twemoji\/17\.0\.3\//);
    expect(parseFloat(image?.style.width ?? "0")).toBeGreaterThan(100);

    fireEvent.load(image as HTMLImageElement);
    expect(glyph?.dataset.artworkState).toBe("loaded");
    expect(glyph?.textContent).toBe("18");
  });

  it("keeps the neutral tile and removes a failed image", () => {
    const { container } = render(<EmojiGlyph emoji="🫠" />);
    const glyph = container.querySelector<HTMLElement>('[data-emoji="🫠"]');
    fireEvent.error(glyph?.querySelector("img") as HTMLImageElement);

    expect(glyph?.dataset.artworkState).toBe("error");
    expect(glyph?.querySelector("img")).toBeNull();
    expect(glyph?.textContent).toBe("18");
    expect(glyph?.textContent).not.toContain("🫠");
  });

  it("uses the same neutral tile when Twemoji has no artwork", () => {
    const { container } = render(<EmojiGlyph emoji="🫫" />);
    const glyph = container.querySelector<HTMLElement>('[data-emoji="🫫"]');

    expect(glyph?.dataset.artworkState).toBe("missing");
    expect(glyph?.querySelector("img")).toBeNull();
    expect(glyph?.textContent).toBe("18");
    expect(glyph?.dataset.emojiName).toBeTruthy();
  });

  it("can expose one semantic image name when used outside a labelled control", () => {
    render(<EmojiGlyph emoji="🫠" decorative={false} label="Melting face" />);
    expect(screen.getByRole("img", { name: "Melting face" })).toBeTruthy();
  });
});
