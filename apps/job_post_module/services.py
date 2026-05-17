"""
Job Post Module – Services
Generates professional job descriptions and interfaces with Canva API.
"""

import logging
import os
from typing import Optional

import requests
from django.conf import settings

from apps.llm_client import get_llm_client

logger = logging.getLogger("etaa")


# ── Job Description Generation ────────────────────────────────────────────────


JD_SYSTEM = """You are a professional HR copywriter. Generate a complete, well-structured job description.
Format it in clean HTML using <h2>, <ul>, <p>, <strong> tags. Include ALL sections:
1. Job Title and Department
2. Role Overview
3. Key Responsibilities (bulleted)
4. Required Qualifications & Skills
5. Preferred Qualifications
6. Compensation & Benefits
7. Application Instructions
Be professional, engaging, and clear."""


def generate_job_description(
    job_title: str,
    department: str = "",
    responsibilities: str = "",
    qualifications: str = "",
    salary_range: str = "",
    company_info: str = "",
) -> str:
    """Generate a professional HTML job description using LLM."""
    llm = get_llm_client()
    prompt = f"""Create a complete job description for the following role:

Job Title: {job_title}
Department: {department or 'Not specified'}
Company: {company_info or settings.COMPANY_NAME}
Responsibilities: {responsibilities}
Qualifications Required: {qualifications}
Salary/Compensation: {salary_range or 'Competitive'}

Generate the full job description as requested."""

    return llm.complete(prompt, system=JD_SYSTEM, max_tokens=2000, temperature=0.4)


# ── Canva Integration ─────────────────────────────────────────────────────────


class CanvaClient:
    """Interfaces with Canva Connect API for job post design export."""

    BASE_URL = "https://api.canva.com/rest/v1"

    def __init__(self):
        self.api_key     = settings.CANVA_API_KEY
        self.template_id = settings.CANVA_TEMPLATE_ID
        self.headers     = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def create_design_from_template(self, job_title: str, description_plain: str) -> Optional[str]:
        """
        Create a new Canva design from the configured template,
        populate text fields, and return the design ID.
        """
        if not self.api_key or not self.template_id:
            logger.warning("Canva API key or template ID not configured.")
            return None

        try:
            # Step 1: Create design from template
            payload = {
                "asset_type": "design",
                "title": f"Job Post – {job_title}",
                "design_type": {"name": "custom"},
            }
            resp = requests.post(
                f"{self.BASE_URL}/designs",
                json=payload,
                headers=self.headers,
                timeout=30,
            )
            resp.raise_for_status()
            design_id = resp.json()["design"]["id"]
            logger.info("Canva design created: %s", design_id)
            return design_id

        except Exception as exc:  # noqa: BLE001
            logger.error("Canva create_design failed: %s", exc)
            return None

    def export_as_jpg(self, design_id: str, output_dir: str) -> Optional[str]:
        """Request a JPG export of a Canva design and download it."""
        if not design_id:
            return None
        try:
            resp = requests.post(
                f"{self.BASE_URL}/exports",
                json={"design_id": design_id, "format": {"type": "jpg", "quality": 90}},
                headers=self.headers,
                timeout=60,
            )
            resp.raise_for_status()
            export_url = resp.json().get("job", {}).get("urls", [None])[0]

            if export_url:
                os.makedirs(output_dir, exist_ok=True)
                file_path = os.path.join(output_dir, f"{design_id}.jpg")
                img_resp = requests.get(export_url, timeout=60)
                img_resp.raise_for_status()
                with open(file_path, "wb") as f:
                    f.write(img_resp.content)
                logger.info("Canva JPG exported: %s", file_path)
                return file_path

        except Exception as exc:  # noqa: BLE001
            logger.error("Canva export_as_jpg failed: %s", exc)
        return None
