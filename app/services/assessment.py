from dataclasses import dataclass, field

from app.services.ai_risk import AIStyleAssessment
from app.services.quetext import InternetScanResult


@dataclass(slots=True)
class ProfessionalConclusion:
    status: str
    status_label: str
    headline: str
    conclusion: str
    evidence_level: str
    recommendations: list[str] = field(default_factory=list)


def _similarity_level(value: float) -> tuple[str, str]:
    if value < 10:
        return "past", "Internet manbalari bilan o‘xshashlik past darajada."
    if value < 25:
        return "o‘rta", "Ayrim o‘xshash qismlar mavjud; iqtibos va havolalarni ko‘rib chiqing."
    if value < 50:
        return "yuqori", "Sezilarli o‘xshashlik topildi; manbalar bo‘yicha tahrir zarur."
    return "juda yuqori", "Katta hajmdagi o‘xshashlik topildi; batafsil ekspert ko‘rigi zarur."


def build_professional_conclusion(
    internet: InternetScanResult,
    ai: AIStyleAssessment | None,
) -> ProfessionalConclusion:
    if internet.status != "completed" or internet.similarity is None:
        raise ValueError("Professional xulosa faqat yakunlangan tashqi skan uchun yaratiladi.")

    level, interpretation = _similarity_level(internet.similarity)
    recommendations = [
        "Mos qismlarni asl manbalar bilan solishtiring va zarur joylarda havola kiriting."
    ]
    if internet.similarity >= 10:
        recommendations.insert(0, "Eng katta moslik bergan manbalardan boshlab tahrir qiling.")
    if ai and ai.score is not None and ai.score >= 20:
        recommendations.append(
            "AI ko‘rsatkichini yakka dalil sifatida ishlatmang; mualliflik savollarini bering."
        )
    recommendations.append("Yakuniy akademik qarorni inson eksperti qabul qilishi kerak.")
    return ProfessionalConclusion(
        status="verified",
        status_label="TEKSHIRUV YAKUNLANDI",
        headline=f"Internet o‘xshashlik darajasi: {level}",
        conclusion=(
            f"Ochiq internet va akademik veb manbalarda {internet.similarity:.2f}% "
            f"o‘xshashlik aniqlandi. {interpretation}"
        ),
        evidence_level="Quetext DeepSearch tashqi skani bilan tasdiqlangan",
        recommendations=recommendations[:4],
    )
