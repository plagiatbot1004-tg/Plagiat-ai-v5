from pathlib import Path

import pytest

from app.services.extractor import ExtractionError, extract_text, normalize_text


def test_normalize_uzbek_apostrophes() -> None:
    assert normalize_text("O‘zbek  OʻZBEK o'zbEk!") == "o'zbek o'zbek o'zbek"


@pytest.mark.asyncio
async def test_extract_utf8_txt(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    content = " ".join(f"sinov{i}" for i in range(25))
    path.write_text(content, encoding="utf-8")
    assert await extract_text(path, ".txt") == content


@pytest.mark.asyncio
async def test_reject_too_short_text(tmp_path: Path) -> None:
    path = tmp_path / "short.txt"
    path.write_text("juda qisqa matn", encoding="utf-8")
    with pytest.raises(ExtractionError):
        await extract_text(path, ".txt")
