import email
import logging
import os
import re

import boto3
from anthropic import Anthropic

logger = logging.getLogger()
logger.setLevel(logging.INFO)

client = Anthropic()
s3 = boto3.client("s3")
ses = boto3.client("ses")

SYSTEM_PROMPT = (
    "You are a field assistant for a solo backpacker communicating via satellite. "
    "Messages display in 160-character segments.\n\n"
    "Rules:\n"
    "- Reply in 160 characters or fewer — always\n"
    "- No greetings, sign-offs, or filler words\n"
    "- Numbers over words; abbreviations where clear (hr, min, ft, mi, elev, temp)\n"
    "- If answer needs more space, write [1/2] first message then [2/2] second (max 2 parts)\n"
    "- If question is unclear, ask ONE short clarifying question\n"
    "- Safety-critical info always comes first"
)

_INREACH_SEPARATORS = [
    "View the location or reply at:",
    "To view the location",
    "Sent via inReach",
    "This message was sent to you by",
    "Do not reply directly",
]

S3_BUCKET = os.environ["S3_BUCKET_NAME"]
S3_PREFIX = os.environ.get("S3_EMAIL_PREFIX", "")  # e.g. "emails/" if set in SES rule
FROM_EMAIL = os.environ["SES_FROM_EMAIL"]


def _fetch_raw_email(message_id: str) -> str:
    key = f"{S3_PREFIX}{message_id}"
    obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
    return obj["Body"].read().decode("utf-8", errors="replace")


def _extract_text_body(raw_email: str) -> str:
    msg = email.message_from_string(raw_email)
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                return payload.decode("utf-8", errors="replace")
    else:
        if msg.get_content_type() == "text/plain":
            payload = msg.get_payload(decode=True)
            return payload.decode("utf-8", errors="replace")
    return ""


def _parse_inreach_body(raw: str) -> str:
    text = raw.strip()
    for sep in _INREACH_SEPARATORS:
        idx = text.find(sep)
        if idx != -1:
            text = text[:idx].strip()
    return re.sub(r"\s{3,}", "\n\n", text).strip()


def _chunk_response(text: str, max_len: int = 155) -> list[str]:
    if len(text) <= max_len:
        return [text]
    part1 = f"[1/2] {text[: max_len - 6]}"
    part2 = f"[2/2] {text[max_len - 6 : (max_len - 6) * 2]}"
    return [part1, part2]


def _send_reply(to: str, subject: str, body: str) -> None:
    ses.send_email(
        Source=FROM_EMAIL,
        Destination={"ToAddresses": [to]},
        Message={
            "Subject": {"Data": subject},
            "Body": {"Text": {"Data": body}},
        },
    )


def lambda_handler(event, _context):
    record = event["Records"][0]
    mail_meta = record["ses"]["mail"]

    message_id = mail_meta["messageId"]
    sender = mail_meta["source"]
    subject = mail_meta["commonHeaders"].get("subject", "Trail Assistant")
    logger.info("Received email from %s, message_id=%s", sender, message_id)

    raw_email = _fetch_raw_email(message_id)
    body_text = _extract_text_body(raw_email)
    query = _parse_inreach_body(body_text)
    logger.info("Parsed query: %r", query)

    if not query:
        logger.warning("Empty query, skipping")
        return {"statusCode": 200, "body": "empty query, skipping"}

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=120,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": query}],
    )

    response_text = message.content[0].text.strip()
    logger.info("Claude response: %r", response_text)
    chunks = _chunk_response(response_text)

    reply_subject = subject if subject.startswith("Re:") else f"Re: {subject}"
    for chunk in chunks:
        _send_reply(sender, reply_subject, chunk)
    logger.info("Reply sent to %s", sender)

    return {"statusCode": 200, "body": "ok"}
