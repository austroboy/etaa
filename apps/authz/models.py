"""
Authorization Module – Models.

Two layers of authorization in ETAA:

1. **Core operators** – the three people configured via env vars
   (OPERATOR_1_PHONE / 2 / 3). They are individually authorized
   everywhere – DMs to the bot, every group the bot is in. They are the
   *only* people allowed to issue instructions in a 1-on-1 chat.

2. **Group-delegated members** – a person that one of the core operators
   has explicitly authorized inside a particular group. Their
   authorization is *scoped to that group only*: a delegated member
   cannot DM the bot, and is not authorized in any other group.

This file defines the persistence layer for layer 2.
Layer 1 lives in settings.AUTHORIZED_OPERATORS.
"""

from django.db import models
from django.utils import timezone


class MembershipStatus(models.TextChoices):
    ACTIVE  = "active",  "Active"
    REVOKED = "revoked", "Revoked"


class GroupMembership(models.Model):
    """
    A (group, phone) pair authorizing `member_phone` to issue instructions
    while messaging in `group_jid`. Outside the group, the membership has
    no effect.
    """

    group_jid       = models.CharField(max_length=120, db_index=True)
    member_phone    = models.CharField(max_length=30, db_index=True)
    member_name     = models.CharField(max_length=120, blank=True)
    granted_by      = models.CharField(
        max_length=30,
        help_text="Phone number of the core operator who granted access.",
    )
    granted_at      = models.DateTimeField(auto_now_add=True)
    status          = models.CharField(
        max_length=10,
        choices=MembershipStatus.choices,
        default=MembershipStatus.ACTIVE,
    )
    revoked_at      = models.DateTimeField(null=True, blank=True)
    revoked_by      = models.CharField(max_length=30, blank=True)
    note            = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = [("group_jid", "member_phone")]
        ordering = ["-granted_at"]
        verbose_name = "Group Membership"

    def __str__(self):
        return (f"{self.member_name or self.member_phone} @ "
                f"{self.group_jid[-20:]} [{self.status}]")

    def revoke(self, by_phone: str) -> None:
        self.status = MembershipStatus.REVOKED
        self.revoked_at = timezone.now()
        self.revoked_by = by_phone
        self.save(update_fields=["status", "revoked_at", "revoked_by"])

    def reactivate(self, by_phone: str) -> None:
        self.status = MembershipStatus.ACTIVE
        self.granted_by = by_phone
        self.revoked_at = None
        self.revoked_by = ""
        self.save(update_fields=["status", "granted_by", "revoked_at", "revoked_by"])


class AuthorizationEvent(models.Model):
    """
    Audit trail of every grant / revoke / denied attempt. Useful for
    answering 'who authorized X and when?' months later.
    """

    class Kind(models.TextChoices):
        GRANTED        = "granted",        "Granted"
        REVOKED        = "revoked",        "Revoked"
        REACTIVATED    = "reactivated",    "Reactivated"
        DENIED_GRANT   = "denied_grant",   "Grant Denied (not a core op)"
        DENIED_MESSAGE = "denied_message", "Message Denied (unauthorized sender)"

    timestamp     = models.DateTimeField(auto_now_add=True, db_index=True)
    kind          = models.CharField(max_length=20, choices=Kind.choices)
    actor_phone   = models.CharField(max_length=30,
                                     help_text="Who took/attempted the action.")
    actor_name    = models.CharField(max_length=120, blank=True)
    target_phone  = models.CharField(max_length=30, blank=True)
    target_name   = models.CharField(max_length=120, blank=True)
    group_jid     = models.CharField(max_length=120, blank=True)
    detail        = models.TextField(blank=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return (f"[{self.timestamp:%Y-%m-%d %H:%M}] "
                f"{self.kind} {self.actor_phone} -> {self.target_phone}")
