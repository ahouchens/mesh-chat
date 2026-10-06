import {
  TWEMOJI_ARTWORK_GAPS,
  TWEMOJI_ARTWORK_VERSION,
  TWEMOJI_CURATED_COLUMNS,
  TWEMOJI_CURATED_ROWS,
  TWEMOJI_CURATED_SEQUENCES,
  TWEMOJI_GENERAL_COLUMNS,
  TWEMOJI_GENERAL_ROWS,
  TWEMOJI_GENERAL_SEQUENCES,
  TWEMOJI_GENERAL_SHEET_CAPACITY,
} from "./emoji-artwork.generated";

export type EmojiArtwork = {
  src: string;
  columns: number;
  rows: number;
  column: number;
  row: number;
};

const curatedIndex = new Map(TWEMOJI_CURATED_SEQUENCES.map((emoji, index) => [emoji, index]));
const generalIndex = new Map(TWEMOJI_GENERAL_SEQUENCES.map((emoji, index) => [emoji, index]));

function assetUrl(filename: string): string {
  const base = import.meta.env.BASE_URL.endsWith("/")
    ? import.meta.env.BASE_URL
    : `${import.meta.env.BASE_URL}/`;
  return `${base}emoji/twemoji/${TWEMOJI_ARTWORK_VERSION}/${filename}`;
}

export function getEmojiArtwork(emoji: string): EmojiArtwork | null {
  const curated = curatedIndex.get(emoji);
  if (curated !== undefined) {
    return {
      src: assetUrl("curated.png"),
      columns: TWEMOJI_CURATED_COLUMNS,
      rows: TWEMOJI_CURATED_ROWS,
      column: curated % TWEMOJI_CURATED_COLUMNS,
      row: Math.floor(curated / TWEMOJI_CURATED_COLUMNS),
    };
  }

  const general = generalIndex.get(emoji);
  if (general === undefined) return null;
  const position = general % TWEMOJI_GENERAL_SHEET_CAPACITY;
  return {
    src: assetUrl(`general-${Math.floor(general / TWEMOJI_GENERAL_SHEET_CAPACITY)}.png`),
    columns: TWEMOJI_GENERAL_COLUMNS,
    rows: TWEMOJI_GENERAL_ROWS,
    column: position % TWEMOJI_GENERAL_COLUMNS,
    row: Math.floor(position / TWEMOJI_GENERAL_COLUMNS),
  };
}

export function getEmojiFallbackName(emoji: string): string | null {
  return TWEMOJI_ARTWORK_GAPS.get(emoji) ?? null;
}
