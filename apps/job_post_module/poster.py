"""
Job Post Poster Generator – HTML/CSS template rendered to JPG.

Theme: matches TalenTracker's branded recruitment poster style.
  * Square 1080×1080 (Facebook / Instagram / LinkedIn safe)
  * Top hero band with blue gradient overlay, "HIRING" letter-spaced
    blue caps, massive black title, italic tagline
  * Right-aligned brand mark in the hero corner
  * 2x2 grid of sections —
      Key Responsibilities | Requirements
      Other Benefits        | Required Skills
  * "Apply Now" cursive script (Google Fonts: Great Vibes)
  * Centered QR code flanked by red Location / Deadline labels
  * Bottom bar: blue gradient with logo right-aligned

Why HTML/CSS over Pillow: real typography, gradients, blur effects,
easy to maintain via one inline template.

Why Playwright: pixel-perfect rendering with modern CSS, including
Google-Fonts loading.

Output: 1080×1080 JPG saved to outputs/job_posts/<slug>.jpg.
No WhatsApp attachment — the operator downloads it manually.
"""

import base64
import html
import io
import logging
import os
from typing import List, Optional
from urllib.parse import quote

import segno
from django.conf import settings
from PIL import Image
from playwright.sync_api import sync_playwright

logger = logging.getLogger("etaa")


# ── Brand palette ──────────────────────────────────────────────────
COLOR_PRIMARY = "#1E40AF"   # deep brand blue (logo / underlines)
COLOR_ACCENT  = "#3B82F6"   # lighter blue (hero gradient)
COLOR_DEEP    = "#0B2C7F"   # darker blue for the bottom bar
COLOR_BLACK   = "#0F172A"   # title color
COLOR_BODY    = "#1F2937"   # body text
COLOR_RED     = "#C53030"   # location / deadline red

# Canvas — square format matches the brand template.
W, H = 1080, 1080


# ── Asset helpers ─────────────────────────────────────────────────
def _project_root() -> Optional[str]:
    base = getattr(settings, "BASE_DIR", None)
    return str(base) if base else None


def _logo_path() -> Optional[str]:
    root = _project_root()
    if not root:
        return None
    for name in ("talentracker_logo.png", "talentracker_logo.jpg",
                 "logo.png", "logo.jpg"):
        p = os.path.join(root, "assets", name)
        if os.path.isfile(p):
            return p
    return None


def _hero_bg_path() -> Optional[str]:
    """Look for a user-provided hero/background image. If absent
    the CSS falls back to a synthesised gradient backdrop, so no
    download is required for the poster to work.
    """
    root = _project_root()
    if not root:
        return None
    for name in ("conference_bg.jpg", "hero_bg.jpg", "hero.jpg",
                 "conference_bg.png", "hero_bg.png"):
        p = os.path.join(root, "assets", name)
        if os.path.isfile(p):
            return p
    return None


def _file_to_data_uri(path: str, mime: str = "image/png") -> str:
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _logo_data_uri() -> str:
    path = _logo_path()
    if not path:
        return ""
    img = Image.open(path).convert("RGBA")
    w, h = img.size
    corners = [img.getpixel((0, 0)), img.getpixel((w - 1, 0)),
               img.getpixel((0, h - 1)), img.getpixel((w - 1, h - 1))]
    avg_brightness = sum((r + g + b) / 3 for r, g, b, _ in corners) / 4
    pixels = img.load()
    if avg_brightness < 60:
        for y in range(h):
            for x in range(w):
                r, g, b, a = pixels[x, y]
                if (r + g + b) / 3 < 30:
                    pixels[x, y] = (255, 255, 255, 0)
    elif avg_brightness > 200:
        for y in range(h):
            for x in range(w):
                r, g, b, a = pixels[x, y]
                if r > 235 and g > 235 and b > 235:
                    pixels[x, y] = (255, 255, 255, 0)

    buf = io.BytesIO()
    img.save(buf, "PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _hero_data_uri() -> str:
    path = _hero_bg_path()
    if not path:
        return ""
    ext = path.lower().rsplit(".", 1)[-1]
    mime = "image/png" if ext == "png" else "image/jpeg"
    return _file_to_data_uri(path, mime=mime)


# ── QR code ───────────────────────────────────────────────────────
def _qr_data_uri(target_url: str) -> str:
    qr = segno.make(target_url, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=10, border=2)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _whatsapp_apply_url(job_title: str, phone: str = "8801830225234") -> str:
    msg = f"I saw your {job_title} job post and I'd like to apply."
    return f"https://wa.me/{phone}?text={quote(msg)}"


# ── Bullet / section parsing ──────────────────────────────────────
_HEADER_MARKERS = (
    "key requirements", "requirements", "responsibilities",
    "core responsibilities", "position overview", "key responsibilities",
    "qualifications", "preferred qualifications",
    "core responsibilities include", "key responsibilities include",
    "responsibilities include", "what you'll do", "candidate profile",
    "key responsibilites",  # tolerate the typo found in some templates
    "other benefits & facilities", "other benefits and facilities",
    "required skills & competencies", "required skills and competencies",
    "skills", "skills & competencies",
)


def _bullets_from_text(text: str, max_bullets: int = 5) -> List[str]:
    if not text:
        return []
    out = []
    for raw in text.replace("\r", "").split("\n"):
        s = raw.strip().lstrip("•-*").lstrip()
        if not s:
            continue
        if len(s) > 2 and s[0].isdigit() and s[1] in (".", ")"):
            s = s[2:].lstrip()
        bare = s.rstrip(":").lower().strip()
        for tail in (" include", " includes", " are"):
            if bare.endswith(tail):
                bare = bare[: -len(tail)].strip()
        if bare in _HEADER_MARKERS:
            continue
        out.append(s)
        if len(out) >= max_bullets:
            break
    return out


# ── HTML builder ──────────────────────────────────────────────────
def _build_html(
    job_title: str,
    tagline: str,
    company_name: str,
    responsibilities: List[str],
    requirements: List[str],
    benefits: List[str],
    skills: List[str],
    location: str,
    deadline: str,
    qr_uri: str,
    logo_uri: str,
    hero_uri: str,
) -> str:
    e = html.escape

    def li_block(items: List[str]) -> str:
        if not items:
            return "<li class='placeholder'>—</li>"
        return "".join(f"<li>{e(it)}</li>" for it in items)

    if hero_uri:
        hero_bg = (
            f"background-image: "
            f"linear-gradient(180deg, rgba(255,255,255,0.45) 0%, "
            f"rgba(240,248,255,0.65) 70%, rgba(240,248,255,0.95) 100%), "
            f"url('{hero_uri}'); "
            f"background-size: cover; background-position: center;"
        )
    else:
        # Synthesised "blurred crowd" backdrop using layered radial
        # gradients. Reads as soft silhouettes when blurred and
        # tinted blue.
        hero_bg = (
            "background-image: "
            "radial-gradient(ellipse 280px 180px at 18% 70%, rgba(30,64,175,0.18) 0%, transparent 70%), "
            "radial-gradient(ellipse 260px 170px at 30% 60%, rgba(30,64,175,0.22) 0%, transparent 70%), "
            "radial-gradient(ellipse 320px 200px at 50% 75%, rgba(30,64,175,0.28) 0%, transparent 70%), "
            "radial-gradient(ellipse 250px 160px at 72% 65%, rgba(30,64,175,0.20) 0%, transparent 70%), "
            "radial-gradient(ellipse 280px 180px at 85% 70%, rgba(30,64,175,0.18) 0%, transparent 70%), "
            "radial-gradient(circle at 90% 10%, rgba(59,130,246,0.20) 0%, transparent 50%), "
            "linear-gradient(180deg, #cfe0f5 0%, #e8f1fb 50%, #ffffff 100%);"
        )

    logo_top_html = (
        f"<img class='logo-top' src='{logo_uri}' alt='{e(company_name)}'>"
        if logo_uri
        else f"<div class='logo-top-text'>{e(company_name)}</div>"
    )
    logo_bottom_html = (
        f"<img class='logo-bottom' src='{logo_uri}' alt='{e(company_name)}'>"
        if logo_uri
        else f"<div class='logo-bottom-text'>{e(company_name)}</div>"
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Great+Vibes&family=Roboto:wght@400;500;700;900&family=Roboto+Slab:wght@700;900&display=swap" rel="stylesheet">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    width: {W}px; height: {H}px;
    font-family: "Roboto", -apple-system, "Segoe UI", sans-serif;
    color: {COLOR_BODY};
    background: #ffffff;
    overflow: hidden;
    position: relative;
  }}

  /* ── Hero band ── */
  .hero {{
    position: relative;
    width: 100%;
    height: 420px;
    {hero_bg}
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 30px 80px 30px;
    text-align: center;
    overflow: hidden;
  }}
  .hero::before {{
    content: "";
    position: absolute;
    inset: 0;
    background:
      linear-gradient(90deg, rgba(30,64,175,0.18) 0%, transparent 18%, transparent 82%, rgba(30,64,175,0.18) 100%);
    pointer-events: none;
  }}
  .logo-top {{
    position: absolute;
    top: 22px;
    right: 28px;
    height: 56px;
    z-index: 5;
  }}
  .logo-top-text {{
    position: absolute;
    top: 22px;
    right: 28px;
    font-weight: 900;
    color: {COLOR_PRIMARY};
    font-size: 18px;
    z-index: 5;
  }}
  .hiring {{
    font-size: 22px;
    font-weight: 700;
    color: {COLOR_PRIMARY};
    letter-spacing: 12px;
    text-transform: uppercase;
    margin-bottom: 10px;
    z-index: 2;
  }}
  h1 {{
    font-family: "Roboto Slab", "Roboto", serif;
    font-weight: 900;
    font-size: 64px;
    line-height: 1.0;
    letter-spacing: 1px;
    color: {COLOR_BLACK};
    text-transform: uppercase;
    text-align: center;
    z-index: 2;
    max-width: 900px;
    text-shadow: 0 2px 6px rgba(255,255,255,0.4);
  }}
  h1.long  {{ font-size: 50px; }}
  h1.xlong {{ font-size: 42px; }}
  .tagline {{
    font-style: italic;
    font-size: 17px;
    line-height: 1.4;
    color: {COLOR_BODY};
    margin-top: 16px;
    max-width: 760px;
    z-index: 2;
  }}
  .tagline strong {{ color: {COLOR_BLACK}; }}

  /* ── Sections grid ── */
  .sections {{
    padding: 28px 60px 0;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 22px 50px;
  }}
  .sec-head {{
    font-size: 22px;
    font-weight: 900;
    color: {COLOR_BLACK};
    margin-bottom: 10px;
    display: inline-block;
    border-bottom: 3px solid {COLOR_PRIMARY};
    padding-bottom: 4px;
  }}
  ul.bullets {{
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding-left: 0;
  }}
  ul.bullets li {{
    font-size: 14.5px;
    line-height: 1.4;
    color: {COLOR_BODY};
    padding-left: 18px;
    position: relative;
    text-align: justify;
  }}
  ul.bullets li::before {{
    content: "•";
    position: absolute;
    left: 0;
    top: 0;
    color: {COLOR_BLACK};
    font-weight: 900;
    font-size: 18px;
  }}
  ul.bullets li.placeholder {{ color: #9ca3af; }}

  /* ── Apply Now + QR row ── */
  .apply-row {{
    position: absolute;
    left: 0; right: 0;
    bottom: 100px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 70px;
  }}
  .meta-left, .meta-right {{
    flex: 1;
    font-size: 18px;
    line-height: 1.3;
  }}
  .meta-left  {{ text-align: left;  }}
  .meta-right {{ text-align: right; }}
  .meta-label {{
    color: {COLOR_RED};
    font-weight: 900;
  }}
  .meta-value {{
    color: {COLOR_BLACK};
    font-weight: 700;
  }}
  .apply-block {{
    text-align: center;
    flex: 0 0 auto;
  }}
  .apply-cursive {{
    font-family: "Great Vibes", cursive;
    font-size: 48px;
    color: {COLOR_PRIMARY};
    line-height: 1;
    margin-bottom: 6px;
  }}
  .qr {{
    width: 130px;
    height: 130px;
    display: block;
    margin: 0 auto;
  }}
  .scan-hint {{
    font-size: 11px;
    color: {COLOR_BODY};
    margin-top: 6px;
  }}
  .scan-hint .underline {{
    color: {COLOR_PRIMARY};
    text-decoration: underline;
    font-weight: 700;
  }}

  /* ── Bottom bar ── */
  .bottom-bar {{
    position: absolute;
    bottom: 0; left: 0; right: 0;
    height: 70px;
    background: linear-gradient(90deg, {COLOR_DEEP} 0%, {COLOR_PRIMARY} 60%, {COLOR_ACCENT} 100%);
    display: flex;
    align-items: center;
    justify-content: flex-end;
    padding: 0 30px;
  }}
  .logo-bottom      {{ height: 42px; }}
  .logo-bottom-text {{ color: white; font-weight: 900; font-size: 20px; }}
</style></head>
<body>
  <div class="hero">
    {logo_top_html}
    <div class="hiring">HIRING</div>
    <h1 class="{
      'xlong' if len(job_title) > 28 else ('long' if len(job_title) > 18 else '')
    }">{e(job_title.upper())}</h1>
    {f'<div class="tagline">{e(tagline)}</div>' if tagline else ""}
  </div>

  <div class="sections">
    <div>
      <div class="sec-head">Key Responsibilities</div>
      <ul class="bullets">{li_block(responsibilities)}</ul>
    </div>
    <div>
      <div class="sec-head">Requirements</div>
      <ul class="bullets">{li_block(requirements)}</ul>
    </div>
    <div>
      <div class="sec-head">Other Benefits &amp; Facilities</div>
      <ul class="bullets">{li_block(benefits)}</ul>
    </div>
    <div>
      <div class="sec-head">Required Skills &amp; Competencies</div>
      <ul class="bullets">{li_block(skills)}</ul>
    </div>
  </div>

  <div class="apply-row">
    <div class="meta-left">
      <span class="meta-label">Location:</span>
      <span class="meta-value">{e(location)}</span>
    </div>
    <div class="apply-block">
      <div class="apply-cursive">Apply Now</div>
      <img class="qr" src="{qr_uri}" alt="QR">
      <div class="scan-hint">Scan to <span class="underline">apply</span> or browse the link from caption.</div>
    </div>
    <div class="meta-right">
      <span class="meta-label">Deadline:</span>
      <span class="meta-value">{e(deadline)}</span>
    </div>
  </div>

  <div class="bottom-bar">
    {logo_bottom_html}
  </div>
</body></html>"""


# ── Public API ────────────────────────────────────────────────────
def generate_job_poster(
    job_title: str,
    company_name: str = "",
    requirements_text: str = "",
    responsibilities_text: str = "",
    benefits_text: str = "",
    skills_text: str = "",
    tagline: str = "",
    location: str = "Dhaka, Bangladesh",
    deadline: str = "Open until filled",
    output_path: str = "",
) -> str:
    """Render a square recruitment poster JPG and return its path.

    No WhatsApp send. The image is saved to disk under
    outputs/job_posts/<slug>.jpg (or `output_path` if given).
    """
    company = company_name or getattr(settings, "COMPANY_NAME", "Company")

    responsibilities = _bullets_from_text(responsibilities_text, max_bullets=5)
    requirements     = _bullets_from_text(requirements_text,     max_bullets=5)
    benefits         = _bullets_from_text(benefits_text,         max_bullets=4)
    skills           = _bullets_from_text(skills_text,           max_bullets=4)

    if not responsibilities:
        responsibilities = ["See the full description in the message."]
    if not requirements:
        requirements = ["See the full description in the message."]
    if not benefits:
        benefits = ["Competitive compensation package",
                    "Career growth opportunities",
                    "Supportive work environment"]
    if not skills:
        skills = ["Strong communication and interpersonal skills",
                  "Strategic thinking and problem-solving",
                  "Team collaboration and leadership"]

    qr_uri   = _qr_data_uri(_whatsapp_apply_url(job_title))
    logo_uri = _logo_data_uri()
    hero_uri = _hero_data_uri()

    html_doc = _build_html(
        job_title=job_title,
        tagline=tagline,
        company_name=company,
        responsibilities=responsibilities,
        requirements=requirements,
        benefits=benefits,
        skills=skills,
        location=location,
        deadline=deadline,
        qr_uri=qr_uri,
        logo_uri=logo_uri,
        hero_uri=hero_uri,
    )

    if not output_path:
        out_dir = os.path.join(settings.OUTPUT_DIR, "job_posts")
        os.makedirs(out_dir, exist_ok=True)
        safe = "".join(c for c in job_title if c.isalnum() or c in " _-")
        safe = safe.strip().replace(" ", "_")[:60] or "job_post"
        output_path = os.path.join(out_dir, f"{safe}.jpg")
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    # Render headless. Wait for the network so Google Fonts load
    # before the screenshot (the "Apply Now" script font depends
    # on it).
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": W, "height": H})
            page.set_content(html_doc, wait_until="networkidle")
            page.evaluate("document.fonts && document.fonts.ready")
            png_bytes = page.screenshot(type="png", full_page=False)
        finally:
            browser.close()

    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    img.save(output_path, "JPEG", quality=92, optimize=True)

    logger.info("Job poster generated: %s", output_path)
    return output_path