import asyncio
import logging
import math
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.config import Settings
from app.services.unicode_safety import safe_text

QUETEXT_API_BASE = "https://www.quetext.com/api/v2"
logger = logging.getLogger(__name__)


class QuetextError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: int | str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.data = data or {}

    @property
    def public_message(self) -> str:
        if self.status_code == 401 or self.code == 401:
            return "Quetext API kaliti noto‘g‘ri yoki faol emas."
        if self.status_code == 402 or self.code == 402:
            balance = self.data.get("balance_words")
            needed = self.data.get("needed_words")
            if balance is not None and needed is not None:
                return (
                    "Quetext API krediti yetarli emas "
                    f"(mavjud: {balance} so‘z, kerak: {needed} so‘z)."
                )
            return "Quetext API krediti yetarli emas."
        if self.status_code == 429 or self.code == 429:
            return "Quetext so‘rovlar limiti vaqtincha oshib ketdi."
        if isinstance(self, QuetextTimeoutError):
            return "Quetext tekshiruvi belgilangan vaqt ichida yakunlanmadi."
        return str(self)


class QuetextTimeoutError(QuetextError):
    pass


@dataclass(slots=True)
class InternetSource:
    title: str
    url: str
    matched_words: int
    introduction: str = ""
    kind: str = "internet"
    similarity: float | None = None
    input_offset: int | None = None
    matched_text: str = ""
    match_id: str = ""


@dataclass(slots=True)
class InternetScanResult:
    similarity: float | None
    originality: float | None
    sources: list[InternetSource] = field(default_factory=list)
    status: str = "pending"
    error_message: str | None = None


@dataclass(slots=True)
class ExternalAIAssessment:
    score: float | None
    verdict: str
    reasons: list[str] = field(default_factory=list)
    language: str = "unknown"
    model: str = "Quetext AI Detector"
    confidence: float | None = None


def _number(value: Any, *, percentage: bool = False) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    if percentage and 0 <= parsed <= 1:
        parsed *= 100
    return round(min(100.0, max(0.0, parsed)), 2)


def _response_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise QuetextError("Quetext kutilmagan javob formatini qaytardi.")
    return data


def _status_is_complete(value: Any) -> bool:
    normalized = str(value or "").strip().casefold().replace("_", "-")
    return normalized in {"complete", "completed", "done", "finished"}


def _progress_is_complete(payload: dict[str, Any]) -> bool:
    data = payload.get("data")
    rows: list[dict[str, Any]] = []
    if isinstance(data, list):
        rows = [item for item in data if isinstance(item, dict)]
    elif isinstance(data, dict):
        rows = [data]

    for row in rows:
        if _status_is_complete(row.get("status") or row.get("Status")):
            return True
        raw_progress = (
            row.get("Progress") if row.get("Progress") is not None else row.get("progress")
        )
        try:
            parsed_progress = float(raw_progress)
        except (TypeError, ValueError):
            continue
        # The progress endpoint documents a 0..1 scale, but accepting 100 also
        # keeps the client compatible with percentage-style responses.
        if parsed_progress >= 1.0:
            return True
    return False


def _result_is_complete(payload: dict[str, Any], *, score_field: str) -> bool:
    data = payload.get("data")
    if not isinstance(data, dict):
        return False
    if _status_is_complete(data.get("status") or data.get("Status")):
        return True
    try:
        percentage = float(data.get("percentage"))
    except (TypeError, ValueError):
        percentage = 0.0
    if percentage >= 100:
        return True
    # Quetext documents the final score as null while processing. This fallback
    # handles completed reports whose status/progress fields are omitted.
    return score_field in data and data.get(score_field) is not None


def parse_plagiarism_report(payload: dict[str, Any]) -> InternetScanResult:
    data = _response_data(payload)
    similarity = _number(data.get("score"))
    if similarity is None:
        raise QuetextError("Quetext yakuniy o‘xshashlik foizini qaytarmadi.")
    originality = round(max(0.0, 100.0 - similarity), 2)

    sources: list[InternetSource] = []
    for item in data.get("matches") or []:
        if not isinstance(item, dict):
            continue
        source = item.get("source") or {}
        raw_url = safe_text(source.get("url")).strip()
        parsed_url = urlsplit(raw_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            continue
        matched_words = item.get("input_token_count") or item.get("matched_words") or 0
        try:
            matched_words = max(0, int(matched_words))
        except (TypeError, ValueError):
            matched_words = 0
        matched_text = safe_text(item.get("input_text_match")).strip()
        snippet = safe_text(item.get("highlighted_snippet") or matched_text or "").strip()
        title = safe_text(source.get("title") or parsed_url.netloc or raw_url).strip()
        raw_offset = item.get("input_text_offset")
        try:
            input_offset = max(0, int(raw_offset)) if raw_offset is not None else None
        except (TypeError, ValueError):
            input_offset = None
        sources.append(
            InternetSource(
                title=title[:300],
                url=raw_url,
                matched_words=matched_words,
                introduction=snippet,
                kind="internet",
                similarity=_number(item.get("percent_similar")),
                input_offset=input_offset,
                matched_text=matched_text,
                match_id=safe_text(item.get("id"))[:128],
            )
        )
    sources.sort(
        key=lambda item: (item.matched_words, item.similarity or 0),
        reverse=True,
    )
    return InternetScanResult(
        similarity=similarity,
        originality=originality,
        sources=sources,
        status="completed",
    )


def parse_ai_report(
    payload: dict[str, Any],
    *,
    language: str = "unknown",
) -> ExternalAIAssessment:
    data = _response_data(payload)
    score = _number(data.get("ai_score"))
    if score is None:
        raise QuetextError("Quetext yakuniy AI foizini qaytarmadi.")

    matches: list[tuple[float, str]] = []
    for item in data.get("ai_matches") or []:
        if not isinstance(item, dict):
            continue
        probability = _number(item.get("generated_prob"), percentage=True)
        sentence = safe_text(item.get("sentence")).strip()
        if probability is not None and sentence:
            matches.append((probability, sentence))
    matches.sort(reverse=True, key=lambda item: item[0])
    confidence = matches[0][0] if matches else None

    if score < 20:
        verdict = "AIga o‘xshash matn ulushi past"
    elif score < 50:
        verdict = "AIga o‘xshash qismlar mavjud - mualliflik tekshiruvi tavsiya etiladi"
    else:
        verdict = "AIga o‘xshash matn ulushi yuqori - chuqur tekshiruv zarur"

    reasons = ["Quetext hujjatni umumiy va gaplar kesimida tahlil qildi."]
    for probability, sentence in matches[:3]:
        excerpt = sentence if len(sentence) <= 220 else sentence[:217].rstrip() + "..."
        reasons.append(f"Ehtimoliy AI qismi ({probability:.2f}%): “{excerpt}”")
    if not matches:
        reasons.append("Quetext gaplar kesimidagi alohida AI qismlarini qaytarmadi.")
    return ExternalAIAssessment(
        score=score,
        verdict=verdict,
        reasons=reasons,
        language=language,
        confidence=confidence,
    )


class QuetextClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self._transport = transport

    @property
    def ready(self) -> bool:
        return self.settings.quetext_ready

    @property
    def _headers(self) -> dict[str, str]:
        if not self.settings.quetext_api_key:
            raise QuetextError("QUETEXT_API_KEY kiritilmagan.")
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-Key": self.settings.quetext_api_key,
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        attempts: int = 3,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(
                    base_url=QUETEXT_API_BASE,
                    headers=self._headers,
                    timeout=60,
                    transport=self._transport,
                ) as client:
                    response = await client.request(method, path, json=json_body)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    await asyncio.sleep(1.5 * (2**attempt))
                    continue
                raise QuetextError("Quetext serveriga ulanib bo‘lmadi.") from exc

            try:
                payload = response.json()
            except ValueError:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}

            if (
                response.status_code == 429 or response.status_code >= 500
            ) and attempt + 1 < attempts:
                await asyncio.sleep(1.5 * (2**attempt))
                continue
            if response.is_error or payload.get("status") is False:
                code = payload.get("code", response.status_code)
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                message = str(
                    payload.get("message")
                    or f"Quetext so‘rovi muvaffaqiyatsiz ({response.status_code})."
                )
                raise QuetextError(
                    message[:800],
                    status_code=response.status_code,
                    code=code,
                    data=data,
                )
            return payload
        raise QuetextError("Quetext so‘rovi bajarilmadi.") from last_error

    async def _submit(self, path: str, *, text: str, title: str) -> str:
        if not self.ready:
            raise QuetextError("QUETEXT_API_KEY kiritilmagan.")
        payload = await self._request(
            "POST",
            path,
            json_body={"title": title[:250], "text": text},
        )
        report_id = str(_response_data(payload).get("id") or "").strip()
        if not report_id:
            raise QuetextError("Quetext hisobot ID raqamini qaytarmadi.")
        return report_id

    async def submit_plagiarism(self, *, text: str, title: str) -> str:
        return await self._submit("/report", text=text, title=title)

    async def submit_ai(self, *, text: str, title: str) -> str:
        return await self._submit("/ai-detect-report", text=text, title=title)

    async def _wait_for_result(
        self,
        report_id: str,
        *,
        result_path: str,
        score_field: str,
    ) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.settings.quetext_timeout_seconds
        last_progress_complete = False
        while loop.time() < deadline:
            # Reading the final endpoint as well as the progress endpoint avoids
            # false timeouts when Quetext has completed a report but its progress
            # record is delayed or stale.
            try:
                result_payload = await self._request(
                    "GET",
                    result_path,
                    attempts=2,
                )
            except QuetextError as exc:
                if exc.status_code not in {404, 409, 429, 500, 502, 503, 504}:
                    raise
            else:
                if _result_is_complete(result_payload, score_field=score_field):
                    return result_payload

            try:
                progress_payload = await self._request(
                    "GET",
                    f"/report-progress/{report_id}",
                    attempts=2,
                )
            except QuetextError as exc:
                if exc.status_code not in {404, 409, 429, 500, 502, 503, 504}:
                    raise
            else:
                progress_complete = _progress_is_complete(progress_payload)
                if progress_complete and not last_progress_complete:
                    logger.info("Quetext report %s reached completed progress", report_id)
                last_progress_complete = progress_complete
            await asyncio.sleep(self.settings.quetext_poll_seconds)

        # One last direct read prevents a report that completed on the deadline
        # boundary from being marked as timed out.
        try:
            result_payload = await self._request("GET", result_path, attempts=2)
        except QuetextError as exc:
            if exc.status_code not in {404, 409, 429, 500, 502, 503, 504}:
                raise
        else:
            if _result_is_complete(result_payload, score_field=score_field):
                return result_payload
        raise QuetextTimeoutError("Quetext tekshiruvi belgilangan vaqt ichida yakunlanmadi.")

    async def get_plagiarism_result(self, report_id: str) -> InternetScanResult:
        payload = await self._wait_for_result(
            report_id,
            result_path=f"/report/{report_id}",
            score_field="score",
        )
        return parse_plagiarism_report(payload)

    async def get_ai_result(
        self,
        report_id: str,
        *,
        language: str,
    ) -> ExternalAIAssessment:
        payload = await self._wait_for_result(
            report_id,
            result_path=f"/ai-detect-report/{report_id}",
            score_field="ai_score",
        )
        return parse_ai_report(payload, language=language)
