#!/usr/bin/env python3
"""
Gmail Sender Analysis
Lists all email senders sorted by message count, flagging marketing/spam.

Setup:
  1. Go to https://console.cloud.google.com and create a project
  2. Enable the Gmail API
  3. Create OAuth 2.0 credentials (Desktop app) and download as credentials.json
  4. pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
"""

import os
import re
import csv
import json
import pickle
from collections import defaultdict
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
TOKEN_FILE = "token.pickle"
CREDENTIALS_FILE = "credentials.json"

MARKETING_PATTERNS = [
    r"no.?reply", r"noreply", r"do.not.reply", r"donotreply",
    r"newsletter", r"updates@", r"news@", r"promotions@",
    r"marketing@", r"info@", r"hello@", r"hi@", r"team@",
    r"notifications@", r"alert(s)?@", r"support@", r"help@",
    r"mailer", r"bounce", r"campaigns?@", r"offers?@",
    r"deals?@", r"promo", r"unsubscribe", r"list-",
    r"bulk", r"blast", r"digest", r"weekly", r"daily",
    r"monthly", r"account@", r"billing@", r"invoice",
    r"receipt", r"order(s)?@", r"confirm", r"verify",
    r"@.*\.(sendgrid|mailchimp|klaviyo|hubspot|marketo|salesforce|constantcontact|campaign)",
    r"@e\.", r"@em\.", r"@mail\.", r"@send\.", r"@news\.",
    r"@m\.", r"@mg\.", r"@sg\.",
]

COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in MARKETING_PATTERNS]


def authenticate():
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)

    return build("gmail", "v1", credentials=creds)


def extract_email(from_header):
    """Extract email address from a From header value."""
    match = re.search(r"<([^>]+)>", from_header)
    if match:
        return match.group(1).strip().lower()
    return from_header.strip().lower()


def extract_name(from_header):
    """Extract display name from a From header value."""
    match = re.match(r"^(.+?)\s*<", from_header)
    if match:
        return match.group(1).strip().strip('"')
    return ""


def is_marketing_or_spam(email_address):
    return any(p.search(email_address) for p in COMPILED_PATTERNS)


def format_size(bytes_total):
    for unit in ("B", "KB", "MB", "GB"):
        if bytes_total < 1024:
            return f"{bytes_total:.1f} {unit}"
        bytes_total /= 1024
    return f"{bytes_total:.1f} TB"


def fetch_senders(service, max_results=5000, query="", progress_callback=None):
    sender_counts = defaultdict(int)
    sender_sizes = defaultdict(int)
    sender_names = {}
    page_token = None
    fetched = 0

    while fetched < max_results:
        batch_size = min(500, max_results - fetched)
        params = {
            "userId": "me",
            "maxResults": batch_size,
            "fields": "messages(id),nextPageToken",
        }
        if query:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token

        result = service.users().messages().list(**params).execute()
        messages = result.get("messages", [])
        if not messages:
            break

        for msg in messages:
            msg_data = (
                service.users()
                .messages()
                .get(userId="me", id=msg["id"], format="metadata", metadataHeaders=["From"])
                .execute()
            )
            headers = {h["name"]: h["value"] for h in msg_data.get("payload", {}).get("headers", [])}
            from_val = headers.get("From", "")
            if from_val:
                email = extract_email(from_val)
                name = extract_name(from_val)
                sender_counts[email] += 1
                sender_sizes[email] += msg_data.get("sizeEstimate", 0)
                if email not in sender_names and name:
                    sender_names[email] = name

            fetched += 1
            if progress_callback and fetched % 50 == 0:
                progress_callback(fetched, sender_counts, sender_sizes, sender_names)

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    return sender_counts, sender_sizes, sender_names


def print_report(sender_counts, sender_sizes, sender_names, top_n=None):
    sorted_senders = sorted(sender_counts.items(), key=lambda x: x[1], reverse=True)
    if top_n:
        sorted_senders = sorted_senders[:top_n]

    total_senders = len(sender_counts)
    total_messages = sum(sender_counts.values())
    flagged_count = sum(1 for email, _ in sorted_senders if is_marketing_or_spam(email))

    print(f"\n{'='*90}")
    print(f"GMAIL SENDER REPORT")
    print(f"{'='*90}")
    print(f"Total unique senders : {total_senders}")
    print(f"Total messages scanned: {total_messages}")
    print(f"Flagged (marketing/spam): {flagged_count} of {len(sorted_senders)} shown")
    print(f"{'='*90}\n")

    fmt = "{:<6}  {:<45}  {:>6}  {:>10}  {}"
    print(fmt.format("RANK", "EMAIL", "COUNT", "SIZE", "FLAGS"))
    print("-" * 90)

    for rank, (email, count) in enumerate(sorted_senders, 1):
        flags = []
        if is_marketing_or_spam(email):
            flags.append("[MARKETING/SPAM]")
        name = sender_names.get(email, "")
        display = f"{name} <{email}>" if name else email
        if len(display) > 45:
            display = display[:42] + "..."
        size = format_size(sender_sizes.get(email, 0))
        print(fmt.format(rank, display, count, size, " ".join(flags)))

    print(f"\n{'='*90}")
    print("FLAG KEY: [MARKETING/SPAM] = likely bulk/automated sender")


def main():
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"ERROR: {CREDENTIALS_FILE} not found.")
        print("Download OAuth2 credentials from Google Cloud Console and save as credentials.json")
        return

    service = authenticate()

    # Change max_results to scan more/fewer messages; add query to filter (e.g. "in:inbox")
    sender_counts, sender_sizes, sender_names = fetch_senders(service, max_results=10000, query="")

    print_report(sender_counts, sender_sizes, sender_names, top_n=100)

    # Save full results to JSON
    output = {
        "senders": [
            {
                "email": email,
                "name": sender_names.get(email, ""),
                "count": count,
                "size_bytes": sender_sizes.get(email, 0),
                "size_human": format_size(sender_sizes.get(email, 0)),
                "flagged": is_marketing_or_spam(email),
            }
            for email, count in sorted(sender_counts.items(), key=lambda x: x[1], reverse=True)
        ]
    }
    with open("sender_report.json", "w") as f:
        json.dump(output, f, indent=2)

    with open("sender_report.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["rank", "email", "name", "count", "size_bytes", "size_human", "flagged"])
        writer.writeheader()
        for rank, row in enumerate(output["senders"], 1):
            writer.writerow({**row, "rank": rank})

    print(f"\nFull results saved to sender_report.csv and sender_report.json")


if __name__ == "__main__":
    main()
