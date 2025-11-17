#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF/HTML report generator with Cyrillic support for xhtml2pdf (pisa) on Windows.

 - Используем локальный шрифт backend/report/fonts/DejaVuSans.ttf.
 - Временные файлы pisa складываются в ws/exports/tmp_pisa с максимально широкими правами.
"""

from __future__ import annotations
import asyncio
import os
import stat
from pathlib import Path
from typing import Any, Dict, Literal

from jinja2 import Environment, FileSystemLoader, select_autoescape

# ---------------- PDF engines ----------------
_HAS_WEASY = False
try:
    from weasyprint import HTML as WeasyHTML  # type: ignore
    _HAS_WEASY = True
except Exception:
    _HAS_WEASY = False

_HAS_PISA = False
try:
    from xhtml2pdf import pisa  # type: ignore
    _HAS_PISA = True
except Exception:
    _HAS_PISA = False


# ---------------- Jinja env ----------------
def _env() -> Environment:
    here = Path(__file__).resolve().parent
    templates = here / "templates"
    return Environment(
        loader=FileSystemLoader(str(templates)),
        autoescape=select_autoescape(["html"]),
    )


def render_report_html(context: Dict[str, Any]) -> str:
    env = _env()
    tpl = env.get_template("report.html")
    return tpl.render(**context)


def _export_dir(ws: str) -> Path:
    d = Path(ws) / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------- Fonts ----------------
def _font_dir() -> Path:
    return Path(__file__).resolve().parent / "fonts"


def _font_file() -> Path:
    """
    Единственный используемый шрифт.
    Переименуй здесь, если у тебя другое имя файла.
    """
    p = _font_dir() / "DejaVuSans.ttf"
    if not p.is_file():
        raise FileNotFoundError(f"Font not found: {p}")
    return p


def _font_css_for_pisa(family: str = "ReportSans") -> str:
    """
    CSS для @font-face: pisa видит url('DejaVuSans.ttf'),
    а link_callback отдаёт ему абсолютный путь.
    """
    font_path = _font_file()
    rel_name = font_path.name

    return f"""
    <style>
    /* DEBUG: using font file {font_path} */
    @font-face {{
        font-family: '{family}';
        src: url('{rel_name}');
        font-weight: normal;
        font-style: normal;
    }}
    body, p, span, div, td, th, h1, h2, h3, h4, h5, h6 {{
        font-family: '{family}', sans-serif !important;
    }}
    </style>
    """


# ---------------- Low-level helpers ----------------
def _ensure_world_writable(path: Path) -> None:
    """
    На Windows/Unix делаем папку/файл максимально доступными.
    """
    try:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
    except Exception:
        # Не критично, продолжаем
        pass


# ---------------- Blocking PDF calls ----------------
def _weasy_pdf_blocking(html: str, out_path: Path) -> None:
    if not _HAS_WEASY:
        raise RuntimeError("WeasyPrint is not available")
    base_url = _font_dir().as_uri() + "/"
    WeasyHTML(string=html, base_url=base_url).write_pdf(target=str(out_path))


def _pisa_pdf_blocking(html: str, out_path: Path, tmp_dir: Path) -> None:
    if not _HAS_PISA:
        raise RuntimeError("xhtml2pdf (pisa) is not available")

    # Готовим tmp_dir и делаем максимально доступным
    tmp_dir.mkdir(parents=True, exist_ok=True)
    _ensure_world_writable(tmp_dir)

    # Принудительно направляем TEMP/TMP/TMPDIR в этот каталог
    old_env = {
        "TEMP": os.environ.get("TEMP"),
        "TMP": os.environ.get("TMP"),
        "TMPDIR": os.environ.get("TMPDIR"),
    }
    os.environ["TEMP"] = str(tmp_dir)
    os.environ["TMP"] = str(tmp_dir)
    os.environ["TMPDIR"] = str(tmp_dir)

    fonts_dir = _font_dir()

    def link_callback(uri: str, rel: str) -> str:
        """
        Делает так, чтобы 'DejaVuSans.ttf' и прочее
        резолвилось в реальные пути.
        """
        # 1) файл в папке fonts
        candidate = fonts_dir / uri
        if candidate.is_file():
            return str(candidate.resolve())

        # 2) абсолютный путь
        if os.path.isabs(uri) and os.path.exists(uri):
            return uri

        # 3) относительный к rel
        guess = Path(rel).parent / uri
        if guess.is_file():
            return str(guess.resolve())

        return uri

    try:
        with open(out_path, "wb") as f:
            pdf = pisa.CreatePDF(
                src=html,
                dest=f,
                encoding="utf-8",
                link_callback=link_callback,
            )

            # После работы pisa делаем все .ttf в tmp_dir доступными (на всякий случай)
            for ttf in tmp_dir.glob("*.ttf"):
                _ensure_world_writable(ttf)

            if pdf.err:
                raise RuntimeError(f"xhtml2pdf failed (err={pdf.err})")

    finally:
        # Восстановить окружение
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------------- Public async API ----------------
async def async_generate_report(
    ws: str,
    context: Dict[str, Any],
    mode: Literal["pdf", "html"] = "pdf",
    engine: str = "auto",
) -> Dict[str, Any]:
    """
    Generate a report.

    engine: "auto" | "weasyprint" | "pisa" | "html"
    """
    html = render_report_html(context)

    if mode == "html":
        return {"html": html}

    out_dir = _export_dir(ws)
    out_path = out_dir / "report.pdf"
    html_path = out_dir / "report.html"
    tmp_dir = out_dir / "tmp_pisa"

    # Вставляем CSS со шрифтом
    html_to_use = html
    try:
        font_css = _font_css_for_pisa(family="ReportSans")
        lower = html_to_use.lower()
        idx = lower.rfind("</head>")
        if idx != -1:
            html_to_use = html_to_use[:idx] + font_css + html_to_use[idx:]
        else:
            html_to_use = font_css + html_to_use
    except Exception as e:
        html_to_use += f"\n<!-- font injection error: {e} -->\n"

    # Сохраняем HTML для отладки
    html_path.write_text(html_to_use, encoding="utf-8")

    loop = asyncio.get_running_loop()

    # Выбор движка
    engines_to_try: list[str] = []
    if engine == "auto":
        # Для кириллицы с pisa — сначала pisa
        if _HAS_PISA:
            engines_to_try.append("pisa")
        if _HAS_WEASY:
            engines_to_try.append("weasyprint")
    else:
        engines_to_try = [engine]

    if not engines_to_try:
        raise RuntimeError(
            "No PDF engine available. Install one of:\n"
            " - xhtml2pdf (pip install xhtml2pdf)\n"
            " - WeasyPrint (pip install weasyprint)\n"
            f"Saved HTML to: {html_path}"
        )

    last_exc: Exception | None = None
    tried: list[tuple[str, str]] = []

    for eng in engines_to_try:
        try:
            if eng == "weasyprint":
                await loop.run_in_executor(None, _weasy_pdf_blocking, html_to_use, out_path)
            elif eng == "pisa":
                await loop.run_in_executor(
                    None,
                    _pisa_pdf_blocking,
                    html_to_use,
                    out_path,
                    tmp_dir,
                )
            else:
                raise RuntimeError(f"Unknown engine requested: {eng}")

            size = out_path.stat().st_size if out_path.exists() else 0
            return {"path": str(out_path), "size_bytes": size}

        except Exception as e:
            tried.append((eng, str(e)))
            last_exc = e

    raise RuntimeError(
        "All PDF engines failed.\n"
        f"Tried: {tried}\n"
        f"Saved HTML to: {html_path}\n"
        f"Last error: {last_exc}"
    )