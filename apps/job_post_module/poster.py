"""
Job Post Poster Generator – HTML/CSS template rendered to JPG.

Why HTML/CSS over Pillow:
  * Pixel-perfect typography (real font kerning, line-breaks, gradients)
  * Maintainable: the look is editable as one inline template instead
    of dozens of draw.text() coordinates
  * Easy to add: backgrounds, shadows, rounded corners, blend modes

Why Playwright over wkhtmltoimage:
  * Modern CSS support (Grid, Flexbox, gradients, shadows, mix-blend-mode)
  * Reliable cross-platform install via `playwright install chromium`
  * Same engine produces the same output everywhere

Output: a 1080×1350 JPG (portrait, LinkedIn/Facebook-friendly) saved
to outputs/job_posts/<slug>.jpg. Not sent to WhatsApp — the operator
opens the file from disk and posts it manually.
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
# All colors live here so they're trivial to retune to match a
# different brand without touching the layout.
COLOR_PRIMARY = "#1E40AF"   # deep brand blue
COLOR_ACCENT  = "#3B82F6"   # lighter blue for accents
COLOR_DARK    = "#0F172A"   # near-black for the title
COLOR_MUTED   = "#475569"   # for taglines / labels

# Canvas
W, H = 1080, 1350


# ── Logo handling ──────────────────────────────────────────────────
# The brand logo lives in assets/. If it has a JPEG-style flat
# background (white or black), we run it through a one-time
# transparency cleanup before embedding so it sits naturally on the
# poster's gradient.
def _logo_path() -> Optional[str]:
    """Locate the brand logo file under settings.BASE_DIR/assets/."""
    candidates = [
        "talentracker_logo.png",
        "talentracker_logo.jpg",
        "logo.png",
        "logo.jpg",
    ]
    base = getattr(settings, "BASE_DIR", None)
    if base is None:
        return None
    for name in candidates:
        p = os.path.join(str(base), "assets", name)
        if os.path.isfile(p):
            return p
    return None


def _logo_data_uri() -> str:
    """Return logo as a base64 data URI with background removed."""
    path = _logo_path()
    if not path:
        return ""
    # Load + auto-remove flat background.
    img = Image.open(path).convert("RGBA")
    w, h = img.size
    # Sample corners to detect bg color (assume corners are bg).
    corners = [img.getpixel((0, 0)), img.getpixel((w - 1, 0)),
               img.getpixel((0, h - 1)), img.getpixel((w - 1, h - 1))]
    avg_brightness = sum((r + g + b) / 3 for r, g, b, _ in corners) / 4

    pixels = img.load()
    if avg_brightness < 60:
        # Dark background → kill near-black pixels.
        for y in range(h):
            for x in range(w):
                r, g, b, a = pixels[x, y]
                if (r + g + b) / 3 < 30:
                    pixels[x, y] = (255, 255, 255, 0)
    elif avg_brightness > 200:
        # Light background → kill near-white pixels.
        for y in range(h):
            for x in range(w):
                r, g, b, a = pixels[x, y]
                if r > 235 and g > 235 and b > 235:
                    pixels[x, y] = (255, 255, 255, 0)
    # Otherwise assume the file already has alpha; leave it alone.

    # Encode to a memory buffer — avoid touching disk so we don't run
    # into Windows file-locking issues (WinError 32) when the same
    # process holds the handle.
    buf = io.BytesIO()
    img.save(buf, "PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


# ── QR code generator ─────────────────────────────────────────────
def _qr_data_uri(target_url: str) -> str:
    qr = segno.make(target_url, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=10, border=2)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _whatsapp_apply_url(job_title: str, phone: str = "8801830225234") -> str:
    msg = f"I saw your {job_title} job post and I'd like to apply."
    return f"https://wa.me/{phone}?text={quote(msg)}"


# ── Bullet extraction (re-used from the old generator) ────────────
_HEADER_MARKERS = (
    "key requirements", "requirements", "responsibilities",
    "core responsibilities", "position overview", "key responsibilities",
    "qualifications", "preferred qualifications",
    "core responsibilities include", "key responsibilities include",
    "responsibilities include", "what you'll do", "candidate profile",
)


def _bullets_from_text(text: str, max_bullets: int = 6) -> List[str]:
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
    what_you_do: List[str],
    candidate_profile: List[str],
    salary: str,
    location: str,
    deadline: str,
    contact_email: str,
    contact_whatsapp: str,
    qr_uri: str,
    logo_uri: str,
) -> str:
    # Escape any user-provided strings that get interpolated into HTML.
    e = html.escape
    do_li     = "".join(f"<li>{e(x)}</li>" for x in what_you_do)
    profile_li = "".join(f"<li>{e(x)}</li>" for x in candidate_profile)

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    width: {W}px; height: {H}px;
    font-family: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    color: {COLOR_DARK};
    background:
      radial-gradient(circle at 90% 10%, rgba(59,130,246,0.18) 0%, transparent 50%),
      radial-gradient(circle at 10% 90%, rgba(30,64,175,0.12) 0%, transparent 50%),
      linear-gradient(180deg, #f0f7ff 0%, #ffffff 60%);
    padding: 60px 70px;
    overflow: hidden;
    position: relative;
  }}
  .hiring-pill {{
    display: inline-block;
    background: {COLOR_PRIMARY};
    color: white;
    padding: 8px 24px;
    border-radius: 999px;
    font-size: 20px;
    font-weight: 700;
    letter-spacing: 6px;
    text-transform: uppercase;
  }}
  h1 {{
    font-size: 64px;
    line-height: 1.08;
    margin-top: 24px;
    color: {COLOR_DARK};
    font-weight: 900;
    letter-spacing: -1.5px;
    max-width: 920px;
  }}
  .tagline {{
    font-size: 22px;
    color: {COLOR_MUTED};
    margin-top: 18px;
    max-width: 720px;
    line-height: 1.4;
  }}
  .body-grid {{
    display: grid;
    grid-template-columns: 1fr 320px;
    gap: 50px;
    margin-top: 50px;
  }}
  .sections {{ display: flex; flex-direction: column; gap: 32px; }}
  .section-head {{
    font-size: 24px;
    font-weight: 800;
    color: {COLOR_PRIMARY};
    margin-bottom: 14px;
    display: flex;
    align-items: center;
    gap: 12px;
  }}
  .section-head::before {{
    content: "";
    display: inline-block;
    width: 6px;
    height: 26px;
    background: {COLOR_ACCENT};
    border-radius: 3px;
  }}
  ul {{
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }}
  li {{
    font-size: 20px;
    line-height: 1.4;
    color: #1f2937;
    padding-left: 26px;
    position: relative;
  }}
  li::before {{
    content: "";
    width: 8px; height: 8px;
    background: {COLOR_ACCENT};
    border-radius: 50%;
    position: absolute;
    left: 0; top: 12px;
  }}
  .qr-card {{
    background: white;
    border-radius: 18px;
    box-shadow: 0 8px 32px rgba(30,64,175,0.18);
    padding: 24px;
    text-align: center;
    align-self: start;
    border: 2px solid {COLOR_PRIMARY};
  }}
  .qr-card .apply {{
    font-size: 22px;
    font-weight: 800;
    color: {COLOR_PRIMARY};
    margin-bottom: 14px;
    letter-spacing: 1px;
  }}
  .qr-card img.qr {{ width: 220px; height: 220px; display: block; margin: 0 auto; }}
  .qr-card .qr-help {{
    font-size: 13px;
    color: #64748b;
    margin-top: 12px;
    line-height: 1.35;
  }}
  .meta {{
    display: flex;
    gap: 50px;
    margin-top: 50px;
    padding: 24px 32px;
    background: rgba(255,255,255,0.7);
    border-radius: 14px;
    border-left: 6px solid {COLOR_PRIMARY};
  }}
  .meta-item .label {{
    font-size: 13px;
    color: #64748b;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
  }}
  .meta-item .value {{
    font-size: 19px;
    color: {COLOR_DARK};
    font-weight: 700;
    margin-top: 4px;
  }}
  .footer {{
    position: absolute;
    bottom: 50px;
    left: 70px;
    right: 70px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  .footer img.logo {{ height: 56px; }}
  .footer .contact {{
    font-size: 16px;
    color: {COLOR_MUTED};
    text-align: right;
    line-height: 1.5;
  }}
  .footer .contact strong {{ color: {COLOR_PRIMARY}; }}
  .no-logo-text {{
    font-size: 28px;
    font-weight: 900;
    color: {COLOR_PRIMARY};
    letter-spacing: -0.5px;
  }}
</style></head>
<body>
  <span class="hiring-pill">We're Hiring</span>
  <h1>{e(job_title)}</h1>
  {f'<p class="tagline">{e(tagline)}</p>' if tagline else ""}

  <div class="body-grid">
    <div class="sections">
      <div>
        <div class="section-head">What you'll do</div>
        <ul>{do_li}</ul>
      </div>
      <div>
        <div class="section-head">Candidate profile</div>
        <ul>{profile_li}</ul>
      </div>
    </div>

    <div class="qr-card">
      <div class="apply">APPLY NOW</div>
      <img class="qr" src="{qr_uri}" alt="QR">
      <div class="qr-help">Scan to apply via WhatsApp</div>
    </div>
  </div>

  <div class="meta">
    <div class="meta-item">
      <div class="label">Salary</div>
      <div class="value">{e(salary)}</div>
    </div>
    <div class="meta-item">
      <div class="label">Location</div>
      <div class="value">{e(location)}</div>
    </div>
    <div class="meta-item">
      <div class="label">Deadline</div>
      <div class="value">{e(deadline)}</div>
    </div>
  </div>

  <div class="footer">
    {f'<img class="logo" src="{logo_uri}" alt="{e(company_name)}">'
     if logo_uri else
     f'<div class="no-logo-text">{e(company_name)}</div>'}
    <div class="contact">
      <strong>{e(contact_email)}</strong><br>
      WhatsApp: {e(contact_whatsapp)}
    </div>
  </div>
</body></html>"""


# ── Public API ────────────────────────────────────────────────────
def generate_job_poster(
    job_title: str,
    company_name: str = "",
    requirements_text: str = "",
    responsibilities_text: str = "",
    tagline: str = "",
    salary: str = "Negotiable",
    location: str = "Dhaka, Bangladesh",
    deadline: str = "Open until filled",
    contact_email: str = "career@talentracker.com.bd",
    contact_whatsapp: str = "+880 1830 225234",
    output_path: str = "",
) -> str:
    """Render a recruitment poster JPG and return its filesystem path.

    No WhatsApp send happens here. The image is saved to disk under
    outputs/job_posts/<slug>.jpg (or to `output_path` if given) so
    the operator can open and post it manually.
    """
    company = company_name or getattr(settings, "COMPANY_NAME", "Company")

    # Extract bullet points.
    do_bullets      = _bullets_from_text(responsibilities_text, max_bullets=5)
    profile_bullets = _bullets_from_text(requirements_text,     max_bullets=5)

    if not do_bullets:
        do_bullets = ["See the full description in the message."]
    if not profile_bullets:
        profile_bullets = ["See the full description in the message."]

    # QR + logo data URIs.
    qr_uri   = _qr_data_uri(_whatsapp_apply_url(job_title))
    logo_uri = _logo_data_uri()

    html_doc = _build_html(
        job_title=job_title,
        tagline=tagline,
        company_name=company,
        what_you_do=do_bullets,
        candidate_profile=profile_bullets,
        salary=salary,
        location=location,
        deadline=deadline,
        contact_email=contact_email,
        contact_whatsapp=contact_whatsapp,
        qr_uri=qr_uri,
        logo_uri=logo_uri,
    )

    # Output path.
    if not output_path:
        out_dir = os.path.join(settings.OUTPUT_DIR, "job_posts")
        os.makedirs(out_dir, exist_ok=True)
        safe = "".join(c for c in job_title if c.isalnum() or c in " _-")
        safe = safe.strip().replace(" ", "_")[:60] or "job_post"
        output_path = os.path.join(out_dir, f"{safe}.jpg")
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    # Render via headless Chromium. Capture the screenshot as bytes
    # (no intermediate file) so Windows file-locking can't bite us.
    # PNG bytes → Pillow → JPEG bytes → write final file once.
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": W, "height": H})
            page.set_content(html_doc, wait_until="load")
            png_bytes = page.screenshot(type="png", full_page=False)
        finally:
            browser.close()

    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    img.save(output_path, "JPEG", quality=92, optimize=True)

    logger.info("Job poster generated: %s", output_path)
    return output_path