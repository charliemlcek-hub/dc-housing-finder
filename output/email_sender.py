"""Send daily digest + extraordinary-fit alerts via Gmail SMTP.

Auth: Uses a Gmail **App Password** (not your real password). Read from env var
GMAIL_APP_PASSWORD. Get one at: https://myaccount.google.com/apppasswords

DRY_RUN=1 prints the email to stdout instead of sending it.
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from datetime import datetime, date
from email.message import EmailMessage
from pathlib import Path
from typing import List

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _render_email(
    new_listings: List[dict],
    extraordinary: List[dict],
    active_count: int,
    dashboard_url: str,
    subject_prefix: str = "",
) -> tuple[str, str, str]:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    tmpl = env.get_template("email.html")

    top_n = sorted(new_listings, key=lambda l: l.get("score") or 0, reverse=True)[:10]

    html = tmpl.render(
        date=date.today().isoformat(),
        active_count=active_count,
        new_count=len(new_listings),
        extraordinary_count=len(extraordinary),
        extraordinary=extraordinary,
        top_listings=top_n,
        dashboard_url=dashboard_url,
    )

    # Plain text fallback
    lines = [f"DC Housing Daily Digest — {date.today().isoformat()}\n"]
    lines.append(f"{active_count} active | {len(new_listings)} new | {len(extraordinary)} extraordinary\n")
    if extraordinary:
        lines.append("\n=== EXTRAORDINARY FITS ===")
        for l in extraordinary:
            lines.append(f"  ${l.get('price')} — {l.get('title') or l.get('address')}")
            lines.append(f"    {l.get('url')}")
    if top_n:
        lines.append("\n=== TOP NEW LISTINGS ===")
        for l in top_n:
            lines.append(f"  ${l.get('price')} — {l.get('title') or l.get('address')} "
                         f"({l.get('neighborhood')}, score {l.get('score')})")
            lines.append(f"    {l.get('url')}")
    lines.append(f"\nDashboard: {dashboard_url}")
    plain = "\n".join(lines)

    if extraordinary:
        subject = f"{subject_prefix}★ {len(extraordinary)} extraordinary DC housing fit{'s' if len(extraordinary) != 1 else ''}"
    elif new_listings:
        subject = f"{subject_prefix}DC Housing: {len(new_listings)} new listing{'s' if len(new_listings) != 1 else ''}"
    else:
        subject = f"{subject_prefix}DC Housing Daily Digest — {date.today().isoformat()}"

    return subject, html, plain


def send_email(
    new_listings: List[dict],
    extraordinary: List[dict],
    active_count: int,
    config: dict,
    dashboard_url: str,
    *,
    immediate_alert: bool = False,
    dry_run: bool = False,
    force: bool = False,
) -> bool:
    """Returns True on success (or when dry-run). force=True sends even with no new items."""
    # Skip if nothing to send (unless forced)
    if not force and not immediate_alert and not new_listings and not extraordinary:
        logger.info("No new listings and no extraordinary fits; skipping daily email.")
        return True

    prefix = "[ALERT] " if immediate_alert else ""
    subject, html, plain = _render_email(
        new_listings, extraordinary, active_count, dashboard_url, subject_prefix=prefix,
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config["email"]["sender"]
    msg["To"] = config["email"]["recipient"]
    msg.set_content(plain)
    msg.add_alternative(html, subtype="html")

    if dry_run:
        print("=" * 60)
        print("DRY RUN — email would be sent:")
        print(f"Subject: {subject}")
        print(f"To: {msg['To']}")
        print("-" * 60)
        print(plain)
        print("=" * 60)
        return True

    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not password:
        logger.error("GMAIL_APP_PASSWORD env var not set — cannot send email")
        return False

    host = config["email"]["smtp_host"]
    port = config["email"]["smtp_port"]

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls(context=context)
            server.login(config["email"]["sender"], password)
            server.send_message(msg)
        logger.info("Sent email to %s: %s", msg["To"], subject)
        return True
    except Exception as exc:
        logger.error("Email send failed: %s", exc)
        return False
