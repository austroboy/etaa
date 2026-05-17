"""
Agent Module – Services.

Entry-point helpers for running the dynamic agent.
"""

import logging
from typing import Optional

from apps.agent.models import AgentRun
from apps.agent.runner import run_agent

logger = logging.getLogger("etaa")


def execute_instruction(
    instruction: str,
    operator_phone: str = "",
    operator_name: str = "",
    log_id: Optional[int] = None,
    reply_jid: str = "",
    allow_dangerous: bool = False,
) -> AgentRun:
    """Run a single free-form instruction through the agent loop."""
    logger.info(
        "Agent run starting | operator=%s allow_dangerous=%s | %.80s",
        operator_name, allow_dangerous, instruction,
    )
    run = run_agent(
        instruction=instruction,
        operator_phone=operator_phone,
        operator_name=operator_name,
        log_id=log_id,
        reply_jid=reply_jid,
        allow_dangerous=allow_dangerous,
    )
    logger.info(
        "Agent run #%s finished | status=%s iterations=%s",
        run.pk, run.status, run.iterations,
    )
    return run
