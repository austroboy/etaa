# ETAA – Enterprise Task Automation Agent

> A WhatsApp-controlled AI agent for automating enterprise tasks: email, CV ranking, job posting, and software development.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Modules](#modules)
4. [Prerequisites](#prerequisites)
5. [Quick Start](#quick-start)
6. [Configuration](#configuration)
7. [Usage Guide](#usage-guide)
8. [Dynamic Instructions](#dynamic-instructions)
9. [Granting In-Group Access](#granting-in-group-access)
10. [API Reference](#api-reference)
11. [Running Tests](#running-tests)
12. [Deployment](#deployment)
13. [Troubleshooting](#troubleshooting)

---

## Overview

ETAA is a Django-based enterprise automation agent controlled via WhatsApp. Authorized operators send natural-language instructions to a designated WhatsApp group. The system classifies the intent using an LLM (GPT-4o with Claude 3.5 Sonnet fallback), requests confirmation for sensitive operations, and executes the appropriate task asynchronously via Celery.

### Supported Task Types

| Task | WhatsApp Instruction Example |
|------|------------------------------|
| **Outbound Email** | "Send an offer email to rahim@client.com for the web project at 50,000 BDT" |
| **Inbox Monitor** | "Check our inbox and reply to any new emails" |
| **CV Ranking** | "Rank the CVs in the Google Drive folder https://drive.google.com/... for a Django developer role" |
| **Job Post** | "Create a job post for a Senior Software Engineer in the Engineering department" |
| **Code Generation** | "Generate a complete Django project from the attached SRS document" |
| **Dynamic Agent** _(new)_ | "Find the email thread titled 'Backend Hiring Q2', download every CV in it, zip them up, and save the archive to ~/hires/" |

The **Dynamic Agent** is what makes the bot behave like a human assistant rather than a switchboard. Instead of a fixed task list, an LLM-driven tool-use loop composes small tools (filesystem, IMAP search, ZIP, Drive download, email send, WhatsApp send, CV ranking, …) to fulfil any multi-step instruction the operator gives. See [Dynamic Instructions](#dynamic-instructions) below.

### Authorization Model

The bot listens to **two kinds of senders**:

1. **Three core operators** (configured in `.env` via `OPERATOR_1_PHONE` / `2` / `3`) are authorized **everywhere** — DMs to the bot AND every group the bot is in. They are the *only* people who can grant in-group access to others.
2. **Group-delegated members**. Inside any group, a core operator can authorize a new member by saying *"authorize +880…"* or by replying to that person's message with *"authorize this person"*. Their authorization is **scoped to that group only** — they cannot DM the bot, and their access does not extend to other groups.

See [Granting In-Group Access](#granting-in-group-access) below.

---

## Architecture

```
WhatsApp Group
      │
      ▼
┌─────────────────────┐
│  WhatsApp Bridge    │  (Node.js / whatsapp-web.js)
│  bridge/server.js   │
└─────────┬───────────┘
          │ HTTP POST
          ▼
┌─────────────────────┐
│  Django Webhook     │  /api/messaging/webhook/
│  apps/messaging/    │
│   ├─ Auth check     │
│   ├─ Confirm check  │
│   └─ Intent parse   │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐     ┌──────────────────┐
│  Task Dispatcher    │────▶│  Celery Workers  │
│  apps/messaging/    │     │                  │
│  dispatcher.py      │     │  ├─ Email tasks  │
└─────────────────────┘     │  ├─ CV tasks     │
                            │  ├─ Job tasks    │
                            │  └─ Dev tasks    │
                            └────────┬─────────┘
                                     │
                            ┌────────▼─────────┐
                            │  Redis (Broker)  │
                            └──────────────────┘
```

---

## Modules

### 1. Messaging Module (`apps/messaging/`)
- Receives all WhatsApp messages via the bridge webhook
- Validates operator authorization against `AUTHORIZED_OPERATORS`
- Filters messages to the configured group JID only
- Checks for pending confirmation responses before parsing new intents
- Routes to the dispatcher after LLM intent classification

### 2. Email Module (`apps/email_module/`)
- **Outbound**: Selects the best-matching email template, substitutes placeholders, sends via SMTP
- **Inbound**: Polls the inbox via IMAP, uses LLM to draft professional auto-replies
- 5 built-in templates: offer proposal, acceptance confirmation, follow-up, inquiry response, general business
- All outbound emails require operator confirmation before sending

### 3. CV Module (`apps/cv_module/`)
- Collects CVs from a local directory or Google Drive folder
- Extracts text from PDF and DOCX files
- Scores each CV (0–100) against job requirements using LLM
- Packages the top-N ranked CVs + CSV scoring summary into a ZIP file
- Delivers the ZIP to WhatsApp

### 4. Job Post Module (`apps/job_post_module/`)
- Generates a complete, professional HTML job description using LLM
- Integrates with Canva API to produce a designed JPG image
- Sends the text description and image to WhatsApp
- Manual posting step: operator posts the image to LinkedIn/Facebook

### 5. Dev Module (`apps/dev_module/`)
- Parses an SRS document (text or file) to produce a structured project plan
- Generates a complete Django project: models, serializers, views, URLs, admin, settings, Dockerfile, README
- Packages the project into a ZIP and delivers to WhatsApp
- Optionally pushes to a Git repository (requires explicit confirmation)

### 6. Confirmation Module (`apps/confirmation/`)
- Creates pending confirmation records for sensitive operations
- Operator responds with "Yes"/"No" in WhatsApp
- Configurable timeout (default: 5 minutes)
- Stale confirmations auto-expired by Celery Beat

### 7. Logger Module (`apps/logger_module/`)
- Immutable `ActionLog` record for every task (pending → in_progress → success/failed)
- Operator name, phone, instruction, task type, status, output location, error details
- Auto-purge after 90 days via Celery Beat
- Admin panel at `/admin/`

### 8. Authorization Module (`apps/authz/`) _(new)_
- Two-tier authorization model: 3 core operators (everywhere) + per-group delegated members
- `GroupMembership` records the (group, phone) pairs that have been authorized; idempotent grant/revoke API
- `AuthorizationEvent` audit log: every grant, revoke, reactivation, denied attempt
- WhatsApp command parser detects "authorize", "revoke", "list members" inside group chats — including reply-based targeting

### 9. Dynamic Agent Module (`apps/agent/`) _(new)_
- LLM-driven tool-use loop (OpenAI function-calling + Anthropic tool-use, with failover) that handles any free-form instruction that doesn't fit the fixed task types
- Tool catalogue: filesystem ops, IMAP search and attachment download, ZIP creation, Drive download, email send, WhatsApp send, CV ranking, finish
- Sensitive tools (`send_email`, `delete_file`, `move_file`) gated behind operator confirmation
- `AgentRun` and `AgentStep` models track every iteration for full audit
- CLI runner for testing without WhatsApp: `python manage.py run_agent "<instruction>"`

---

## Prerequisites

**Server:**
- Python 3.11+
- Node.js 20+
- Redis 7+
- Git

**External services:**
- OpenAI API key (primary LLM)
- Anthropic API key (fallback LLM — optional but recommended)
- Gmail account with App Password (SMTP + IMAP)
- Google Service Account JSON (for Drive CV collection — optional)
- Canva Connect API key (for job post images — optional)

---

## Quick Start

### 1. Clone & set up Python environment

```bash
git clone <repo-url> etaa
cd etaa
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
nano .env   # Fill in all required values
```

**Minimum required values:**
```
DJANGO_SECRET_KEY=<random 50-char string>
OPENAI_API_KEY=sk-...
SMTP_USER=your@gmail.com
SMTP_PASSWORD=your-app-password
COMPANY_EMAIL=your@gmail.com
COMPANY_NAME=Your Company Name
OPERATOR_1_PHONE=8801700000001
WHATSAPP_GROUP_JID=<your group JID>
WHATSAPP_API_TOKEN=<any secret token>
```

### 3. Set up Django

```bash
mkdir -p outputs/cv_rankings outputs/job_posts outputs/code logs temp/cvs
python manage.py migrate
python manage.py createsuperuser
```

### 4. Start Redis

```bash
redis-server
```

### 5. Start Celery worker

```bash
celery -A etaa_core worker --loglevel=info
```

### 6. Start Django server

```bash
python manage.py runserver
```

### 7. Set up WhatsApp bridge

```bash
cd bridge
npm install
cp ../.env .env     # or set env vars directly
node server.js
```

Scan the QR code that appears in the terminal with your WhatsApp (the operator's phone).

---

## Finding Your WhatsApp Group JID

After the bridge connects, send any message to your group and check the bridge logs:
```
[ETAA Bridge] Message from Zihad (8801700000001): test
```
The group JID appears in the message forwarded to Django. Check Django logs or the `IncomingMessage` records in the admin panel. It will look like `120363XXXXXXXXXXXXXXXX@g.us`.

---

## Configuration

All configuration is via environment variables in `.env`. See `.env.example` for the full list.

| Variable | Required | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | ✅ | Django secret key |
| `OPENAI_API_KEY` | ✅ | OpenAI API key |
| `SMTP_USER` | ✅ | Gmail address for sending emails |
| `SMTP_PASSWORD` | ✅ | Gmail App Password |
| `OPERATOR_1_PHONE` / `2` / `3` | ✅ | The three core operators (digits only, country code included, no `+`) |
| `OPERATOR_1_NAME` / `2` / `3` | ⚪ | Display names for the three operators |
| `CORE_OPERATOR_PHONES` | ✅ | Comma-separated list of the same three numbers, used by the WhatsApp Node bridge to filter DMs at the edge |
| `WHATSAPP_GROUP_JID` | ⚪ | Optional fallback group for unsolicited bot messages (status updates from periodic tasks). Replies always go back to the chat the instruction came from regardless of this value |
| `ANTHROPIC_API_KEY` | ⚪ | Fallback LLM provider |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | ⚪ | For Google Drive CV collection |
| `CANVA_API_KEY` | ⚪ | For Canva job post images |
| `GIT_SSH_KEY_PATH` | ⚪ | SSH key for Git push feature |
| `DATABASE_URL` | ⚪ | PostgreSQL URL (SQLite used if blank) |

---

## Usage Guide

### Sending an Outbound Email

```
Send an offer email to karim@clientcompany.com for the e-commerce website project at 120,000 BDT. 
Valid until 15 May 2026.
```

The agent will:
1. Select the **offer_proposal** template
2. Ask: *"⚠️ Confirmation Required – Send an email to karim@clientcompany.com… Reply Yes to confirm."*
3. On confirmation → send the email → reply *"✅ Email sent to karim@clientcompany.com"*

### Ranking CVs

```
Rank the CVs from this Google Drive folder: https://drive.google.com/drive/folders/ABC123
Job requirements: Senior Django developer, 5+ years Python, PostgreSQL, REST APIs, team lead experience
Top 30 candidates please
```

### Creating a Job Post

```
Create a job post for a Frontend Developer in the Product team.
Requirements: React, TypeScript, 3 years experience.
Salary: 60,000-80,000 BDT.
```

### Generating Code from SRS

```
Generate a complete Django REST API project from this SRS:
[paste SRS text or attach file]
Push to GitHub: https://github.com/myorg/myproject.git
```

### Checking the Inbox

```
Check our inbox and reply to any new emails
```

### Dynamic Instructions

Anything that doesn't fit the fixed task types above goes to the dynamic agent — an LLM tool-use loop that composes small actions to fulfil novel, multi-step requests. You don't need to phrase the request a special way: the intent classifier routes free-form instructions to this loop automatically.

Examples that work out of the box:

```
Find the email thread titled "Backend Hiring Q2",
download every CV attachment, zip them, and save to ~/hires/q2.zip
```

```
Search my inbox for invoices received this week from suppliers@*.com,
download the PDFs to ~/finance/invoices/, and message me a list of filenames
```

```
List everything in /tmp/cvs, then run a CV ranking on that folder
against this job spec: "Senior backend engineer, 5+ years Django,
PostgreSQL, AWS" — top 20 candidates, save the result ZIP to ~/hires/
```

The agent is given a tool catalogue (filesystem ops, IMAP search and attachment download, ZIP creation, Drive download, email send, WhatsApp send, CV ranking, ZIP-of-top-N) and decides — step by step — which tools to call, observing each result before deciding the next call. Sensitive tools (sending email, deleting files, moving files, pushing to Git) require an explicit *Yes* confirmation from the operator before they actually run; the bot will pause and ask in WhatsApp.

You can also trigger the agent directly from the shell for testing:

```bash
python manage.py run_agent "list /tmp/cvs and zip them to /tmp/cvs.zip"
```

Add `--allow-dangerous` to bypass the confirmation gate for sensitive tools when running locally.

### Granting In-Group Access

Only the three core operators can issue instructions individually. To let someone else in a particular group give the bot orders, a core operator types one of these in the group:

```
authorize +880 1888-555000
authorize this person          (as a reply to their message)
@bot grant access to Karim
```

The bot replies confirming the grant. From that point, Karim can issue instructions **inside that group** — but he can't DM the bot, and his access doesn't extend to any other group.

To revoke:

```
revoke +880 1888-555000
remove access for Karim        (as a reply to one of his messages)
```

To audit:

```
show authorized members
who is authorized
```

The full grant/revoke history is also visible at `/api/authz/events/` and in the Django admin under **Authorization → Authorization Events**.

---

## API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/api/messaging/webhook/` | POST | WhatsApp bridge webhook (receives messages) |
| `/api/confirm/respond/` | POST | Manual confirmation trigger |
| `/api/email/records/` | GET | Email send history |
| `/api/cv/jobs/` | GET | CV ranking job history |
| `/api/jobpost/` | GET | Job post history |
| `/api/dev/jobs/` | GET | Code generation job history |
| `/api/agent/runs/` | GET | Dynamic agent run history (last 30) |
| `/api/agent/runs/<id>/` | GET | Detail of one agent run with all tool-call steps |
| `/api/authz/memberships/` | GET | Active and revoked group memberships |
| `/api/authz/events/` | GET | Audit log of grants, revokes, and denied messages |
| `/api/logs/` | GET | Action log (last 100 entries) |
| `/api/health/` | GET | Health check |
| `/admin/` | GET | Django admin panel |

---

## Running Tests

```bash
# All tests
pytest

# With coverage report
coverage run -m pytest
coverage report -m

# Specific module
pytest tests/test_cv.py -v
```

---

## Deployment

### Docker Compose (Recommended)

```bash
cp .env.example .env
# Edit .env with production values

docker-compose up -d
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py createsuperuser

# View logs
docker-compose logs -f web
docker-compose logs -f celery_worker
docker-compose logs -f wa_bridge
```

### Production Checklist

- [ ] Set `DEBUG=False`
- [ ] Set `DJANGO_SECRET_KEY` to a unique 50+ character random string
- [ ] Set `DATABASE_URL` to a PostgreSQL database
- [ ] Configure `ALLOWED_HOSTS` with your domain
- [ ] Set up SSL/TLS (nginx reverse proxy)
- [ ] Configure proper firewall rules (only expose ports 80/443)
- [ ] Set up log rotation
- [ ] Configure backup for the database and outputs directory

---

## Troubleshooting

**WhatsApp bridge shows QR code but won't connect**
- Ensure the phone scanning the QR is the operator's phone
- Check that port 3000 is accessible

**"No email templates found"**
- Ensure `templates/email_templates/` contains at least one `.json` template file
- Check `EMAIL_TEMPLATES_DIR` in `.env`

**CV ranking takes too long**
- Increase Celery worker `time_limit`
- Process CVs in smaller batches
- Ensure your LLM API keys have sufficient rate limits

**Git push fails**
- Verify SSH key is configured: `ssh -T git@github.com`
- For HTTPS: set `GIT_PAT` and use `https://token@github.com/...` format

**Celery tasks not executing**
- Confirm Redis is running: `redis-cli ping`
- Check worker is running: `celery -A etaa_core inspect active`

---

## License

Proprietary – Zihad IT. All rights reserved.

---

*Built with Django · Celery · OpenAI GPT-4o · Anthropic Claude · whatsapp-web.js*
# etaa
