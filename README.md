# Gmail Sender Analysis

A Flask web app that connects to your Gmail account and analyses your inbox by sender — showing message counts, total size, and flagging likely marketing/spam. Staged senders can be moved to a Gmail label for bulk deletion.

> [!WARNING]
> This tool is largely generated using AI. It is very likely it will result in data loss if you don't know what you're doing.
> I recommend that no one uses this tool.
> I accept no responsibility for data loss.
> You have been warned.

## Features

- Fetches your entire mailbox (or a subset) via the Gmail API
- Ranks senders by message count with total size per sender
- Flags likely marketing/spam addresses automatically
- Sortable, searchable table with live updates as data is fetched
- Stage emails from any sender to a `mark for deletion` Gmail label
- Crash-safe: partial results are saved to disk every 500 messages
- CSV and JSON export

## Setup

### 1. Google Cloud credentials

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a project
2. Enable the **Gmail API** for the project
3. Go to **APIs & Services → OAuth consent screen**, set it to External, and add your email as a test user
4. Go to **APIs & Services → Credentials**, create an **OAuth 2.0 Client ID** (Desktop app type)
5. Download the credentials file and save it as `credentials.json` in this directory

### 2. Python environment

```bash
python3 -m venv venv
venv/bin/pip install flask google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
```

### 3. Run

```bash
venv/bin/python app.py
```

Open [http://localhost:5000](http://localhost:5000) in your browser.

On first run, a browser window will open asking you to authorise access to your Gmail account. The token is cached in `token.pickle` for subsequent runs.

## Usage

| Action | Description |
|---|---|
| **Fetch Emails** | Start scanning your mailbox. The table populates live as messages are processed. |
| **Refresh** | Re-scan from scratch, overwriting existing data. |
| **Clear Data** | Delete all saved results and reset the app. |
| **Sort** | Click any column header to sort ascending/descending. |
| **Search** | Filter by email address or sender name. |
| **Show flagged only** | Narrow the table to likely marketing/spam senders. |
| **📁 Stage** | Move all emails from that sender to the `mark for deletion` Gmail label, removing them from your inbox. Review and permanently delete from Gmail. |

## Files

| File | Description |
|---|---|
| `app.py` | Flask application and API endpoints |
| `gmail_senders.py` | Gmail API authentication and message fetching logic |
| `templates/index.html` | Web interface |
| `credentials.json` | OAuth credentials from Google Cloud *(not committed)* |
| `token.pickle` | Cached OAuth token *(not committed)* |
| `sender_report.json` | Saved results *(not committed)* |
| `sender_report.csv` | CSV export of last completed fetch *(not committed)* |

## Notes

- Fetching a large mailbox (tens of thousands of emails) takes time — each message requires an individual API call. Progress is shown live in the browser.
- The `mark for deletion` Gmail label is created automatically on first use.
- Staging moves emails out of your inbox and adds the label; it does **not** permanently delete them. You must do that manually in Gmail.
