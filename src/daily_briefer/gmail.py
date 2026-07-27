"""Gmail client for sending and receiving emails."""
from __future__ import annotations

import asyncio
import imaplib
import email
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any
from datetime import datetime, timezone

import aiosmtplib

from daily_briefer.config import Config


class GmailClient:
    """Client for Gmail IMAP/SMTP."""

    def __init__(self, config: Config):
        self.config = config
        self.address = config.gmail_address
        self.password = config.gmail_app_password

    async def send_email(self, to: str, subject: str, body: str) -> bool:
        """Send an email via Gmail SMTP."""
        msg = MIMEMultipart()
        msg["From"] = self.address
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))

        try:
            await aiosmtplib.send(
                msg,
                hostname="smtp.gmail.com",
                port=587,
                username=self.address,
                password=self.password,
                start_tls=True,
            )
            return True
        except Exception as e:
            print(f"[ERROR] Failed to send email: {e}")
            return False

    async def fetch_unread_email(self) -> dict | None:
        """Check for new unread emails and return the first one."""
        try:
            # Connect to IMAP
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(self.address, self.password)
            mail.select("INBOX")

            # Search for unread emails
            status, messages = mail.search(None, '(UNSEEN)')
            if status != "OK":
                mail.logout()
                return None

            email_ids = messages[0].split()
            if not email_ids:
                mail.logout()
                return None

            # Get the most recent unread email
            email_id = email_ids[-1]
            status, msg_data = mail.fetch(email_id, "(RFC822)")
            if status != "OK":
                mail.logout()
                return None

            # Parse the email
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            # Extract headers
            subject = self._decode_header(msg.get("Subject", ""))
            from_addr = msg.get("From", "")

            # Extract body (prefer HTML, fallback to text)
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition", ""))
                    if "attachment" in content_disposition:
                        continue
                    if content_type == "text/html":
                        body = part.get_payload(decode=True).decode(part.get_content_charset(), errors="ignore")
                        break
                    elif content_type == "text/plain" and not body:
                        body = part.get_payload(decode=True).decode(part.get_content_charset(), errors="ignore")
            else:
                body = msg.get_payload(decode=True).decode(msg.get_content_charset(), errors="ignore")

            mail.logout()

            # Check if this is a reply to our last brief
            if not self._is_reply_to_brief(subject, from_addr):
                return None

            return {
                "subject": subject,
                "body": body,
                "from": from_addr,
                "date": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            print(f"[ERROR] Failed to fetch email: {e}")
            return None

    def _decode_header(self, header: str) -> str:
        """Decode a MIME header."""
        if not header:
            return ""
        # Try to decode RFC 2047 encoded words
        decoded = email.header.decode_header(header)
        result = []
        for part, charset in decoded:
            if isinstance(part, bytes):
                charset = charset or "utf-8"
                result.append(part.decode(charset, errors="ignore"))
            else:
                result.append(part)
        return " ".join(result)

    def _is_reply_to_brief(self, subject: str, from_addr: str) -> bool:
        """Check if the incoming unread email should be processed as a user preference command or reply."""
        if not from_addr:
            return False

        from_clean = from_addr.lower()
        my_addr = (self.address or "").lower()
        subject_lower = (subject or "").lower()

        # Ignore automated outgoing briefs sent from self to self (unless it is a reply Re:)
        if my_addr and my_addr in from_clean and not any(k in subject_lower for k in ["re:", "fw:", "reply"]):
            return False

        return True


    async def mark_as_read(self, email_id: str) -> bool:
        """Mark an email as read."""
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(self.address, self.password)
            mail.select("INBOX")
            mail.store(email_id, "+FLAGS", "\\Seen")
            mail.close()
            mail.logout()
            return True
        except Exception as e:
            print(f"[ERROR] Failed to mark email as read: {e}")
            return False
