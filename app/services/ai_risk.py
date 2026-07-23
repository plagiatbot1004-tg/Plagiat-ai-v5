import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field

from app.services.extractor import normalize_text


@dataclass(slots=True)
class AIStyleAssessment:
    score: float | None
    verdict: str
    reasons: list[str] = field(default_factory=list)
    supported: bool = False
    language: str = "unknown"
    provider: str = "local_stylometry"
    confidence: str = "past"
    disclaimer: str = (
        "AI ko‘rsatkichi mualliflikni isbotlamaydi. Natija boshqa dalillar va "
        "muallif bilan suhbat asosida talqin qilinishi kerak."
    )


UZBEK_AI_MARKERS = (
    "bundan tashqari",
    "shuningdek",
    "xulosa qilib aytganda",
    "xulosa o'rnida",
    "ta'kidlash joizki",
    "alohida ta'kidlash kerakki",
    "muhim ahamiyat kasb etadi",
    "zamonaviy dunyoda",
    "bugungi kunda",
    "umuman olganda",
    "shu bilan birga",
)

LANGUAGE_NAMES = {
    "uz": "O‘zbek tili",
    "en": "Ingliz tili",
    "ru": "Rus tili",
    "unknown": "Aniqlanmagan",
}

# Quetext rasmiy til ro‘yxatidan bot ishonchli ajrata oladigan til. O‘zbek va
# rus tillari Quetextning amaldagi rasmiy ro‘yxatida ko‘rsatilmagan.
EXTERNAL_AI_SUPPORTED_LANGUAGES = {"en"}

ENGLISH_MARKERS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "of",
    "on",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "with",
}

UZBEK_MARKERS = {
    "ammo",
    "bilan",
    "bir",
    "bo‘ladi",
    "bu",
    "ham",
    "uchun",
    "esa",
    "kabi",
    "kerak",
    "qilish",
    "shu",
    "va",
    "yoki",
}


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code.upper() if code else LANGUAGE_NAMES["unknown"])


def detect_document_language(text: str) -> str:
    """O‘zbek, ingliz va rus tillarini konservativ tarzda ajratadi."""
    letters = [character for character in text if character.isalpha()]
    if not letters:
        return "unknown"
    cyrillic = sum(
        "а" <= character.casefold() <= "я" or character.casefold() == "ё"
        for character in letters
    )
    if cyrillic / len(letters) >= 0.35:
        return "ru"

    words = re.findall(r"[a-zA-Z‘’'ʻʼ‘’]+", text.casefold())
    if len(words) < 20:
        return "unknown"
    english_hits = sum(word in ENGLISH_MARKERS for word in words)
    uzbek_hits = sum(word in UZBEK_MARKERS for word in words)
    uzbek_chars = sum(any(mark in word for mark in ("o‘", "g‘", "o'", "g'")) for word in words)
    if english_hits >= max(5, uzbek_hits * 1.8):
        return "en"
    if uzbek_hits + uzbek_chars >= max(4, english_hits * 1.25):
        return "uz"
    return "unknown"


def supports_external_ai(language: str) -> bool:
    return language.casefold() in EXTERNAL_AI_SUPPORTED_LANGUAGES


def _coefficient_of_variation(values: list[int]) -> float:
    if len(values) < 2 or statistics.mean(values) == 0:
        return 0.0
    return statistics.pstdev(values) / statistics.mean(values)


def _repeated_ngram_ratio(words: list[str], size: int = 4) -> float:
    if len(words) < size * 2:
        return 0.0
    ngrams = [tuple(words[index : index + size]) for index in range(len(words) - size + 1)]
    counts = Counter(ngrams)
    repeated = sum(count - 1 for count in counts.values() if count > 1)
    return repeated / len(ngrams)


def analyze_uzbek_ai_style(text: str) -> AIStyleAssessment:
    normalized = normalize_text(text)
    words = normalized.split()
    if len(words) < 120:
        return AIStyleAssessment(
            score=None,
            verdict="AI-uslubni baholash uchun matn juda qisqa",
            reasons=["Kamida 120 so‘z tavsiya qilinadi."],
            language="uz",
        )

    sentences = [
        item.strip()
        for item in re.split(r"(?<=[.!?])\s+|\n+", text)
        if len(normalize_text(item).split()) >= 4
    ]
    sentence_lengths = [len(normalize_text(sentence).split()) for sentence in sentences]
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    paragraph_lengths = [len(normalize_text(part).split()) for part in paragraphs]

    score = 8.0
    reasons: list[str] = []

    sentence_cv = _coefficient_of_variation(sentence_lengths)
    if len(sentence_lengths) >= 6 and sentence_cv < 0.30:
        score += 22
        reasons.append("Gap uzunliklari noodatiy darajada bir xil.")
    elif len(sentence_lengths) >= 6 and sentence_cv < 0.45:
        score += 12
        reasons.append("Gap tuzilishida bir xillik kuzatildi.")

    paragraph_cv = _coefficient_of_variation(paragraph_lengths)
    if len(paragraph_lengths) >= 4 and paragraph_cv < 0.25:
        score += 15
        reasons.append("Abzatslar hajmi juda bir xil.")

    marker_count = sum(normalized.count(marker) for marker in UZBEK_AI_MARKERS)
    marker_rate = marker_count / max(len(words), 1) * 1_000
    if marker_rate >= 5:
        score += 25
        reasons.append("Qolipli bog‘lovchi va xulosa iboralari juda ko‘p ishlatilgan.")
    elif marker_rate >= 2:
        score += 13
        reasons.append("Qolipli akademik iboralar tez-tez takrorlangan.")

    repeated_ratio = _repeated_ngram_ratio(words)
    if repeated_ratio >= 0.04:
        score += 18
        reasons.append("Bir xil to‘rt so‘zli tuzilmalar ko‘p takrorlangan.")
    elif repeated_ratio >= 0.02:
        score += 9
        reasons.append("Ayrim so‘z birikmalari takroriy ishlatilgan.")

    punctuation_types = sum(symbol in text for symbol in ',;:—()!?"')
    if len(words) >= 250 and punctuation_types <= 2:
        score += 8
        reasons.append("Uzun matnda tinish belgilari xilma-xilligi past.")

    unique_ratio = len(set(words)) / math.sqrt(len(words))
    if len(words) >= 300 and unique_ratio < 9:
        score += 8
        reasons.append("Lug‘aviy xilma-xillik nisbatan past.")

    score = round(min(score, 100.0), 2)
    if score < 35:
        verdict = "Kuchli AI-uslub belgisi topilmadi"
    elif score < 70:
        verdict = "Natija noaniq — qo‘shimcha mualliflik tekshiruvi kerak"
    else:
        verdict = "AIga o‘xshash uslub belgilari ko‘p — mualliflikni tekshiring"

    if not reasons:
        reasons.append("Kuchli statistik shubha belgisi aniqlanmadi.")
    return AIStyleAssessment(
        score=score,
        verdict=verdict,
        reasons=reasons[:5],
        supported=True,
        language="uz",
        provider="PlagiAI stilometriyasi",
        confidence="past",
        disclaimer=(
            "O‘zbek tili Quetext AI detektorining rasmiy til ro‘yxatida bo‘lmagani "
            "sababli bu ball faqat uslubiy-statistik xavf indikatoridir; u matnni "
            "AI yozganini isbotlamaydi."
        ),
    )


def analyze_document_ai_style(text: str) -> AIStyleAssessment:
    language = detect_document_language(text)
    if language == "uz":
        return analyze_uzbek_ai_style(text)
    if supports_external_ai(language):
        return AIStyleAssessment(
            score=None,
            verdict="Quetext AI tekshiruvi yakunlanishi kutilmoqda",
            reasons=[
                f"Hujjat tili: {language_name(language)}.",
                "AI ehtimoli Quetext natijasi tayyor bo‘lgach olinadi.",
            ],
            supported=True,
            language=language,
            provider="Quetext AI Detector",
            confidence="kutilmoqda",
            disclaimer=(
                "Tashqi AI detektori natijasi ehtimollik ko‘rsatkichidir; u "
                "mualliflik yoki qoidabuzarlikning yakka o‘zi yetarli isboti emas."
            ),
        )
    return AIStyleAssessment(
        score=None,
        verdict="Hujjat tili uchun ishonchli AI bahosi mavjud emas",
        reasons=[
            "Til ishonchli aniqlanmadi yoki tashqi AI detektori bu tilni qo‘llab-quvvatlamaydi."
        ],
        supported=False,
        language=language,
        provider="mavjud emas",
        confidence="mavjud emas",
    )


def generate_authorship_questions(text: str, limit: int = 3) -> list[str]:
    sentences = []
    for item in re.split(r"(?<=[.!?])\s+|\n+", text):
        cleaned = re.sub(r"\s+", " ", item).strip()
        count = len(normalize_text(cleaned).split())
        if 12 <= count <= 40:
            sentences.append(cleaned)

    sentences.sort(key=lambda value: len(set(normalize_text(value).split())), reverse=True)
    questions = ["Matnning asosiy xulosasini o‘z so‘zingiz bilan tushuntiring."]
    for sentence in sentences:
        shortened = sentence if len(sentence) <= 150 else sentence[:147].rstrip() + "…"
        question = f"“{shortened}” fikrini oddiy misol bilan izohlang."
        if question not in questions:
            questions.append(question)
        if len(questions) >= limit:
            break
    return questions[:limit]
