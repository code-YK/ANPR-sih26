import os

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, Response
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_service import AuthContext, authorised_departments, get_current_auth
from app.db import get_session
from app.models.camera import Camera
from app.services.gap_analysis import build_gap_analysis_report

router = APIRouter()

_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
_jinja_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), autoescape=True)


async def _load_report(session: AsyncSession, auth: AuthContext):
    stmt = select(Camera)
    allowed = authorised_departments(auth)
    if allowed is not None:
        stmt = stmt.where(Camera.department.in_(allowed))
    cameras = (await session.execute(stmt.order_by(Camera.camera_number))).scalars().all()
    return build_gap_analysis_report(cameras)


@router.get("/gap-analysis")
async def gap_analysis_json(
    auth: AuthContext = Depends(get_current_auth), session: AsyncSession = Depends(get_session)
):
    report = await _load_report(session, auth)
    return {
        "generated_at": report.generated_at,
        "total_cameras": report.total_cameras,
        "capability_gaps": report.capability_gaps,
        "coverage": {
            "covered_districts": report.coverage_covered,
            "uncovered_districts": report.coverage_uncovered_districts,
            "unplaced_camera_count": report.unplaced_camera_count,
        },
        "health_gaps": report.health_gaps,
    }


@router.get("/gap-analysis/export")
async def gap_analysis_export(
    format: str = Query("html", pattern="^(html|pdf)$"),
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    report = await _load_report(session, auth)
    template = _jinja_env.get_template("gap_analysis.html")
    html = template.render(report=report)

    if format == "html":
        return HTMLResponse(content=html)

    from weasyprint import HTML

    pdf_bytes = HTML(string=html, base_url=_TEMPLATE_DIR).write_pdf()
    filename = f"sentinel-gap-analysis-{report.generated_at.strftime('%Y%m%d')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
