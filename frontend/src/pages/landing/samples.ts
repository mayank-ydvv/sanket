import type { Department } from "@/types";
import type { MessageKey } from "@/lib/messages";

export interface SampleReport {
  text: string;
  english: string | null; // what the dispatcher sees under a non-English report
  language: MessageKey;
  department: Department;
  severity: number;
}

/** Synthetic Chennai examples in the five demo languages (no real callers). */
export const SAMPLE_REPORTS: SampleReport[] = [
  { text: "முடிச்சூரில் வீடுகளுக்குள் தண்ணீர் புகுந்தது, மக்கள் மாடியில் சிக்கியுள்ளனர்", english: "Water has entered the houses in Mudichur, people are stuck upstairs", language: "lang.ta", department: "disaster", severity: 5 },
  { text: "Marina beach pe building mein aag lagi hai", english: "A building near Marina beach is on fire", language: "lang.hinglish", department: "fire", severity: 5 },
  { text: "அப்பாவுக்கு நெஞ்சு வலி அதிகம், ஆம்புலன்ஸ் வேண்டும்", english: "Father has severe chest pain, we need an ambulance", language: "lang.ta", department: "medical", severity: 5 },
  { text: "बच्चा सीढ़ियों से गिर गया, सिर में चोट, Egmore", english: "A child fell down the stairs with a head injury, Egmore", language: "lang.hi", department: "medical", severity: 4 },
  { text: "Two men fighting with knives near Pondy Bazaar", english: null, language: "lang.en", department: "police", severity: 4 },
  { text: "சைதாப்பேட்டையில் மின்கம்பி தண்ணீரில் விழுந்துள்ளது", english: "A power line has fallen into the water in Saidapet", language: "lang.ta", department: "utilities", severity: 4 },
  { text: "Ganesapuram subway flooded, a bus is stuck inside", english: null, language: "lang.en", department: "disaster", severity: 4 },
  { text: "বিদ্যুতের তার জলে পড়েছে, Adyar bridge", english: "An electric wire has fallen into the water, Adyar bridge", language: "lang.bn", department: "utilities", severity: 4 },
];

export const HERO_PHRASES = ["தீ பிடித்துள்ளது", "Fire on 3rd floor", "வெள்ளம் வந்துவிட்டது", "आग लगी है!", "aag lagi hai"];
