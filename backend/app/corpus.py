"""Synthetic report corpus for the five demo languages. All content is invented.

Emergencies are compositional: an *event* phrase (department + severity) is placed
into a sentence *frame*, then a place is filled into ``{loc}``. Non-urgent reports
and pranks are whole templates. The generator holds out every third event /
template per language for the test split, so test phrasings are never trained on.
"""

import random
from typing import NamedTuple

Language = str  # "en" | "hinglish" | "hi" | "ta" | "bn"
LANGUAGES: tuple[Language, ...] = ("en", "hinglish", "hi", "ta", "bn")
LATIN_LANGUAGES = frozenset({"en", "hinglish"})
DEPARTMENTS: tuple[str, ...] = ("fire", "police", "medical", "disaster", "utilities")


class Event(NamedTuple):
    severity: int
    text: str


class Template(NamedTuple):
    department: str
    severity: int
    text: str


class HardCase(NamedTuple):
    language: Language
    text: str
    is_emergency: bool
    department: str
    severity: int
    location_text: str | None
    tag: str  # sarcasm | keyword_trap | silent_sos | same_event | implicit


LOCATIONS: tuple[str, ...] = (
    "Sector 18 metro",
    "Sector 62",
    "Atta market",
    "Botanical Garden metro",
    "Sector 15 gurudwara",
    "Gaur City 2",
    "Sector 137",
    "Pari Chowk",
    "Rajendra Nagar Shiv mandir",
    "Sector 50 park",
    "Sector 76",
    "Film City",
    "Sector 22 market",
    "Sector 93 expressway",
    "Sector 104 crossing",
    "Kalindi Kunj bridge",
    "Sector 12 market",
    "Mamura chowk",
)

# Noun phrases, so they read naturally inside any frame.
VAGUE_LOCATIONS: dict[Language, tuple[str, ...]] = {
    "en": ("the petrol pump behind the big temple", "the old water tank"),
    "hinglish": ("bade mandir ke peeche wala petrol pump", "purani tanki"),
    "hi": ("बड़े मंदिर के पीछे वाला पेट्रोल पंप", "पुरानी टंकी"),
    "ta": ("பெரிய கோவில் பின்னால் உள்ள பெட்ரோல் பங்க்", "பழைய தண்ணீர் தொட்டி"),
    "bn": ("বড় মন্দিরের পিছনের পেট্রোল পাম্প", "পুরনো জলের ট্যাঙ্ক"),
}

# Life-safety clauses appended to some emergencies; each raises severity by one.
ESCALATORS: dict[Language, dict[str, str]] = {
    "en": {
        "trapped": "2 people are trapped inside",
        "child": "there is a small child inside",
        "unconscious": "he is unconscious now",
        "breathing": "she is not breathing properly",
    },
    "hinglish": {
        "trapped": "do log andar phanse hue hain",
        "child": "andar ek chhota bachha hai",
        "unconscious": "ab woh behosh hai",
        "breathing": "saans theek se nahi le pa rahi",
    },
    "hi": {
        "trapped": "दो लोग अंदर फंसे हुए हैं",
        "child": "अंदर एक छोटा बच्चा है",
        "unconscious": "अब वह बेहोश है",
        "breathing": "वह ठीक से सांस नहीं ले पा रही",
    },
    "ta": {
        "trapped": "இரண்டு பேர் உள்ளே சிக்கியிருக்கிறார்கள்",
        "child": "உள்ளே ஒரு சிறு குழந்தை இருக்கிறது",
        "unconscious": "இப்போது அவர் மயக்கத்தில் இருக்கிறார்",
        "breathing": "அவருக்கு மூச்சு விட முடியவில்லை",
    },
    "bn": {
        "trapped": "দুজন ভিতরে আটকে আছে",
        "child": "ভিতরে একটা ছোট বাচ্চা আছে",
        "unconscious": "এখন সে অজ্ঞান",
        "breathing": "ঠিকমতো শ্বাস নিতে পারছে না",
    },
}

ESCALATORS_BY_DEPARTMENT: dict[str, tuple[str, ...]] = {
    "fire": ("trapped", "child"),
    "disaster": ("trapped", "child"),
    "medical": ("unconscious", "breathing"),
}

PANIC: dict[Language, tuple[str, ...]] = {
    "en": ("HELP!!", "please hurry", "urgent!!!", "pls come fast"),
    "hinglish": ("jaldi aao", "bachao!!", "please jaldi", "help help"),
    "hi": ("जल्दी आओ", "बचाओ!!", "मदद करो", "कृपया जल्दी"),
    "ta": ("உதவி!!", "சீக்கிரம் வாங்க", "தயவு செய்து வேகமா"),
    "bn": ("বাঁচাও!!", "তাড়াতাড়ি আসুন", "সাহায্য করুন"),
}

FRAMES: dict[Language, tuple[str, ...]] = {
    "en": (
        "{event} at {loc}",
        "{event} near {loc}",
        "{loc} - {event}",
        "please send help, {event} at {loc}",
        "{event}. we are at {loc}",
        "emergency at {loc}, {event}",
        "need help at {loc}, {event}",
        "{event}",
        "{event}, please come quickly",
    ),
    "hinglish": (
        "{loc} pe {event}",
        "{event}, {loc} mein",
        "{loc} ke paas {event}",
        "jaldi aao, {loc} pe {event}",
        "{event}, hum {loc} pe hain",
        "bhai {loc} pe {event}",
        "help chahiye {loc}, {event}",
        "{event}",
        "{event}, jaldi koi bhejo",
    ),
    "hi": (
        "{loc} पर {event}",
        "{event}, {loc} में",
        "{loc} के पास {event}",
        "जल्दी आइए, {loc} पर {event}",
        "{event}, हम {loc} पर हैं",
        "मदद चाहिए {loc}, {event}",
        "{event}",
        "{event}, जल्दी किसी को भेजो",
    ),
    "ta": (
        "{loc} இல் {event}",
        "{loc} அருகே {event}",
        "{event}, நாங்கள் {loc} இல் இருக்கிறோம்",
        "உடனே வாருங்கள், {loc} இல் {event}",
        "உதவி தேவை {loc}, {event}",
        "{event}",
        "{event}, சீக்கிரம் ஆளை அனுப்புங்கள்",
    ),
    "bn": (
        "{loc} এ {event}",
        "{loc} এর কাছে {event}",
        "{event}, আমরা {loc} এ আছি",
        "তাড়াতাড়ি আসুন, {loc} এ {event}",
        "সাহায্য দরকার {loc}, {event}",
        "{event}",
        "{event}, কাউকে পাঠান",
    ),
}

E = Event

EVENTS: dict[Language, dict[str, list[Event]]] = {
    "en": {
        "fire": [
            E(4, "a building is on fire"),
            E(4, "fire on the 3rd floor of our building"),
            E(3, "smoke coming out of a shop"),
            E(4, "kitchen fire spreading to other flats"),
            E(5, "cylinder blast and a big fire"),
            E(4, "strong gas leak smell, people feeling dizzy"),
            E(3, "a car is on fire"),
            E(4, "flames coming out of the roof"),
            E(3, "electrical fire in the meter room"),
            E(4, "factory fire with thick black smoke"),
        ],
        "police": [
            E(4, "someone is breaking into my house"),
            E(4, "two men fighting with knives"),
            E(3, "my chain was snatched by bike riders"),
            E(4, "a woman is being harassed by a group of men"),
            E(4, "robbery at a jewellery shop"),
            E(3, "drunk men beating up a guy"),
            E(4, "a man is following me with a knife"),
            E(4, "a child was pulled into a van, kidnapping"),
            E(3, "a mob is gathering and throwing stones"),
            E(4, "gunshots heard"),
        ],
        "medical": [
            E(5, "my father has severe chest pain"),
            E(5, "a man collapsed and is not moving"),
            E(4, "road accident, the rider is bleeding a lot"),
            E(4, "my wife is in labour, need an ambulance"),
            E(4, "a child fell from the stairs, head injury"),
            E(4, "an old lady fainted"),
            E(4, "snake bite, the leg is swelling"),
            E(4, "someone drank poison"),
            E(5, "heart attack, please send an ambulance"),
            E(4, "a worker fell from the scaffolding"),
        ],
        "disaster": [
            E(5, "water entering houses, people stuck on rooftops"),
            E(5, "a wall collapsed after the rain, people under it"),
            E(4, "flood water rising fast, cars floating"),
            E(3, "a big tree fell on a house"),
            E(4, "building cracking and tilting"),
            E(4, "underpass flooded, a bus is stuck inside"),
            E(5, "a house collapsed, family trapped under the debris"),
            E(4, "river overflowing into the colony"),
            E(4, "landslide hit a car on the road"),
            E(4, "a boat with people is stuck in the flood"),
        ],
        "utilities": [
            E(4, "live electric wire fallen into the water"),
            E(4, "transformer burst with sparks"),
            E(3, "main water pipeline burst, road flooding"),
            E(3, "electric pole sparking and about to fall"),
            E(3, "open manhole on the main road, a scooter fell in"),
            E(4, "high tension cable snapped and lying on the road"),
            E(3, "sewage overflowing into homes"),
            E(3, "street light pole giving electric shocks"),
            E(4, "gas pipeline damaged by digging"),
        ],
    },
    "hinglish": {
        "fire": [
            E(4, "building mein aag lagi hai"),
            E(4, "teesri manzil pe aag lag gayi"),
            E(3, "dukaan se dhuaan nikal raha hai"),
            E(4, "kitchen ki aag doosre flat tak pahunch gayi"),
            E(5, "cylinder phat gaya, bahut badi aag"),
            E(4, "gas ki tez smell aa rahi, log chakkar kha rahe"),
            E(3, "gaadi mein aag lag gayi"),
            E(4, "chhat se lapte nikal rahi hain"),
            E(3, "meter room mein short circuit se aag"),
            E(4, "factory mein aag, kaala dhuaan"),
        ],
        "police": [
            E(4, "koi ghar mein ghus raha hai"),
            E(4, "do log chaku leke lad rahe hain"),
            E(3, "bike wale chain chheen ke bhaag gaye"),
            E(4, "kuch ladke ek ladki ko pareshan kar rahe hain"),
            E(4, "jewellery shop mein loot ho rahi hai"),
            E(3, "sharabi log ek aadmi ko maar rahe hain"),
            E(4, "ek aadmi chaku leke mera peecha kar raha hai"),
            E(4, "ek bachhe ko van mein kheench ke le gaye"),
            E(3, "bheed pathar fenk rahi hai"),
            E(4, "goli chalne ki awaaz aayi"),
        ],
        "medical": [
            E(5, "papa ko seene mein bahut dard ho raha hai"),
            E(5, "ek aadmi gir gaya, hil nahi raha"),
            E(4, "accident hua hai, bike wale ka bahut khoon beh raha"),
            E(4, "biwi ko delivery ka dard shuru ho gaya, ambulance chahiye"),
            E(4, "bachha seedhi se gir gaya, sar pe chot"),
            E(4, "ek budhi amma chakkar kha ke gir gayi"),
            E(4, "saanp ne kaat liya, pair sooj raha hai"),
            E(4, "kisi ne zeher pi liya"),
            E(5, "heart attack aaya hai, ambulance bhejo"),
            E(4, "mazdoor upar se gir gaya"),
        ],
        "disaster": [
            E(5, "gharon mein paani ghus gaya, log chhat pe phanse hain"),
            E(5, "baarish se deewar gir gayi, log dabe hain"),
            E(4, "baadh ka paani tezi se badh raha, gaadiyan beh rahi"),
            E(3, "bada ped ghar pe gir gaya"),
            E(4, "building mein darar aa gayi, jhuk rahi hai"),
            E(4, "underpass mein paani bhar gaya, bus phasi hai"),
            E(5, "makaan gir gaya, parivaar malbe mein daba hai"),
            E(4, "nadi ka paani colony mein aa gaya"),
            E(4, "pahad khisak gaya, gaadi dab gayi"),
            E(4, "naav mein log baadh mein phanse hain"),
        ],
        "utilities": [
            E(4, "bijli ka taar paani mein gir gaya"),
            E(4, "transformer phat gaya, chingari nikal rahi"),
            E(3, "paani ki main pipe phat gayi, sadak pe paani"),
            E(3, "bijli ka khamba gir raha hai, spark ho raha"),
            E(3, "khula manhole, scooty wala gir gaya"),
            E(4, "high tension taar toot ke sadak pe pada hai"),
            E(3, "gutter ka paani gharon mein aa raha"),
            E(3, "khambe mein current aa raha hai"),
            E(4, "khudai mein gas pipeline toot gayi"),
        ],
    },
    "hi": {
        "fire": [
            E(4, "बिल्डिंग में आग लगी है"),
            E(4, "तीसरी मंजिल पर आग लग गई"),
            E(3, "दुकान से धुआं निकल रहा है"),
            E(4, "रसोई की आग दूसरे फ्लैट तक पहुंच गई"),
            E(5, "सिलेंडर फट गया, बहुत बड़ी आग"),
            E(4, "गैस की तेज़ बदबू, लोगों को चक्कर आ रहे हैं"),
            E(3, "गाड़ी में आग लग गई"),
            E(4, "छत से लपटें निकल रही हैं"),
            E(3, "मीटर रूम में शॉर्ट सर्किट से आग"),
            E(4, "फैक्ट्री में आग, काला धुआं"),
        ],
        "police": [
            E(4, "कोई घर में घुस रहा है"),
            E(4, "दो लोग चाकू लेकर लड़ रहे हैं"),
            E(3, "बाइक वाले चेन छीनकर भाग गए"),
            E(4, "कुछ लड़के एक लड़की को परेशान कर रहे हैं"),
            E(4, "ज्वेलरी की दुकान में लूट हो रही है"),
            E(3, "शराबी लोग एक आदमी को पीट रहे हैं"),
            E(4, "एक आदमी चाकू लेकर मेरा पीछा कर रहा है"),
            E(4, "एक बच्चे को वैन में खींच ले गए"),
            E(3, "भीड़ पत्थर फेंक रही है"),
            E(4, "गोली चलने की आवाज़ आई"),
        ],
        "medical": [
            E(5, "पापा के सीने में तेज़ दर्द है"),
            E(5, "एक आदमी गिर गया, हिल नहीं रहा"),
            E(4, "एक्सीडेंट हुआ है, बाइक वाले का बहुत खून बह रहा है"),
            E(4, "पत्नी को प्रसव पीड़ा, एम्बुलेंस चाहिए"),
            E(4, "बच्चा सीढ़ियों से गिर गया, सिर में चोट"),
            E(4, "एक बूढ़ी महिला चक्कर खाकर गिर गई"),
            E(4, "सांप ने काट लिया, पैर सूज रहा है"),
            E(4, "किसी ने ज़हर पी लिया"),
            E(5, "दिल का दौरा पड़ा है, एम्बुलेंस भेजो"),
            E(4, "मज़दूर ऊपर से गिर गया"),
        ],
        "disaster": [
            E(5, "घरों में पानी घुस गया, लोग छत पर फंसे हैं"),
            E(5, "बारिश से दीवार गिर गई, लोग दबे हैं"),
            E(4, "बाढ़ का पानी तेज़ी से बढ़ रहा है, गाड़ियां बह रही हैं"),
            E(3, "बड़ा पेड़ घर पर गिर गया"),
            E(4, "बिल्डिंग में दरार आ गई, झुक रही है"),
            E(4, "अंडरपास में पानी भर गया, बस फंसी है"),
            E(5, "मकान गिर गया, परिवार मलबे में दबा है"),
            E(4, "नदी का पानी कॉलोनी में आ गया"),
            E(4, "भूस्खलन से गाड़ी दब गई"),
            E(4, "नाव में लोग बाढ़ में फंसे हैं"),
        ],
        "utilities": [
            E(4, "बिजली का तार पानी में गिर गया"),
            E(4, "ट्रांसफार्मर फट गया, चिंगारी निकल रही है"),
            E(3, "पानी की मेन पाइप फट गई, सड़क पर पानी"),
            E(3, "बिजली का खंभा गिरने वाला है, स्पार्क हो रहा है"),
            E(3, "खुला मैनहोल, स्कूटी वाला गिर गया"),
            E(4, "हाई टेंशन तार टूटकर सड़क पर पड़ा है"),
            E(3, "नाले का पानी घरों में घुस रहा है"),
            E(3, "खंभे में करंट आ रहा है"),
            E(4, "खुदाई में गैस पाइपलाइन टूट गई"),
        ],
    },
    "ta": {
        "fire": [
            E(4, "கட்டிடத்தில் தீ பிடித்துள்ளது"),
            E(4, "மூன்றாவது மாடியில் தீ"),
            E(3, "கடையில் இருந்து புகை வருகிறது"),
            E(4, "சமையலறை தீ பக்கத்து வீட்டுக்கு பரவுகிறது"),
            E(5, "சிலிண்டர் வெடித்தது, பெரிய தீ"),
            E(4, "கேஸ் வாசனை அதிகம், மக்களுக்கு தலை சுற்றுகிறது"),
            E(3, "கார் தீப்பிடித்து எரிகிறது"),
            E(4, "கூரையில் இருந்து தீப்பிழம்பு வருகிறது"),
            E(4, "தொழிற்சாலையில் தீ, கரும்புகை"),
        ],
        "police": [
            E(4, "யாரோ வீட்டுக்குள் நுழைகிறார்கள்"),
            E(4, "இரண்டு பேர் கத்தியுடன் சண்டை போடுகிறார்கள்"),
            E(3, "பைக்கில் வந்தவர்கள் சங்கிலியை பறித்துச் சென்றார்கள்"),
            E(4, "ஒரு பெண்ணை சிலர் துன்புறுத்துகிறார்கள்"),
            E(4, "நகைக்கடையில் கொள்ளை நடக்கிறது"),
            E(3, "குடிகாரர்கள் ஒருவரை அடிக்கிறார்கள்"),
            E(4, "ஒருவன் கத்தியுடன் என்னை பின்தொடர்கிறான்"),
            E(4, "ஒரு குழந்தையை வேனில் இழுத்துச் சென்றார்கள்"),
            E(4, "துப்பாக்கி சுடும் சத்தம் கேட்டது"),
        ],
        "medical": [
            E(5, "அப்பாவுக்கு நெஞ்சு வலி அதிகம்"),
            E(5, "ஒருவர் விழுந்துவிட்டார், அசையவில்லை"),
            E(4, "விபத்து, பைக்கில் வந்தவருக்கு நிறைய ரத்தம்"),
            E(4, "மனைவிக்கு பிரசவ வலி, ஆம்புலன்ஸ் வேண்டும்"),
            E(4, "குழந்தை படியில் இருந்து விழுந்தது, தலையில் காயம்"),
            E(4, "பாட்டி மயங்கி விழுந்தார்"),
            E(4, "பாம்பு கடித்துவிட்டது, கால் வீங்குகிறது"),
            E(4, "ஒருவர் விஷம் குடித்துவிட்டார்"),
            E(5, "மாரடைப்பு, உடனே ஆம்புலன்ஸ் அனுப்புங்கள்"),
        ],
        "disaster": [
            E(5, "வீடுகளுக்குள் தண்ணீர் புகுந்தது, மக்கள் மாடியில் சிக்கியுள்ளனர்"),
            E(5, "மழையால் சுவர் இடிந்தது, ஆட்கள் அடியில் இருக்கிறார்கள்"),
            E(4, "வெள்ள நீர் வேகமாக உயர்கிறது, கார்கள் மிதக்கின்றன"),
            E(3, "பெரிய மரம் வீட்டின் மேல் விழுந்தது"),
            E(4, "கட்டிடத்தில் விரிசல், சாய்கிறது"),
            E(4, "சுரங்கப்பாதையில் தண்ணீர், பஸ் சிக்கியுள்ளது"),
            E(5, "வீடு இடிந்தது, குடும்பம் இடிபாடுகளில் சிக்கியுள்ளது"),
            E(4, "ஆற்று நீர் குடியிருப்புக்குள் வருகிறது"),
            E(4, "படகில் மக்கள் வெள்ளத்தில் சிக்கியுள்ளனர்"),
        ],
        "utilities": [
            E(4, "மின் கம்பி தண்ணீரில் விழுந்துவிட்டது"),
            E(4, "டிரான்ஸ்பார்மர் வெடித்தது, தீப்பொறி வருகிறது"),
            E(3, "குடிநீர் குழாய் உடைந்து சாலையில் தண்ணீர்"),
            E(3, "மின்கம்பம் சாய்ந்து விழப்போகிறது"),
            E(3, "திறந்த பாதாள சாக்கடை, ஸ்கூட்டர் விழுந்தது"),
            E(4, "உயர் மின்னழுத்த கம்பி அறுந்து சாலையில் கிடக்கிறது"),
            E(3, "கழிவுநீர் வீடுகளுக்குள் வருகிறது"),
            E(3, "மின்கம்பத்தில் மின்சாரம் பாய்கிறது"),
        ],
    },
    "bn": {
        "fire": [
            E(4, "বিল্ডিংয়ে আগুন লেগেছে"),
            E(4, "তিনতলায় আগুন লেগেছে"),
            E(3, "দোকান থেকে ধোঁয়া বেরোচ্ছে"),
            E(4, "রান্নাঘরের আগুন পাশের ফ্ল্যাটে ছড়াচ্ছে"),
            E(5, "সিলিন্ডার ফেটে বিশাল আগুন"),
            E(4, "খুব গ্যাসের গন্ধ, লোকের মাথা ঘুরছে"),
            E(3, "গাড়িতে আগুন লেগেছে"),
            E(4, "ছাদ থেকে আগুনের শিখা বেরোচ্ছে"),
            E(4, "কারখানায় আগুন, কালো ধোঁয়া"),
        ],
        "police": [
            E(4, "কেউ বাড়িতে ঢুকছে"),
            E(4, "দুজন ছুরি নিয়ে মারামারি করছে"),
            E(3, "বাইকে এসে চেন ছিনতাই করে পালাল"),
            E(4, "কয়েকটা ছেলে একটা মেয়েকে উত্যক্ত করছে"),
            E(4, "গয়নার দোকানে ডাকাতি হচ্ছে"),
            E(3, "মাতালরা একজনকে মারছে"),
            E(4, "একজন ছুরি নিয়ে আমার পিছু নিচ্ছে"),
            E(4, "একটা বাচ্চাকে ভ্যানে টেনে নিয়ে গেল"),
            E(4, "গুলির আওয়াজ শোনা গেল"),
        ],
        "medical": [
            E(5, "বাবার বুকে খুব ব্যথা"),
            E(5, "একজন পড়ে গেছে, নড়ছে না"),
            E(4, "দুর্ঘটনা, বাইক আরোহীর খুব রক্ত পড়ছে"),
            E(4, "স্ত্রীর প্রসব বেদনা, অ্যাম্বুলেন্স দরকার"),
            E(4, "বাচ্চা সিঁড়ি থেকে পড়ে মাথায় চোট"),
            E(4, "দিদিমা মাথা ঘুরে পড়ে গেছেন"),
            E(4, "সাপে কামড়েছে, পা ফুলে যাচ্ছে"),
            E(4, "কেউ বিষ খেয়েছে"),
            E(5, "হার্ট অ্যাটাক, এখনই অ্যাম্বুলেন্স পাঠান"),
        ],
        "disaster": [
            E(5, "বাড়িতে জল ঢুকেছে, লোকজন ছাদে আটকে"),
            E(5, "বৃষ্টিতে দেয়াল ভেঙে লোক চাপা পড়েছে"),
            E(4, "বন্যার জল দ্রুত বাড়ছে, গাড়ি ভাসছে"),
            E(3, "বড় গাছ বাড়ির উপর পড়েছে"),
            E(4, "বিল্ডিংয়ে ফাটল, হেলে পড়ছে"),
            E(4, "আন্ডারপাসে জল, বাস আটকে আছে"),
            E(5, "বাড়ি ভেঙে পড়েছে, পরিবার ধ্বংসস্তূপে আটকে"),
            E(4, "নদীর জল পাড়ায় ঢুকছে"),
            E(4, "নৌকায় লোক বন্যায় আটকে আছে"),
        ],
        "utilities": [
            E(4, "বিদ্যুতের তার জলে পড়েছে"),
            E(4, "ট্রান্সফরমার ফেটে ফুলকি বেরোচ্ছে"),
            E(3, "জলের মেন পাইপ ফেটে রাস্তায় জল"),
            E(3, "বিদ্যুতের খুঁটি হেলে পড়ছে, স্পার্ক হচ্ছে"),
            E(3, "খোলা ম্যানহোল, স্কুটার পড়ে গেছে"),
            E(4, "হাই টেনশন তার ছিঁড়ে রাস্তায় পড়ে আছে"),
            E(3, "নর্দমার জল বাড়িতে ঢুকছে"),
            E(3, "খুঁটিতে কারেন্ট আসছে"),
        ],
    },
}

T = Template

NON_URGENT: dict[Language, list[Template]] = {
    "en": [
        T("utilities", 1, "Streetlight not working at {loc} for a week"),
        T("utilities", 2, "No water supply since morning at {loc}"),
        T("utilities", 2, "Power cut at {loc} for 2 hours, when will it come back?"),
        T("police", 2, "Neighbours playing loud music late at night at {loc}"),
        T("utilities", 1, "There is a big pothole on the road near {loc}"),
        T("police", 1, "I lost my wallet near {loc} yesterday"),
        T("none", 1, "Stray dogs barking all night at {loc}"),
        T("none", 1, "Garbage has not been collected at {loc} for 3 days"),
        T("police", 1, "How do I get a copy of my FIR?"),
        T("none", 1, "Is the metro running today?"),
        T("police", 1, "Someone parked a car blocking my gate at {loc}"),
        T("utilities", 1, "Tree branches touching electric wires at {loc}, please trim them"),
        T("disaster", 2, "Some water logging on the road at {loc} after rain, nobody in danger"),
    ],
    "hinglish": [
        T("utilities", 1, "{loc} mein streetlight ek hafte se kharab hai"),
        T("utilities", 2, "subah se paani nahi aa raha {loc} mein"),
        T("utilities", 2, "{loc} mein 2 ghante se light nahi hai, kab aayegi?"),
        T("police", 2, "padosi raat ko bahut tez gaana baja rahe hain {loc}"),
        T("utilities", 1, "{loc} ke paas sadak pe bada gaddha hai"),
        T("police", 1, "kal {loc} ke paas mera purse kho gaya"),
        T("none", 1, "{loc} mein kooda 3 din se nahi utha"),
        T("police", 1, "FIR ki copy kaise milegi?"),
        T("none", 1, "kya aaj metro chal rahi hai?"),
        T("none", 1, "kutte raat bhar bhaunkte hain {loc} mein"),
        T("police", 1, "{loc} pe kisi ne gate ke aage gaadi khadi kar di"),
        T("utilities", 1, "{loc} pe ped ki daaliyan bijli ke taar se lag rahi hain, katwa do"),
        T("disaster", 2, "baarish ke baad {loc} road pe thoda paani bhara hai, koi khatra nahi"),
    ],
    "hi": [
        T("utilities", 1, "{loc} में एक हफ्ते से स्ट्रीटलाइट खराब है"),
        T("utilities", 2, "सुबह से {loc} में पानी नहीं आ रहा"),
        T("utilities", 2, "{loc} में दो घंटे से बिजली नहीं है, कब आएगी?"),
        T("police", 2, "पड़ोसी रात को बहुत तेज़ गाना बजा रहे हैं {loc}"),
        T("utilities", 1, "{loc} के पास सड़क पर बड़ा गड्ढा है"),
        T("police", 1, "कल {loc} के पास मेरा पर्स खो गया"),
        T("none", 1, "{loc} में तीन दिन से कूड़ा नहीं उठा"),
        T("police", 1, "एफआईआर की कॉपी कैसे मिलेगी?"),
        T("none", 1, "क्या आज मेट्रो चल रही है?"),
        T("police", 1, "{loc} पर किसी ने गेट के आगे गाड़ी खड़ी कर दी"),
        T("utilities", 1, "{loc} पर पेड़ की डालियां बिजली के तार से छू रही हैं"),
        T("disaster", 2, "बारिश के बाद {loc} सड़क पर थोड़ा पानी भरा है, कोई खतरा नहीं"),
    ],
    "ta": [
        T("utilities", 1, "{loc} இல் ஒரு வாரமாக தெருவிளக்கு எரியவில்லை"),
        T("utilities", 2, "காலையில் இருந்து {loc} இல் தண்ணீர் வரவில்லை"),
        T("utilities", 2, "{loc} இல் இரண்டு மணி நேரமாக மின்சாரம் இல்லை"),
        T("police", 2, "பக்கத்து வீட்டில் இரவில் சத்தமாக பாட்டு போடுகிறார்கள் {loc}"),
        T("utilities", 1, "{loc} அருகே சாலையில் பெரிய பள்ளம் இருக்கிறது"),
        T("police", 1, "நேற்று {loc} அருகே என் பர்ஸ் தொலைந்துவிட்டது"),
        T("none", 1, "{loc} இல் மூன்று நாளாக குப்பை எடுக்கவில்லை"),
        T("police", 1, "எஃப்ஐஆர் நகல் எப்படி பெறுவது?"),
        T("none", 1, "இன்று மெட்ரோ ஓடுகிறதா?"),
        T("police", 1, "{loc} இல் யாரோ என் கேட்டுக்கு முன் காரை நிறுத்திவிட்டார்கள்"),
        T("utilities", 1, "{loc} இல் மரக்கிளைகள் மின்கம்பியை தொடுகின்றன"),
        T("disaster", 2, "மழைக்குப் பிறகு {loc} சாலையில் கொஞ்சம் தண்ணீர் தேங்கியுள்ளது, ஆபத்து இல்லை"),
    ],
    "bn": [
        T("utilities", 1, "{loc} এ এক সপ্তাহ ধরে রাস্তার আলো জ্বলছে না"),
        T("utilities", 2, "সকাল থেকে {loc} এ জল আসছে না"),
        T("utilities", 2, "{loc} এ দুই ঘণ্টা ধরে কারেন্ট নেই"),
        T("police", 2, "পাশের বাড়িতে রাতে খুব জোরে গান বাজাচ্ছে {loc}"),
        T("utilities", 1, "{loc} এর কাছে রাস্তায় বড় গর্ত"),
        T("police", 1, "কাল {loc} এর কাছে আমার পার্স হারিয়ে গেছে"),
        T("none", 1, "{loc} এ তিন দিন ধরে আবর্জনা তোলা হয়নি"),
        T("police", 1, "এফআইআর এর কপি কীভাবে পাব?"),
        T("none", 1, "আজ কি মেট্রো চলছে?"),
        T("police", 1, "{loc} এ কেউ আমার গেটের সামনে গাড়ি রেখে দিয়েছে"),
        T("utilities", 1, "{loc} এ গাছের ডাল বিদ্যুতের তারে লাগছে"),
        T("disaster", 2, "বৃষ্টির পর {loc} রাস্তায় একটু জল জমেছে, কোনো বিপদ নেই"),
    ],
}

PRANKS: dict[Language, list[str]] = {
    "en": [
        "hello hello testing 123",
        "aliens have landed at {loc} lol",
        "I want to order a pizza",
        "fire fire!! just kidding bro",
        "wrong number sorry",
        "can you tell me a joke",
        "zombies attacking {loc} send the army hahaha",
        "just checking if this number works",
        "my friend dared me to call lol",
    ],
    "hinglish": [
        "hello hello testing ho raha hai",
        "{loc} pe aliens aa gaye lol",
        "pizza order karna tha",
        "aag aag!! mazaak kar raha tha bhai",
        "galti se call lag gaya",
        "kuch nahi bas aise hi call kiya",
        "bhai ek joke sunao",
        "bas check kar raha tha number chalta hai ya nahi",
        "dost ne bola call kar, hahaha",
    ],
    "hi": [
        "हैलो हैलो टेस्टिंग",
        "{loc} पर एलियन आ गए हाहा",
        "पिज़्ज़ा ऑर्डर करना है",
        "आग आग!! मज़ाक कर रहा था",
        "गलती से कॉल लग गया",
        "बस ऐसे ही फोन किया",
        "बस देख रहा था नंबर चलता है या नहीं",
        "दोस्त ने शर्त लगाई थी हाहा",
    ],
    "ta": [
        "ஹலோ ஹலோ டெஸ்டிங்",
        "{loc} இல் ஏலியன்கள் வந்துவிட்டார்கள் ஹாஹா",
        "பீட்சா ஆர்டர் செய்ய வேண்டும்",
        "தீ தீ!! சும்மா விளையாட்டுக்கு சொன்னேன்",
        "தவறுதலாக கால் வந்துவிட்டது",
        "இந்த நம்பர் வேலை செய்கிறதா என்று பார்த்தேன்",
        "நண்பன் சவால் விட்டான் ஹாஹா",
    ],
    "bn": [
        "হ্যালো হ্যালো টেস্টিং",
        "{loc} এ এলিয়েন নেমেছে হাহা",
        "পিৎজা অর্ডার করতে চাই",
        "আগুন আগুন!! মজা করছিলাম",
        "ভুল করে কল হয়ে গেছে",
        "নম্বরটা কাজ করে কিনা দেখছিলাম",
        "বন্ধু বাজি ধরেছিল হাহা",
    ],
}

H = HardCase

HARD_CASES: tuple[HardCase, ...] = (
    # Sarcasm and figurative use of emergency words.
    H("en", "my exam is a disaster, I am definitely going to fail", False, "none", 1, None, "sarcasm"),
    H("en", "this traffic at Sector 18 is killing me", False, "none", 1, "Sector 18", "sarcasm"),
    H("hinglish", "yeh gaana toh fire hai bhai", False, "none", 1, None, "sarcasm"),
    H("hinglish", "meri life mein toh kaam ki baadh aa gayi hai", False, "none", 1, None, "sarcasm"),
    H("en", "I am dying of boredom in this meeting", False, "none", 1, None, "sarcasm"),
    H("hinglish", "mera phone garam hoke aag ban gaya lol", False, "none", 1, None, "sarcasm"),
    H("hi", "मेरी तो आज वाट लग गई, बॉस ने बहुत डांटा", False, "none", 1, None, "sarcasm"),
    H("en", "the new movie totally bombed at the box office", False, "none", 1, None, "sarcasm"),
    H("ta", "தேர்வு ஒரு பேரழிவு மாதிரி போச்சு", False, "none", 1, None, "sarcasm"),
    H("bn", "পরীক্ষাটা একদম দুর্যোগ হয়ে গেল", False, "none", 1, None, "sarcasm"),
    H("hinglish", "bhai aaj party mein aag laga di humne", False, "none", 1, None, "sarcasm"),
    # Emergency keyword present but no emergency.
    H("hinglish", "kal society mein fire drill hai, sabko inform kar rahe hain", False, "none", 1, None, "keyword_trap"),
    H("en", "Is the fire station in Sector 6 hiring drivers?", False, "none", 1, "Sector 6", "keyword_trap"),
    H("hi", "एम्बुलेंस सेवा का नंबर क्या है, बस जानकारी चाहिए", False, "none", 1, None, "keyword_trap"),
    # Silent SOS: the caller cannot speak freely.
    H("en", "1111111111", True, "police", 4, None, "silent_sos"),
    H("en", "... --- ...", True, "police", 4, None, "silent_sos"),
    H("en", "asdfgh jkl qwrt zxcv", True, "police", 4, None, "silent_sos"),
    H("en", "999 999 999", True, "police", 4, None, "silent_sos"),
    H("en", "cant talk. he is in the house. sector 50", True, "police", 5, "sector 50", "silent_sos"),
    H("hinglish", "bol nahi sakti.. woh yahin hai.. help", True, "police", 5, None, "silent_sos"),
    # Same event, very different phrasing.
    H("en", "flames and smoke coming out of tower B, Gaur City 2", True, "fire", 4, "Gaur City 2", "same_event"),
    H("hinglish", "Gaur City 2 tower B mein aag, log neeche bhaag rahe", True, "fire", 4, "Gaur City 2", "same_event"),
    H("en", "lots of black smoke from Gaur City 2 B block, smells like burning plastic", True, "fire", 3, "Gaur City 2", "same_event"),
    H("en", "smell of gas near the lift and smoke on the 5th floor, Sector 62", True, "fire", 5, "Sector 62", "same_event"),
    # Real emergencies described without the usual keywords.
    H("hinglish", "pitaji ki saans phool rahi hai, honth neele pad gaye", True, "medical", 5, None, "implicit"),
    H("en", "my grandmother is not waking up", True, "medical", 5, None, "implicit"),
    H("hi", "बच्चा तालाब में डूब रहा है, सेक्टर 137", True, "disaster", 5, "सेक्टर 137", "implicit"),
    H("bn", "বাবা বুক চেপে ধরে বসে আছে, কথা বলতে পারছে না", True, "medical", 5, None, "implicit"),
    H("ta", "அம்மா பேசவே இல்லை, கண் திறக்கவில்லை", True, "medical", 5, None, "implicit"),
    H("hi", "छत पर फंसे हैं, पानी गले तक आ गया, सेक्टर 15", True, "disaster", 5, "सेक्टर 15", "implicit"),
)

# Train-only domain vocabulary: generic words a dispatcher associates with each
# department. Rendered as short events inside the same frames, never in test.
LEXICON_SEVERITY: dict[str, int] = {"fire": 4, "police": 3, "medical": 4, "disaster": 4, "utilities": 3}

LEXICON: dict[Language, dict[str, tuple[str, ...]]] = {
    "en": {
        "fire": ("fire", "smoke everywhere", "flames", "burning smell and smoke", "house burning",
                 "shop on fire", "short circuit fire", "gas leak", "blast", "fire spreading"),
        "police": ("theft", "robbery", "thief in the house", "fight", "attack with a knife", "harassment",
                   "stalker", "kidnap", "assault", "riot", "snatching", "shooting"),
        "medical": ("ambulance needed", "unconscious person", "heavy bleeding", "chest pain",
                    "accident injury", "fainted", "pregnant woman in pain", "poisoning", "fracture",
                    "stroke", "seizure"),
        "disaster": ("flood", "water logging with people stuck", "building collapse", "wall collapse",
                     "tree fall", "landslide", "people stranded", "rooftop rescue needed", "earthquake damage"),
        "utilities": ("live wire", "electric shock", "transformer blast", "pipe burst", "sparking pole",
                      "open manhole", "power line down"),
    },
    "hinglish": {
        "fire": ("aag", "dhuaan hi dhuaan", "lapte", "jalne ki smell", "ghar jal raha",
                 "dukaan mein aag", "short circuit se aag", "gas leak", "dhamaka", "aag fail rahi"),
        "police": ("chori", "loot", "ghar mein chor", "ladai jhagda", "chaku se hamla", "chhedkhani",
                   "peecha kar raha", "apharan", "maar peet", "danga", "chain snatching", "goli chali"),
        "medical": ("ambulance chahiye", "behosh aadmi", "bahut khoon", "seene mein dard",
                    "accident mein chot", "chakkar aake gir gaya", "pregnant aurat dard mein", "zeher",
                    "haddi toot gayi", "lakwa maar gaya", "daura pad raha"),
        "disaster": ("baadh", "paani bhar gaya log phanse", "building gir gayi", "deewar giri", "ped gira",
                     "landslide", "log phanse hain", "chhat se rescue chahiye", "bhukamp"),
        "utilities": ("nanga taar", "current lag gaya", "transformer blast", "pipe phat gayi",
                      "khambe mein spark", "khula gutter", "bijli ki line giri"),
    },
    "hi": {
        "fire": ("आग", "धुआं ही धुआं", "लपटें", "जलने की गंध", "घर जल रहा है", "दुकान में आग",
                 "शॉर्ट सर्किट से आग", "गैस लीक", "धमाका", "आग फैल रही है"),
        "police": ("चोरी", "लूट", "घर में चोर", "लड़ाई झगड़ा", "चाकू से हमला", "छेड़खानी",
                   "पीछा कर रहा है", "अपहरण", "मारपीट", "दंगा", "चेन स्नैचिंग", "गोली चली"),
        "medical": ("एम्बुलेंस चाहिए", "बेहोश आदमी", "बहुत खून", "सीने में दर्द", "दुर्घटना में चोट",
                    "चक्कर आकर गिर गया", "गर्भवती महिला दर्द में", "ज़हर", "हड्डी टूट गई", "लकवा",
                    "दौरा पड़ रहा है"),
        "disaster": ("बाढ़", "पानी भर गया लोग फंसे", "इमारत गिर गई", "दीवार गिरी", "पेड़ गिरा",
                     "भूस्खलन", "लोग फंसे हैं", "छत से बचाव चाहिए", "भूकंप"),
        "utilities": ("नंगा तार", "करंट लग गया", "ट्रांसफार्मर ब्लास्ट", "पाइप फट गई",
                      "खंभे में स्पार्क", "खुला नाला", "बिजली की लाइन गिरी"),
    },
    "ta": {
        "fire": ("தீ", "எங்கும் புகை", "தீப்பிழம்பு", "எரியும் வாசனை", "வீடு எரிகிறது", "கடையில் தீ",
                 "ஷார்ட் சர்க்யூட் தீ", "கேஸ் கசிவு", "வெடிப்பு", "தீ பரவுகிறது"),
        "police": ("திருட்டு", "கொள்ளை", "வீட்டில் திருடன்", "சண்டை", "கத்திக்குத்து", "பாலியல் தொல்லை",
                   "பின்தொடர்கிறான்", "கடத்தல்", "அடிதடி", "கலவரம்", "செயின் பறிப்பு", "துப்பாக்கிச் சூடு"),
        "medical": ("ஆம்புலன்ஸ் தேவை", "மயக்கமான நபர்", "அதிக ரத்தப்போக்கு", "நெஞ்சு வலி",
                    "விபத்தில் காயம்", "மயங்கி விழுந்தார்", "கர்ப்பிணி வலியில்", "விஷம்", "எலும்பு முறிவு",
                    "வலிப்பு"),
        "disaster": ("வெள்ளம்", "தண்ணீர் தேங்கி மக்கள் சிக்கியுள்ளனர்", "கட்டிடம் இடிந்தது", "சுவர் இடிந்தது",
                     "மரம் விழுந்தது", "நிலச்சரிவு", "மக்கள் சிக்கியுள்ளனர்", "மாடியில் இருந்து மீட்க வேண்டும்",
                     "நிலநடுக்கம்"),
        "utilities": ("மின் கம்பி அறுந்தது", "மின்சாரம் தாக்கியது", "டிரான்ஸ்பார்மர் வெடிப்பு", "குழாய் உடைப்பு",
                      "மின்கம்பத்தில் தீப்பொறி", "திறந்த சாக்கடை", "மின் இணைப்பு கீழே விழுந்தது"),
    },
    "bn": {
        "fire": ("আগুন", "চারদিকে ধোঁয়া", "আগুনের শিখা", "পোড়া গন্ধ", "বাড়ি পুড়ছে", "দোকানে আগুন",
                 "শর্ট সার্কিটে আগুন", "গ্যাস লিক", "বিস্ফোরণ", "আগুন ছড়াচ্ছে"),
        "police": ("চুরি", "ডাকাতি", "বাড়িতে চোর", "মারামারি", "ছুরি দিয়ে হামলা", "শ্লীলতাহানি",
                   "পিছু নিচ্ছে", "অপহরণ", "মারধর", "দাঙ্গা", "চেন ছিনতাই", "গুলি চলেছে"),
        "medical": ("অ্যাম্বুলেন্স দরকার", "অজ্ঞান লোক", "প্রচুর রক্ত", "বুকে ব্যথা", "দুর্ঘটনায় আঘাত",
                    "মাথা ঘুরে পড়ে গেছে", "গর্ভবতী মহিলা যন্ত্রণায়", "বিষ", "হাড় ভেঙেছে", "খিঁচুনি"),
        "disaster": ("বন্যা", "জল জমে লোক আটকে", "বিল্ডিং ভেঙে পড়েছে", "দেয়াল ভেঙেছে", "গাছ পড়েছে",
                     "ভূমিধস", "লোক আটকে আছে", "ছাদ থেকে উদ্ধার দরকার", "ভূমিকম্প"),
        "utilities": ("খোলা তার", "কারেন্ট লেগেছে", "ট্রান্সফরমার বিস্ফোরণ", "পাইপ ফেটেছে",
                      "খুঁটিতে স্পার্ক", "খোলা নর্দমা", "বিদ্যুতের লাইন পড়ে গেছে"),
    },
}

KEYBOARD_NEIGHBOURS = {
    "a": "sq", "e": "wr", "i": "uo", "o": "ip", "n": "bm", "s": "ad", "t": "ry", "r": "et",
    "h": "gj", "l": "k", "g": "fh", "d": "sf", "m": "n", "u": "yi", "c": "xv", "p": "o",
}


def add_typos(text: str, language: str, rng: random.Random) -> str:
    """Apply 1–2 realistic typos (drop / double / swap / neighbour key). O(L)."""
    chars = list(text)
    for _ in range(rng.randint(1, 2)):
        positions = [i for i, ch in enumerate(chars) if ch.isalpha()]
        if len(positions) < 4:
            break
        i = rng.choice(positions[1:-1])
        op = rng.choice(("drop", "double", "swap", "neighbour") if language in LATIN_LANGUAGES else ("drop", "double"))
        if op == "drop":
            del chars[i]
        elif op == "double":
            chars.insert(i, chars[i])
        elif op == "swap":
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
        elif chars[i].lower() in KEYBOARD_NEIGHBOURS:
            chars[i] = rng.choice(KEYBOARD_NEIGHBOURS[chars[i].lower()])
    return "".join(chars)
