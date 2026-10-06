import { EMOJI_18_FULLY_QUALIFIED } from "./emoji-catalog";

export type ReactionOption = {
  emoji: string;
  label: string;
  keywords?: string;
};

export type ReactionCategory = {
  id: string;
  label: string;
  icon: string;
  options: ReactionOption[];
};

export const QUICK_REACTION_OPTIONS: ReactionOption[] = [
  { emoji: "👍", label: "thumbs up", keywords: "like yes agree" },
  { emoji: "❤️", label: "heart", keywords: "love red" },
  { emoji: "😂", label: "laughing", keywords: "joy funny tears" },
  { emoji: "😮", label: "surprised", keywords: "wow open mouth" },
  { emoji: "😢", label: "sad", keywords: "cry tear" },
  { emoji: "🎉", label: "celebration", keywords: "party tada congratulations" },
];

export const REACTION_CATEGORIES: ReactionCategory[] = [
  {
    id: "smileys",
    label: "Smileys",
    icon: "😀",
    options: [
      ["😀", "grinning face"], ["😃", "happy face"], ["😄", "smiling face"], ["😁", "beaming face"],
      ["😆", "laughing squint"], ["😅", "smile with sweat"], ["🤣", "rolling with laughter"], ["😂", "laughing"],
      ["😊", "warm smile"], ["😇", "angel"], ["🙂", "slight smile"], ["🙃", "upside-down face"],
      ["😉", "wink"], ["🥰", "smiling with hearts"], ["😍", "heart eyes"], ["😘", "kiss"],
      ["😋", "yummy"], ["😛", "tongue out"], ["🤪", "zany face"], ["🤨", "raised eyebrow"],
      ["🧐", "monocle"], ["🤓", "nerd face"], ["😎", "sunglasses"], ["🤩", "star eyes"],
      ["🥳", "party face"], ["😏", "smirk"], ["😒", "unamused"], ["😔", "pensive"],
      ["😕", "confused"], ["🥺", "pleading face"], ["😢", "sad"], ["😭", "crying loudly"],
      ["😤", "triumph"], ["😠", "angry"], ["😡", "very angry"], ["🤯", "mind blown"],
      ["😳", "flushed"], ["😱", "screaming"], ["😨", "fearful"], ["😰", "anxious"],
      ["🤗", "hugging face"], ["🤔", "thinking"], ["🫣", "peeking"], ["🤭", "hand over mouth"],
      ["🫡", "saluting"], ["🤫", "quiet"], ["🫠", "melting face"], ["😶", "no mouth"],
      ["😐", "neutral face"], ["🫤", "diagonal mouth"], ["😬", "grimacing"], ["🙄", "eye roll"],
      ["😮", "surprised"], ["😴", "sleeping"], ["🤤", "drooling"], ["🤐", "zipper mouth"],
      ["🤢", "nauseated"], ["🤮", "sick"], ["🤧", "sneezing"], ["😷", "mask"],
    ].map(([emoji, label]) => ({ emoji, label })),
  },
  {
    id: "gestures",
    label: "People & gestures",
    icon: "👋",
    options: [
      ["👍", "thumbs up"], ["👎", "thumbs down"], ["👌", "OK hand"], ["🤌", "pinched fingers"],
      ["🤏", "pinching hand"], ["✌️", "victory hand"], ["🤞", "crossed fingers"], ["🫰", "finger heart"],
      ["🤟", "love-you gesture"], ["🤘", "rock on"], ["🤙", "call me"], ["👈", "point left"],
      ["👉", "point right"], ["👆", "point up"], ["👇", "point down"], ["☝️", "index pointing up"],
      ["✋", "raised hand"], ["🤚", "back of hand"], ["🖐️", "hand with fingers spread"], ["🖖", "Vulcan salute"],
      ["👋", "waving hand"], ["🤝", "handshake"], ["👏", "clapping"], ["🙌", "raised hands"],
      ["🫶", "heart hands"], ["👐", "open hands"], ["🤲", "palms up"], ["🙏", "folded hands"],
      ["✍️", "writing hand"], ["💪", "flexed biceps"], ["🦾", "mechanical arm"], ["👀", "eyes"],
    ].map(([emoji, label]) => ({ emoji, label })),
  },
  {
    id: "hearts",
    label: "Hearts",
    icon: "❤️",
    options: [
      ["❤️", "red heart"], ["🧡", "orange heart"], ["💛", "yellow heart"], ["💚", "green heart"],
      ["💙", "blue heart"], ["💜", "purple heart"], ["🖤", "black heart"], ["🤍", "white heart"],
      ["🤎", "brown heart"], ["💔", "broken heart"], ["❤️‍🔥", "heart on fire"], ["❤️‍🩹", "mending heart"],
      ["💕", "two hearts"], ["💞", "revolving hearts"], ["💓", "beating heart"], ["💗", "growing heart"],
      ["💖", "sparkling heart"], ["💘", "heart with arrow"], ["💝", "heart with ribbon"], ["❣️", "heart exclamation"],
    ].map(([emoji, label]) => ({ emoji, label })),
  },
  {
    id: "animals",
    label: "Animals",
    icon: "🐶",
    options: [
      ["🐶", "dog"], ["🐱", "cat"], ["🐭", "mouse"], ["🐹", "hamster"], ["🐰", "rabbit"],
      ["🦊", "fox"], ["🐻", "bear"], ["🐼", "panda"], ["🐨", "koala"], ["🐯", "tiger"],
      ["🦁", "lion"], ["🐮", "cow"], ["🐷", "pig"], ["🐸", "frog"], ["🐵", "monkey"],
      ["🙈", "see-no-evil monkey"], ["🙉", "hear-no-evil monkey"], ["🙊", "speak-no-evil monkey"],
      ["🐔", "chicken"], ["🐧", "penguin"], ["🐦", "bird"], ["🦆", "duck"], ["🦅", "eagle"],
      ["🦉", "owl"], ["🦋", "butterfly"], ["🐝", "bee"], ["🐞", "ladybug"], ["🐴", "horse"],
      ["🐄", "dairy cow"], ["🐓", "rooster chicken"], ["🐑", "sheep"], ["🐐", "goat"], ["🧑‍🌾", "farmer"],
    ].map(([emoji, label]) => ({ emoji, label })),
  },
  {
    id: "food",
    label: "Food & drink",
    icon: "🍕",
    options: [
      ["🍎", "apple"], ["🍊", "orange"], ["🍋", "lemon"], ["🍌", "banana"], ["🍉", "watermelon"],
      ["🍇", "grapes"], ["🍓", "strawberry"], ["🫐", "blueberries"], ["🍒", "cherries"], ["🍑", "peach"],
      ["🥭", "mango"], ["🍍", "pineapple"], ["🥥", "coconut"], ["🥝", "kiwi"], ["🍅", "tomato"],
      ["🥑", "avocado"], ["🍕", "pizza"], ["🍔", "hamburger"], ["🍟", "fries"], ["🌮", "taco"],
      ["🌯", "burrito"], ["🍣", "sushi"], ["🍿", "popcorn"], ["🎂", "birthday cake"], ["🍪", "cookie"],
      ["☕", "coffee"], ["🍺", "beer"], ["🥂", "cheers"],
    ].map(([emoji, label]) => ({ emoji, label })),
  },
  {
    id: "activities",
    label: "Activities",
    icon: "⚽",
    options: [
      ["⚽", "soccer ball"], ["🏀", "basketball"], ["🏈", "football"], ["⚾", "baseball"], ["🎾", "tennis"],
      ["🏐", "volleyball"], ["🏉", "rugby"], ["🎱", "pool ball"], ["🏓", "table tennis"], ["🏸", "badminton"],
      ["🥅", "goal net"], ["⛳", "golf"], ["🎣", "fishing"], ["🥊", "boxing glove"], ["🎮", "video game"],
      ["🎲", "dice"], ["🧩", "puzzle"], ["🎨", "art palette"], ["🎵", "music"], ["🎸", "guitar"],
      ["🎉", "celebration"], ["🎊", "confetti"], ["🏆", "trophy"], ["🥇", "gold medal"],
    ].map(([emoji, label]) => ({ emoji, label })),
  },
  {
    id: "nature",
    label: "Nature & travel",
    icon: "🌈",
    options: [
      ["☀️", "sun"], ["🌤️", "sun behind cloud"], ["⛈️", "thunderstorm"], ["❄️", "snowflake"], ["☃️", "snowman"],
      ["🌈", "rainbow"], ["🔥", "fire"], ["💧", "water drop"], ["🌊", "wave"], ["🌸", "cherry blossom"],
      ["🌹", "rose"], ["🌻", "sunflower"], ["🌱", "seedling"], ["🌲", "evergreen tree"], ["🌎", "earth"],
      ["🌙", "moon"], ["⭐", "star"], ["✨", "sparkles"], ["⚡", "lightning"], ["🚗", "car"],
      ["🚕", "taxi"], ["🚌", "bus"], ["🚲", "bicycle"], ["✈️", "airplane"], ["🚀", "rocket"],
      ["🛸", "flying saucer"], ["🏠", "house"], ["🏕️", "camping"],
    ].map(([emoji, label]) => ({ emoji, label })),
  },
  {
    id: "symbols",
    label: "Objects & symbols",
    icon: "✅",
    options: [
      ["✅", "check mark"], ["❌", "cross mark"], ["⚠️", "warning"], ["❗", "exclamation"], ["❓", "question"],
      ["💯", "hundred points"], ["💥", "collision"], ["💫", "dizzy"], ["💬", "speech bubble"], ["💭", "thought bubble"],
      ["💤", "sleep"], ["🎁", "gift"], ["💡", "light bulb"], ["📌", "pushpin"], ["📣", "megaphone"],
      ["🔔", "bell"], ["🔒", "lock"], ["🔑", "key"], ["🛠️", "tools"], ["📅", "calendar"],
      ["📍", "location pin"], ["➕", "plus"], ["➖", "minus"], ["♻️", "recycling"], ["✔️", "check"],
      ["☑️", "checked box"], ["🆗", "OK button"], ["🆘", "SOS"],
    ].map(([emoji, label]) => ({ emoji, label })),
  },
];

export const ALL_REACTION_OPTIONS = (() => {
  const options = new Map<string, ReactionOption>();
  for (const option of [...QUICK_REACTION_OPTIONS, ...REACTION_CATEGORIES.flatMap((category) => category.options)]) {
    if (!options.has(option.emoji)) options.set(option.emoji, option);
  }
  return [...options.values()];
})();

export const REACTION_OPTION_BY_EMOJI = new Map(ALL_REACTION_OPTIONS.map((option) => [option.emoji, option]));

export function validateSingleEmoji(value: string): { emoji: string; error: string } {
  const emoji = value.trim();
  for (let index = 0; index < emoji.length; index += 1) {
    const unit = emoji.charCodeAt(index);
    if (unit >= 0xD800 && unit <= 0xDBFF) {
      const next = emoji.charCodeAt(index + 1);
      if (!(next >= 0xDC00 && next <= 0xDFFF)) return { emoji, error: "Enter one valid emoji." };
      index += 1;
    } else if (unit >= 0xDC00 && unit <= 0xDFFF) {
      return { emoji, error: "Enter one valid emoji." };
    }
  }
  if ([...emoji].length > 16 || new TextEncoder().encode(emoji).length > 64) {
    return { emoji, error: "That emoji sequence is too long." };
  }
  if (!EMOJI_18_FULLY_QUALIFIED.has(emoji)) {
    return { emoji, error: "Enter one supported emoji from your keyboard." };
  }
  return { emoji, error: "" };
}
