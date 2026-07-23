from app.services.ai_risk import (
    analyze_document_ai_style,
    analyze_uzbek_ai_style,
    detect_document_language,
    generate_authorship_questions,
)


def test_short_text_is_not_given_a_misleading_score() -> None:
    assessment = analyze_uzbek_ai_style("Bu juda qisqa sinov matni.")

    assert assessment.score is None
    assert "qisqa" in assessment.verdict.casefold()
    assert assessment.supported is False


def test_repetitive_template_text_is_flagged_only_as_style_risk() -> None:
    sentence = (
        "Bugungi kunda ta'kidlash joizki, zamonaviy dunyoda bu masala muhim ahamiyat kasb etadi."
    )
    assessment = analyze_uzbek_ai_style(" ".join([sentence] * 20))

    assert assessment.score is not None
    assert assessment.score >= 70
    assert "mualliflikni tekshiring" in assessment.verdict
    assert "isbotlamaydi" in assessment.disclaimer


def test_authorship_questions_are_generated_from_document() -> None:
    text = (
        "O‘zbekiston hududlarida raqamli xizmatlarning rivojlanishi fuqarolarga "
        "davlat xizmatlaridan tezroq va qulayroq foydalanish imkonini bermoqda. "
        "Tadqiqot natijalariga ko‘ra, mobil ilovalar navbatlarni qisqartirishga "
        "hamda tashkilotlarning ish jarayonini ochiqroq qilishga yordam beradi."
    )

    questions = generate_authorship_questions(text)

    assert 1 <= len(questions) <= 3
    assert questions[0].endswith("tushuntiring.")
    assert any("oddiy misol" in question for question in questions[1:])


def test_language_detection_separates_english_and_uzbek() -> None:
    english = (
        "This research examines the impact of digital services on education and the "
        "methods that are used by universities for academic assessment. "
    ) * 15
    uzbek = (
        "Bu tadqiqot ta’lim uchun raqamli xizmatlarning ahamiyatini va universitetlar "
        "tomonidan qo‘llanadigan akademik baholash usullarini o‘rganadi. "
    ) * 15

    assert detect_document_language(english) == "en"
    assert detect_document_language(uzbek) == "uz"


def test_english_document_waits_for_external_ai_detector() -> None:
    english = (
        "The study explains how the model is evaluated and why the results are relevant "
        "for institutions that use automated academic tools. "
    ) * 15

    assessment = analyze_document_ai_style(english)

    assert assessment.language == "en"
    assert assessment.score is None
    assert assessment.provider == "Quetext AI Detector"
    assert "kutilmoqda" in assessment.verdict.casefold()
