import json

import httpx
import pytest

from app.config import Settings
from app.services.quetext import (
    QuetextClient,
    QuetextError,
    _progress_is_complete,
    _result_is_complete,
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
                        "input_text_offset": 17,
                        "input_token_count": 42,
                        "id": "match-1",
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
    assert result.sources[0].input_offset == 17
    assert result.sources[0].matched_text == "Mos kelgan matn"
    assert result.sources[0].match_id == "match-1"


def test_plagiarism_report_keeps_every_returned_match() -> None:
    matches = [
        {
            "input_text_match": f"matching fragment number {index}",
            "input_text_offset": index * 25,
            "input_token_count": 8,
            "percent_similar": 90,
            "source": {"url": f"https://example.com/{index}"},
        }
        for index in range(35)
    ]
    result = parse_plagiarism_report({"status": True, "data": {"score": 42.0, "matches": matches}})

    assert len(result.sources) == 35
    assert result.sources[-1].input_offset is not None


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


def test_progress_parser_accepts_documented_and_compatible_shapes() -> None:
    assert _progress_is_complete({"status": True, "data": [{"Progress": 1, "id": "report-1"}]})
    assert _progress_is_complete({"status": True, "data": {"progress": 100, "status": "completed"}})
    assert not _progress_is_complete(
        {"status": True, "data": [{"Progress": 0.75, "id": "report-1"}]}
    )


def test_result_completion_ignores_intermediate_zero_score() -> None:
    assert not _result_is_complete(
        {
            "status": True,
            "data": {
                "status": "in-progress",
                "percentage": 25,
                "score": 0,
                "matches": [],
            },
        }
    )
    assert not _result_is_complete(
        {
            "status": True,
            "data": {
                "status": "in-progress",
                "percentage": 40,
                "ai_score": "0.00",
            },
        }
    )
    assert _result_is_complete(
        {"status": True, "data": {"status": "completed", "percentage": 100, "score": 0}}
    )


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
                json={
                    "status": True,
                    "data": {
                        "status": "completed",
                        "percentage": 100,
                        "score": 12.5,
                        "matches": [],
                    },
                },
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


async def test_plagiarism_waits_past_intermediate_zero_until_matches_are_final(
    monkeypatch,
) -> None:
    result_reads = 0

    async def no_wait(_: float) -> None:
        return None

    matches = [
        {
            "input_text_match": f"matching fragment {index}",
            "input_text_offset": index * 20,
            "input_token_count": 10,
            "percent_similar": 88,
            "source": {"url": f"https://example.com/source-{index}"},
        }
        for index in range(26)
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal result_reads
        path = request.url.path
        if path == "/api/v2/report/plag-processing":
            result_reads += 1
            if result_reads == 1:
                return httpx.Response(
                    200,
                    json={
                        "status": True,
                        "data": {
                            "status": "in-progress",
                            "percentage": 25,
                            "score": 0,
                            "matches": [],
                        },
                    },
                )
            return httpx.Response(
                200,
                json={
                    "status": True,
                    "data": {
                        "status": "completed",
                        "percentage": 100,
                        "score": 32,
                        "matches": matches,
                    },
                },
            )
        if path == "/api/v2/report-progress/plag-processing":
            return httpx.Response(
                200,
                json={"status": True, "data": [{"Progress": 0.25}]},
            )
        return httpx.Response(404, json={"status": False, "code": 404})

    monkeypatch.setattr("app.services.quetext.asyncio.sleep", no_wait)
    settings = Settings(BOT_TOKEN="123456:TEST", QUETEXT_API_KEY="secret-key")
    client = QuetextClient(settings, transport=httpx.MockTransport(handler))

    result = await client.get_plagiarism_result("plag-processing")

    assert result.similarity == 32
    assert result.originality == 68
    assert len(result.sources) == 26
    assert result_reads == 2


async def test_ai_waits_past_intermediate_zero_until_final_score(monkeypatch) -> None:
    result_reads = 0

    async def no_wait(_: float) -> None:
        return None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal result_reads
        path = request.url.path
        if path == "/api/v2/ai-detect-report/ai-processing":
            result_reads += 1
            if result_reads == 1:
                return httpx.Response(
                    200,
                    json={
                        "status": True,
                        "data": {
                            "status": "in-progress",
                            "percentage": 40,
                            "ai_score": "0.00",
                            "ai_matches": [],
                        },
                    },
                )
            return httpx.Response(
                200,
                json={
                    "status": True,
                    "data": {
                        "status": "completed",
                        "percentage": 100,
                        "ai_score": "3.83",
                        "ai_matches": [],
                    },
                },
            )
        if path == "/api/v2/report-progress/ai-processing":
            return httpx.Response(
                200,
                json={"status": True, "data": [{"Progress": 0.4}]},
            )
        return httpx.Response(404, json={"status": False, "code": 404})

    monkeypatch.setattr("app.services.quetext.asyncio.sleep", no_wait)
    settings = Settings(BOT_TOKEN="123456:TEST", QUETEXT_API_KEY="secret-key")
    client = QuetextClient(settings, transport=httpx.MockTransport(handler))

    result = await client.get_ai_result("ai-processing", language="uz")

    assert result.score == 3.83
    assert result_reads == 2


async def test_client_reads_completed_report_when_progress_is_stale(monkeypatch) -> None:
    result_reads = 0

    async def no_wait(_: float) -> None:
        return None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal result_reads
        path = request.url.path
        if path == "/api/v2/report/report-stale":
            result_reads += 1
            if result_reads == 1:
                return httpx.Response(
                    409,
                    json={
                        "status": False,
                        "code": 409,
                        "message": "Report is still processing.",
                    },
                )
            return httpx.Response(
                200,
                json={
                    "status": True,
                    "data": {
                        "id": "report-stale",
                        "status": "completed",
                        "percentage": 100,
                        "score": 7.5,
                        "matches": [],
                    },
                },
            )
        if path == "/api/v2/report-progress/report-stale":
            return httpx.Response(
                200,
                json={"status": True, "data": [{"Progress": 0.25}]},
            )
        return httpx.Response(404, json={"status": False, "code": 404})

    monkeypatch.setattr("app.services.quetext.asyncio.sleep", no_wait)
    settings = Settings(
        BOT_TOKEN="123456:TEST",
        QUETEXT_API_KEY="secret-key",
    )
    client = QuetextClient(settings, transport=httpx.MockTransport(handler))

    result = await client.get_plagiarism_result("report-stale")

    assert result.similarity == 7.5
    assert result.originality == 92.5
    assert result_reads == 2


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
