"""
Pytest configuration for ETAA test suite.
"""
import django
from django.conf import settings


def pytest_configure():
    settings.WHATSAPP_GROUP_JID = "test_group@g.us"
    settings.WHATSAPP_BRIDGE_URL = "http://localhost:3000"
    settings.WHATSAPP_API_TOKEN  = "test-token"
    settings.AUTHORIZED_OPERATORS = {
        "8801700000001": "Test Operator 1",
        "8801700000002": "Test Operator 2",
    }
    settings.CONFIRMATION_TIMEOUT = 300
    settings.EMAIL_TEMPLATES_DIR  = "templates/email_templates"
    settings.OUTPUT_DIR  = "/tmp/etaa_test_outputs"
    settings.CV_TEMP_DIR = "/tmp/etaa_test_cvs"
    settings.CODE_OUT_DIR = "/tmp/etaa_test_code"
    settings.OPENAI_API_KEY   = "sk-test"
    settings.ANTHROPIC_API_KEY = "sk-ant-test"
    settings.PRIMARY_LLM_PROVIDER = "openai"
    settings.COMPANY_NAME = "Test Company"
    settings.CANVA_API_KEY = ""
    settings.CANVA_TEMPLATE_ID = ""
    settings.GIT_SSH_KEY_PATH = ""
