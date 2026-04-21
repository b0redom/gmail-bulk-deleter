#!/usr/bin/env python3
import csv
import json
import os
import threading

from flask import Flask, jsonify, redirect, render_template, request, url_for

from gmail_senders import (
    authenticate,
    fetch_senders,
    format_size,
    is_marketing_or_spam,
)

app = Flask(__name__)

REPORT_FILE = "sender_report.json"
MAX_MESSAGES = 10_000_000

_state = {"running": False, "fetched": 0, "target": MAX_MESSAGES, "error": None}
_state_lock = threading.Lock()
_live_senders = []
_live_lock = threading.Lock()


CSV_FILE = "sender_report.csv"


def _save_report(senders, partial=False):
    data = {"senders": senders, "partial": partial}
    tmp = REPORT_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, REPORT_FILE)
    if not partial:
        with open(CSV_FILE, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["rank", "email", "name", "count", "size_bytes", "size_human", "flagged"],
            )
            writer.writeheader()
            for rank, row in enumerate(senders, 1):
                writer.writerow({**row, "rank": rank})


def _build_senders(counts, sizes, names):
    return [
        {
            "email": email,
            "name": names.get(email, ""),
            "count": count,
            "size_bytes": sizes.get(email, 0),
            "size_human": format_size(sizes.get(email, 0)),
            "flagged": is_marketing_or_spam(email),
        }
        for email, count in sorted(counts.items(), key=lambda x: x[1], reverse=True)
    ]


def _run_fetch():
    global _live_senders
    try:
        service = authenticate()

        def on_progress(n, counts, sizes, names):
            global _live_senders
            with _state_lock:
                _state["fetched"] = n
            senders = _build_senders(counts, sizes, names)
            with _live_lock:
                _live_senders = senders
            if n % 500 == 0:
                _save_report(senders, partial=True)

        counts, sizes, names = fetch_senders(
            service, max_results=MAX_MESSAGES, progress_callback=on_progress
        )

        senders = _build_senders(counts, sizes, names)

        with _live_lock:
            _live_senders = senders

        _save_report(senders, partial=False)

    except Exception as e:
        with _state_lock:
            _state["error"] = str(e)
    finally:
        with _state_lock:
            _state["running"] = False


def _load_saved():
    if not os.path.exists(REPORT_FILE):
        return [], False
    with open(REPORT_FILE) as f:
        data = json.load(f)
    raw = data.get("senders", [])
    partial = data.get("partial", False)
    for s in raw:
        s.setdefault("size_bytes", 0)
        s.setdefault("size_human", format_size(0))
        s.setdefault("name", "")
        s.setdefault("flagged", False)
    return raw, partial


@app.route("/")
def index():
    with _state_lock:
        state = dict(_state)
    with _live_lock:
        live = list(_live_senders)
    if live:
        senders, partial = live, state["running"]
    else:
        senders, partial = _load_saved()
    total_size = sum(s["size_bytes"] for s in senders)
    return render_template(
        "index.html",
        senders=senders,
        state=state,
        partial=partial,
        total_size_human=format_size(total_size),
    )


@app.route("/fetch", methods=["POST"])
def fetch():
    global _live_senders
    with _state_lock:
        if _state["running"]:
            return redirect(url_for("index"))
        _state["running"] = True
        _state["fetched"] = 0
        _state["target"] = MAX_MESSAGES
        _state["error"] = None
    with _live_lock:
        _live_senders = []

    t = threading.Thread(target=_run_fetch, daemon=True)
    t.start()
    return redirect(url_for("index"))


@app.route("/clear", methods=["POST"])
def clear():
    global _live_senders
    with _state_lock:
        if _state["running"]:
            return jsonify({"error": "fetch in progress"}), 409
    with _live_lock:
        _live_senders = []
    for f in (REPORT_FILE, CSV_FILE, REPORT_FILE + ".tmp"):
        if os.path.exists(f):
            os.remove(f)
    return redirect(url_for("index"))


@app.route("/api/status")
def api_status():
    with _state_lock:
        return jsonify(dict(_state))


@app.route("/api/data")
def api_data():
    with _state_lock:
        running = _state["running"]
    with _live_lock:
        live = list(_live_senders)
    if running and live:
        return jsonify({"senders": live, "partial": True})
    if live:
        return jsonify({"senders": live, "partial": False})
    return jsonify({"senders": _load_saved(), "partial": False})


def _get_message_ids(service, email):
    query = f"from:{email}"
    message_ids = []
    page_token = None
    while True:
        params = {
            "userId": "me",
            "q": query,
            "fields": "messages(id),nextPageToken",
            "maxResults": 500,
        }
        if page_token:
            params["pageToken"] = page_token
        result = service.users().messages().list(**params).execute()
        msgs = result.get("messages", [])
        message_ids.extend(m["id"] for m in msgs)
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return message_ids


@app.route("/api/dry-run")
def api_dry_run():
    email = request.args.get("email", "").strip()
    if not email:
        return jsonify({"error": "email parameter required"}), 400
    try:
        service = authenticate()
        message_ids = _get_message_ids(service, email)
        return jsonify({
            "email": email,
            "query": f"from:{email}",
            "count": len(message_ids),
            "message_ids": message_ids,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


STAGING_LABEL = "mark for deletion"


def _get_or_create_label(service):
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    existing = next((l for l in labels if l["name"] == STAGING_LABEL), None)
    if existing:
        return existing["id"]
    created = service.users().labels().create(
        userId="me", body={"name": STAGING_LABEL}
    ).execute()
    return created["id"]


@app.route("/api/stage-for-deletion", methods=["POST"])
def api_stage_for_deletion():
    email = request.get_json(force=True).get("email", "").strip()
    if not email:
        return jsonify({"error": "email required"}), 400
    try:
        service = authenticate()
        label_id = _get_or_create_label(service)
        message_ids = _get_message_ids(service, email)

        for i in range(0, len(message_ids), 1000):
            chunk = message_ids[i:i + 1000]
            service.users().messages().batchModify(
                userId="me",
                body={
                    "ids": chunk,
                    "addLabelIds": [label_id],
                    "removeLabelIds": ["INBOX"],
                },
            ).execute()

        return jsonify({"success": True, "email": email, "moved": len(message_ids)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True, port=5000)
