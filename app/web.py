import hmac
from html import escape

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import Certificate


def _verification_html(certificate: Certificate, *, valid: bool) -> str:
    status_label = "SERTIFIKAT AMALDA" if valid else "SERTIFIKAT AMALDA EMAS"
    status_color = "#15803d" if valid else "#b91c1c"
    issued = certificate.issued_at.strftime("%Y-%m-%d %H:%M UTC")
    ai_text = (
        "Baholanmagan"
        if certificate.ai_style_score is None
        else f"{certificate.ai_style_score:.2f}%"
    )
    return f"""<!doctype html>
<html lang="uz">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>PlagiAI sertifikat verifikatsiyasi</title>
  <style>
    body {{ margin:0; font-family:Inter,Arial,sans-serif; background:#071426; color:#e2e8f0; }}
    .wrap {{ max-width:880px; margin:0 auto; padding:32px 18px; }}
    .card {{ background:#0d213c; border:1px solid #254466; border-radius:22px; padding:28px; box-shadow:0 24px 60px rgba(0,0,0,.28); }}
    .brand {{ font-size:14px; letter-spacing:.18em; color:#67e8f9; font-weight:800; }}
    h1 {{ font-size:30px; margin:8px 0 6px; }}
    .status {{ display:inline-block; padding:8px 14px; border-radius:999px; background:{status_color}; color:white; font-weight:800; margin:12px 0 24px; }}
    .grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }}
    .item {{ background:#0a192d; border:1px solid #1e3a5f; border-radius:14px; padding:15px; }}
    .label {{ color:#94a3b8; font-size:12px; text-transform:uppercase; letter-spacing:.08em; }}
    .value {{ margin-top:6px; font-size:17px; font-weight:700; overflow-wrap:anywhere; }}
    .metrics {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:22px 0; }}
    .metric {{ text-align:center; background:#102a47; border-radius:14px; padding:16px 8px; }}
    .metric b {{ display:block; font-size:24px; }}
    .note {{ margin-top:20px; color:#94a3b8; line-height:1.55; font-size:13px; }}
    @media (max-width:680px) {{ .grid,.metrics {{ grid-template-columns:1fr; }} h1 {{ font-size:24px; }} }}
  </style>
</head>
<body><main class="wrap"><section class="card">
  <div class="brand">PLAGIAI • ACADEMIC INTEGRITY</div>
  <h1>Hujjat tekshiruvi sertifikati</h1>
  <div class="status">{status_label}</div>
  <div class="metrics">
    <div class="metric"><b>{certificate.originality_score:.2f}%</b><span>Originallik</span></div>
    <div class="metric"><b>{certificate.similarity_score:.2f}%</b><span>O‘xshashlik</span></div>
    <div class="metric"><b>{certificate.source_count}</b><span>Manbalar</span></div>
    <div class="metric"><b>{ai_text}</b><span>AI ehtimoli</span></div>
  </div>
  <div class="grid">
    <div class="item"><div class="label">Sertifikat ID</div><div class="value">{escape(certificate.certificate_number)}</div></div>
    <div class="item"><div class="label">Berilgan vaqt</div><div class="value">{issued}</div></div>
    <div class="item"><div class="label">Hujjat</div><div class="value">{escape(certificate.document_name)}</div></div>
    <div class="item"><div class="label">Qabul qiluvchi</div><div class="value">{escape(certificate.recipient_name or 'Telegram foydalanuvchisi')}</div></div>
    <div class="item"><div class="label">Provayder</div><div class="value">{escape(certificate.provider)}</div></div>
    <div class="item"><div class="label">So‘zlar</div><div class="value">{certificate.word_count:,}</div></div>
    <div class="item" style="grid-column:1/-1"><div class="label">SHA-256 hujjat xeshi</div><div class="value">{escape(certificate.document_hash)}</div></div>
  </div>
  <p class="note">Bu sahifa PlagiAI bazasidagi sertifikat yozuvini jonli tekshiradi. O‘xshashlik foizi plagiat bo‘yicha yakuniy akademik hukm emas; iqtiboslar va kontekst ekspert tomonidan baholanadi.</p>
</section></main></body></html>"""


def create_web_app(
    *,
    settings: Settings | None = None,
    session_maker: async_sessionmaker[AsyncSession] | None = None,
) -> FastAPI:
    app = FastAPI(title="PlagiAI Health", docs_url=None, redoc_url=None)

    @app.get("/")
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "PlagiAI Bot",
            "provider": "Quetext",
        }

    @app.get("/verify/{certificate_number}", response_class=HTMLResponse)
    async def verify_certificate_page(
        certificate_number: str,
        token: str = Query(min_length=20, max_length=160),
    ) -> HTMLResponse:
        if settings is None or session_maker is None:
            raise HTTPException(status_code=503, detail="Verifikatsiya xizmati sozlanmagan.")
        async with session_maker() as session:
            certificate = await session.scalar(
                select(Certificate).where(Certificate.certificate_number == certificate_number)
            )
        if certificate is None or not hmac.compare_digest(certificate.verification_token, token):
            raise HTTPException(status_code=404, detail="Sertifikat topilmadi yoki token noto‘g‘ri.")
        valid = certificate.status == "active" and certificate.revoked_at is None
        return HTMLResponse(_verification_html(certificate, valid=valid), status_code=200)

    @app.get("/api/verify/{certificate_number}")
    async def verify_certificate_api(
        certificate_number: str,
        token: str = Query(min_length=20, max_length=160),
    ) -> dict[str, object]:
        if settings is None or session_maker is None:
            raise HTTPException(status_code=503, detail="Verifikatsiya xizmati sozlanmagan.")
        async with session_maker() as session:
            certificate = await session.scalar(
                select(Certificate).where(Certificate.certificate_number == certificate_number)
            )
        if certificate is None or not hmac.compare_digest(certificate.verification_token, token):
            raise HTTPException(status_code=404, detail="Sertifikat topilmadi yoki token noto‘g‘ri.")
        valid = certificate.status == "active" and certificate.revoked_at is None
        return {
            "valid": valid,
            "certificate_number": certificate.certificate_number,
            "status": certificate.status,
            "document_name": certificate.document_name,
            "document_hash": certificate.document_hash,
            "word_count": certificate.word_count,
            "originality_score": certificate.originality_score,
            "similarity_score": certificate.similarity_score,
            "source_count": certificate.source_count,
            "provider": certificate.provider,
            "issued_at": certificate.issued_at.isoformat(),
        }

    return app
