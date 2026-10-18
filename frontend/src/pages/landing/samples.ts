import type { Department } from "@/types";

export interface SampleReport {
  text: string;
  language: string;
  department: Department;
  severity: number;
}

/** Synthetic examples in the five demo languages (no real callers). */
export const SAMPLE_REPORTS: SampleReport[] = [
  { text: "Sector 18 metro pe building mein aag lagi hai", language: "Hinglish", department: "fire", severity: 5 },
  { text: "घरों में पानी घुस गया, लोग छत पर फंसे हैं", language: "Hindi", department: "disaster", severity: 5 },
  { text: "அப்பாவுக்கு நெஞ்சு வலி அதிகம், ஆம்புலன்ஸ் வேண்டும்", language: "Tamil", department: "medical", severity: 5 },
  { text: "বিদ্যুতের তার জলে পড়েছে", language: "Bengali", department: "utilities", severity: 4 },
  { text: "Two men fighting with knives near Atta market", language: "English", department: "police", severity: 4 },
  { text: "gas ki tez smell aa rahi, log chakkar kha rahe", language: "Hinglish", department: "fire", severity: 4 },
  { text: "Underpass flooded, a bus is stuck inside", language: "English", department: "disaster", severity: 4 },
  { text: "बच्चा सीढ़ियों से गिर गया, सिर में चोट", language: "Hindi", department: "medical", severity: 4 },
];

export const HERO_PHRASES = ["आग लगी है!", "Fire on 3rd floor", "தீ பிடித்துள்ளது", "আগুন লেগেছে", "aag lagi hai"];
