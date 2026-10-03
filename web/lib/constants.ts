/* Static option lists shared by pages. */
export const PLATFORMS = [
  { value: "dramabox", label: "DramaBox" },
  { value: "reelshort", label: "ReelShort" },
  { value: "tiktok", label: "TikTok" },
  { value: "google", label: "Google" },
  { value: "youtube", label: "YouTube" },
];
export const PLATFORM_LABEL: Record<string, string> = { dramabox: "DramaBox", reelshort: "ReelShort", tiktok: "TikTok", google: "Google", youtube: "YouTube", local: "Notes" };

/** Drafting pace used for the segment/write mode hint (words per second of audio). */
export const WORDS_PER_SEC = 3.3;
