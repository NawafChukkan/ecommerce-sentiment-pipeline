from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..config import load_settings
from .queries import fetch_all, fetch_one, dashboard_payload


settings = load_settings()
app = FastAPI(title=settings.app_name)

base_dir = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(base_dir / "templates"))
app.mount("/static", StaticFiles(directory=str(base_dir / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"app_name": settings.app_name},
    )


@app.get("/api/dashboard")
async def api_dashboard() -> JSONResponse:
    return JSONResponse(dashboard_payload())


@app.get("/api/exports/{table}.csv")
async def export_csv(table: str) -> StreamingResponse:
    allowed = {
        "product_risk_scores": "SELECT * FROM product_risk_scores ORDER BY risk_score DESC, revenue DESC",
        "category_health": "SELECT * FROM category_health ORDER BY revenue DESC",
        "monthly_trends": "SELECT * FROM monthly_trends ORDER BY month",
    }
    if table not in allowed:
        return StreamingResponse(iter([b"Unsupported export table."]), media_type="text/plain", status_code=400)

    rows = fetch_all(allowed[table])
    if not rows:
        return StreamingResponse(iter([b"No data available for export."]), media_type="text/plain", status_code=404)

    def generate():
        import csv
        import io

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        yield output.getvalue().encode("utf-8")

    headers = {"Content-Disposition": f"attachment; filename={table}.csv"}
    return StreamingResponse(generate(), media_type="text/csv", headers=headers)


@app.get("/api/exports/summary.pdf")
async def export_summary_pdf() -> StreamingResponse:
    from io import BytesIO

    overview = fetch_one("SELECT * FROM dashboard_overview LIMIT 1") or {}
    top_risk = fetch_all("SELECT * FROM product_risk_scores ORDER BY risk_score DESC, revenue DESC LIMIT 12")

    buffer = BytesIO()
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        from reportlab.pdfgen import canvas

        pdf = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        y = height - inch

        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(inch, y, settings.app_name)
        y -= 0.4 * inch

        pdf.setFont("Helvetica", 11)
        pdf.drawString(inch, y, f"Latest month: {overview.get('latest_month', 'N/A')}")
        y -= 0.25 * inch
        pdf.drawString(inch, y, f"Active products: {overview.get('active_products', 0)}")
        y -= 0.25 * inch
        pdf.drawString(inch, y, f"Revenue: {overview.get('revenue', 0):,.0f}")
        y -= 0.25 * inch
        pdf.drawString(inch, y, f"Avg sentiment: {overview.get('avg_sentiment', 0):.3f}")
        y -= 0.4 * inch

        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(inch, y, "Top Risk Products")
        y -= 0.25 * inch
        pdf.setFont("Helvetica", 10)

        for row in top_risk:
            line = (
                f"{row.get('product_name', 'Unknown')} | Risk {row.get('risk_score', 0):.1f} | "
                f"Returns {row.get('return_rate', 0):.1%} | Sentiment Δ {row.get('sentiment_delta', 0):.3f}"
            )
            pdf.drawString(inch, y, line)
            y -= 0.2 * inch
            if y < inch:
                pdf.showPage()
                y = height - inch
                pdf.setFont("Helvetica", 10)

        pdf.save()
    except ModuleNotFoundError:
        return StreamingResponse(iter([b"PDF export requires reportlab."]), media_type="text/plain", status_code=500)

    buffer.seek(0)
    headers = {"Content-Disposition": "attachment; filename=dashboard_summary.pdf"}
    return StreamingResponse(buffer, media_type="application/pdf", headers=headers)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
