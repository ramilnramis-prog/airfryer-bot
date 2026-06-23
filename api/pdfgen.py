"""Сборка PDF из markdown или из рецептов. Кириллица через DejaVu (fpdf2)."""
import re
from fpdf import FPDF
from .config import PDF_FONT, PDF_FONT_BOLD, PHOTOS_DIR
from .posts import load_recipes

# Грубая чистка эмодзи (DejaVu их не рисует -> были бы квадраты)
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "←-⇿⌀-⏿⬀-⯿️‍]"
)


def _clean(s) -> str:
    return _EMOJI.sub("", str(s)).strip()


def _new_pdf() -> FPDF:
    pdf = FPDF(format="A4")
    pdf.add_font("DejaVu", "", PDF_FONT)
    try:
        pdf.add_font("DejaVu", "B", PDF_FONT_BOLD)
    except Exception:
        pass
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("DejaVu", size=12)
    return pdf


def build_markdown_pdf(md: str, out_path) -> None:
    pdf = _new_pdf()
    in_code = False
    for raw in (md or "").splitlines():
        line = _clean(raw.rstrip())
        if line.startswith("```"):
            in_code = not in_code
            continue
        if not line:
            pdf.ln(3)
            continue
        if line.startswith("### "):
            pdf.set_font("DejaVu", "B", 13); pdf.multi_cell(0, 7, line[4:]); pdf.set_font("DejaVu", size=12)
        elif line.startswith("## "):
            pdf.set_font("DejaVu", "B", 15); pdf.multi_cell(0, 8, line[3:]); pdf.set_font("DejaVu", size=12)
        elif line.startswith("# "):
            pdf.set_font("DejaVu", "B", 18); pdf.multi_cell(0, 9, line[2:]); pdf.set_font("DejaVu", size=12)
        elif line.startswith(("- ", "* ")):
            pdf.multi_cell(0, 6, "• " + line[2:].replace("**", ""))
        else:
            pdf.multi_cell(0, 6, line.replace("**", ""))
    pdf.output(str(out_path))


def build_recipes_pdf(recipe_ids, out_path) -> None:
    recipes = load_recipes()
    pdf = _new_pdf()
    pdf.set_font("DejaVu", "B", 18); pdf.multi_cell(0, 10, "Рецепты для аэрогриля")
    pdf.set_font("DejaVu", size=12); pdf.ln(4)

    ids = recipe_ids if recipe_ids else list(range(1, len(recipes) + 1))
    for rid in ids:
        if not isinstance(rid, int) or rid < 1 or rid > len(recipes):
            continue
        r = recipes[rid - 1]
        img = r.get("image", "")
        name = img.split("/")[-1] if img else ""
        p = PHOTOS_DIR / name
        if name and p.exists():
            try:
                pdf.image(str(p), w=80)
                pdf.ln(2)
            except Exception:
                pass
        pdf.set_font("DejaVu", "B", 15); pdf.multi_cell(0, 8, _clean(r.get("title", ""))); pdf.set_font("DejaVu", size=12)
        if r.get("total_time"):
            pdf.multi_cell(0, 6, "Время: " + _clean(r["total_time"]))
        pdf.set_font("DejaVu", "B", 12); pdf.multi_cell(0, 6, "Ингредиенты:"); pdf.set_font("DejaVu", size=12)
        for x in (r.get("ingredients") or []):
            pdf.multi_cell(0, 6, "• " + _clean(x))
        pdf.set_font("DejaVu", "B", 12); pdf.multi_cell(0, 6, "Приготовление:"); pdf.set_font("DejaVu", size=12)
        for i, x in enumerate(r.get("steps") or [], 1):
            pdf.multi_cell(0, 6, f"{i}. " + _clean(x))
        pdf.ln(6)
    pdf.output(str(out_path))
