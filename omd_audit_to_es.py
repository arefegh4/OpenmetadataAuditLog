
#!/usr/bin/env python3

import json
import os
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

from datetime import datetime, timedelta, timezone


# --------------------------------------------------
# Configuration
# --------------------------------------------------

OMD_URL = os.environ["OMD_URL"].rstrip("/")
OMD_TOKEN = os.environ["OMD_TOKEN"]

OUT_DIR = os.environ.get("OUT_DIR", "/data")

PAGE = min(max(int(os.environ.get("PAGE", "200")), 1), 200)
OVERLAP_MS = int(os.environ.get("OVERLAP_MS", "600000"))

TZ_OFFSET_MIN = int(os.environ.get("TZ_OFFSET_MIN", "210"))
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "30"))
POLL_INTERVAL_SECONDS = max(
    1, int(os.environ.get("POLL_INTERVAL_SECONDS", "30"))
)

DROP_FIELDS = {
    field.strip()
    for field in os.environ.get("DROP_FIELDS", "rawEventJson").split(",")
    if field.strip()
}

SKIP_ENTITY_TYPES = {
    item.strip()
    for item in os.environ.get("SKIP_ENTITY_TYPES", "").split(",")
    if item.strip()
}

STATE_FILE = os.path.join(OUT_DIR, ".audit_state.json")

# Keep recently processed event IDs to suppress duplicates.
# The time window must cover the configured overlap.
STATE_OVERLAP_MS = max(OVERLAP_MS, 600000)


# --------------------------------------------------
# API
# --------------------------------------------------

def fetch(params):
    query = urllib.parse.urlencode({
        key: value
        for key, value in params.items()
        if value is not None
    })

    url = f"{OMD_URL}/v1/audit/logs?{query}"

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {OMD_TOKEN}",
            "Accept": "application/json",
        },
        method="GET",
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


# --------------------------------------------------
# State management
# --------------------------------------------------

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            state = json.load(file)

        last_ts = int(state.get("last_ts", 0))
        recent = {
            str(event_id): int(event_ts)
            for event_id, event_ts in state.get("recent", {}).items()
        }

        return last_ts, recent

    except FileNotFoundError:
        return 0, {}


def save_state(last_ts, recent):
    temp_file = STATE_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(
            {
                "last_ts": int(last_ts),
                "recent": recent,
            },
            file,
            ensure_ascii=False,
        )
        file.flush()
        os.fsync(file.fileno())

    os.replace(temp_file, STATE_FILE)


# --------------------------------------------------
# Timestamp and files
# --------------------------------------------------

def iso_timestamp(timestamp_ms):
    value = datetime.fromtimestamp(
        timestamp_ms / 1000,
        tz=timezone.utc,
    )

    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def daily_file(timestamp_ms):
    event_date = (
        datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        + timedelta(minutes=TZ_OFFSET_MIN)
    )

    return os.path.join(
        OUT_DIR,
        f"audit-{event_date:%Y-%m-%d}.json",
    )


def append_records(path, records):
    if not records:
        return

    # Each record is one JSON object on a separate line (NDJSON).
    with open(path, "a", encoding="utf-8") as file:
        for record in records:
            file.write(
                json.dumps(record, ensure_ascii=False) + "\n"
            )

        file.flush()
        os.fsync(file.fileno())


# --------------------------------------------------
# Retention
# --------------------------------------------------

def cleanup():
    if RETENTION_DAYS <= 0:
        return

    cutoff_date = (
        datetime.now(timezone.utc)
        + timedelta(minutes=TZ_OFFSET_MIN)
        - timedelta(days=RETENTION_DAYS)
    ).date()

    for name in os.listdir(OUT_DIR):
        if not name.startswith("audit-") or not name.endswith(".json"):
            continue

        date_text = name[len("audit-"):-len(".json")]

        try:
            file_date = datetime.strptime(
                date_text, "%Y-%m-%d"
            ).date()
        except ValueError:
            continue

        if file_date < cutoff_date:
            path = os.path.join(OUT_DIR, name)

            if os.path.isfile(path):
                os.remove(path)
                print(f"Retention removed: {name}", flush=True)


# --------------------------------------------------
# Collection
# --------------------------------------------------

def collect_once():
    os.makedirs(OUT_DIR, exist_ok=True)

    last_ts, recent = load_state()

    start_ts = (
        max(last_ts - OVERLAP_MS, 0)
        if last_ts
        else None
    )

    end_ts = int(time.time() * 1000)

    print(
        f"Starting collection: lastTs={last_ts}, "
        f"startTs={start_ts}, endTs={end_ts}",
        flush=True,
    )

    max_ts = last_ts
    written = 0
    after = None
    seen_cursors = set()

    # Work on a copy so a failed collection does not commit
    # unconfirmed event IDs to the persistent state.
    working_recent = dict(recent)

    while True:
        response = fetch({
            "limit": PAGE,
            "startTs": start_ts,
            "endTs": end_ts,
            "after": after,
        })

        rows = response.get("data", [])

        if not rows:
            break

        records_by_file = {}
        page_max_ts = max_ts

        for row in rows:
            event_ts = int(row["eventTs"])
            page_max_ts = max(page_max_ts, event_ts)

            event_id = str(row["id"])

            if event_id in working_recent:
                continue

            # This event is intentionally excluded by configuration.
            if row.get("entityType") in SKIP_ENTITY_TYPES:
                working_recent[event_id] = event_ts
                continue
            #keep only user login and logout events.   
            if row.get("eventType") not in {"userLogin","userLogout"}:
                working_recent[event_id] = event_ts
                continue     

            record = dict(row)

            for field in DROP_FIELDS:
                record.pop(field, None)

            record["@timestamp"] = iso_timestamp(event_ts)

            path = daily_file(event_ts)
            records_by_file.setdefault(path, []).append(record)

            # Mark as processed only in working memory.
            working_recent[event_id] = event_ts

        # Write the page before committing its event IDs.
        # If writing fails, the checkpoint is not advanced.
        for path, records in records_by_file.items():
            append_records(path, records)

        max_ts = page_max_ts

        # Bound the in-memory deduplication map.
        cutoff_ts = max(0, max_ts - STATE_OVERLAP_MS)
        working_recent = {
            event_id: event_ts
            for event_id, event_ts in working_recent.items()
            if event_ts >= cutoff_ts
        }

        # Persist progress after every successfully written page.
        save_state(max_ts, working_recent)

        written += sum(len(records) for records in records_by_file.values())

        next_after = (response.get("paging") or {}).get("after")

        if not next_after:
            break

        # Protect against an API repeatedly returning the same cursor.
        cursor_key = str(next_after)

        if cursor_key in seen_cursors:
            raise RuntimeError(
                "Pagination cursor repeated; stopping to avoid an infinite loop"
            )

        seen_cursors.add(cursor_key)
        after = next_after

    print(
        f"Collection successful: written={written}, lastTs={max_ts}",
        flush=True,
    )


# --------------------------------------------------
# Main loop
# --------------------------------------------------

def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    print(
        "Collector started: "
        f"poll={POLL_INTERVAL_SECONDS}s, "
        f"output={OUT_DIR}, "
        f"retention={RETENTION_DAYS} days",
        flush=True,
    )

    while True:
        started = time.monotonic()

        try:
            collect_once()
        except Exception as exc:
            print(
                f"COLLECTION ERROR: {type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )

        try:
            cleanup()
        except Exception as exc:
            print(
                f"CLEANUP ERROR: {type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )

        elapsed = time.monotonic() - started
        sleep_seconds = max(
            1,
            POLL_INTERVAL_SECONDS - int(elapsed),
        )

        print(
            f"Next collection in {sleep_seconds} seconds",
            flush=True,
        )

        time.sleep(sleep_seconds)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Collector stopped.", flush=True)
