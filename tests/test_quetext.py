import json

import httpx
import pytest

from app.config import Settings
from app.services.quetext import (
    QuetextClient,
    QuetextError,
    parse_ai_report,
    parse_plagiarism_report,
)


def test_plagiarism_report_parses_score_sources_and_snippets() -> None:
    result = parse_plagiarism_report(
        {
            "status": True,
            "data": {
                "score": 37.25,
                "matches": [
                    {
                        "input_text_match": "Mos kelgan matn",
                        "input_token_count": 42,
                        "percent_similar": 85,
                        "source": {
                            "url": "https://example.uz/article",
                            "title": "Asosiy manba",
                        },
                    },
                    {
                        "input_token_count": 5,
                        "source": {"url": "javascript:alert(1)"},
                    },
                ],
            },
        }
    )

    assert result.similarity == 37.25
    assert result.originality == 62.75
    assert result.status == "completed"
    assert len(result.sources) == 1
    assert result.sources[0].matched_words == 42
    assert result.sources[0].introduction == "Mos kelgan matn"
    assert result.sources[0].similarity == 85


def test_ai_report_parses_sentence_level_probabilities() -> None:
    result = parse_ai_report(
        {
            "status": True,
            "data": {
                "ai_score": "82.50",
                "ai_matches": [
                    {"sentence": "First suspicious sentence.", "generated_prob": 0.91},
                    {"sentence": "Second sentence.", "generated_prob": 0.44},
                ],
            },
        },
        language="en",
    )

    assert result.score == 82.5
    assert result.confidence == 91
    assert result.language == "en"
    assert "yuqori" in result.verdict.casefold()
    assert "91.00%" in result.reasons[1]


async def test_client_uses_api_key_submits_and_polls() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if request.method == "POST" and path == "/api/v2/report":
            return httpx.Response(200, json={"status": True, "data": {"id": "plag-1"}})
        if path == "/api/v2/report-progress/plag-1":
            return httpx.Response(
                200,
                json={"status": True, "data": [{"Progress": 1, "id": "plag-1"}]},
            )
        if path == "/api/v2/report/plag-1":
            return httpx.Response(
                200,
                json={"status": True, "data": {"score": 12.5, "matches": []}},
            )
        return httpx.Response(404, json={"status": False, "code": 404})

    settings = Settings(
        BOT_TOKEN="123456:TEST",
        QUETEXT_API_KEY="secret-key",
    )
    client = QuetextClient(settings, transport=httpx.MockTransport(handler))
    report_id = await client.submit_plagiarism(
        text="This is a sufficiently long test document. " * 5,
        title="paper.docx",
    )
    result = await client.get_plagiarism_result(report_id)

    assert report_id == "plag-1"
    assert result.originality == 87.5
    assert all(request.headers["X-API-Key"] == "secret-key" for request in requests)
    submitted = json.loads(requests[0].content)
    assert submitted["title"] == "paper.docx"
    assert "sufficiently long" in submitted["text"]


async def test_insufficient_credit_error_is_actionable() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            402,
            json={
                "status": False,
                "code": 402,
                "message": "Insufficient API credits.",
                "data": {"balance_words": 120, "needed_words": 450},
            },
        )

    settings = Settings(
        BOT_TOKEN="123456:TEST",
        QUETEXT_API_KEY="secret-key",
    )
    client = QuetextClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(QuetextError) as captured:
        await client.submit_plagiarism(text="test " * 100, title="paper.txt")

    assert captured.value.status_code == 402
    assert "mavjud: 120" in captured.value.public_message
    assert "kerak: 450" in captured.value.public_message
