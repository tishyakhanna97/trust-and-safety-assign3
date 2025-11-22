import os
import csv

from atproto import Client
from dotenv import load_dotenv

load_dotenv(override=True)
USERNAME = os.getenv("USERNAME")
PW = os.getenv("PW")

# ---------------------------------------------------------
# ACCOUNTS grouped by category
# ---------------------------------------------------------
ACCOUNTS = {
    "donation_real_org": [
        "redcrosscanada.bsky.social",
        "decappeal.bsky.social",
    ],
    "donation_real_individual": [
        "drewscanlon.bsky.social",
        "supergavigator.bsky.social",
    ],
    "talks_about_donations_no_ask": [
        "taryndevere.bsky.social",
        "bboxart.bsky.social",
    ],
    "no_donations": [
        "trekkiebill.bsky.social",
        "decappeal.bsky.social",
    ],
    "donation_scam_org": [],
    "donation_scam_individual": [],
}


# ---------------------------------------------------------
# Extract only: source_url, category, author, text
# ---------------------------------------------------------
def extract_from_feed_item(item):
    post = item.post
    record = post.record

    author = post.author.handle
    text = (record.text or "").replace("\n", " ").strip()

    # Build source URL
    rkey = post.uri.split("/")[-1]
    source_url = f"https://bsky.app/profile/{author}/post/{rkey}"

    return {
        "author": author,
        "text": text,
        "source_url": source_url,
    }


# ---------------------------------------------------------
# Fetch first n posts from an author
# ---------------------------------------------------------
def fetch_first_n_posts(client, handle, n=20):
    res = client.app.bsky.feed.get_author_feed({"actor": handle, "limit": n})
    return res.feed


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------
def main():
    client = Client()
    client.login(USERNAME, PW)

    rows = []

    for category, handles in ACCOUNTS.items():
        print(f"\n=== Category: {category} ===")
        for handle in handles:
            print(f"Fetching posts from @{handle}...")

            try:
                items = fetch_first_n_posts(client, handle, n=20)
            except Exception as e:
                print(f"  Failed for {handle}: {e}")
                continue

            for item in items:
                data = extract_from_feed_item(item)
                data["category"] = category
                rows.append(data)

    out_file = "20_posts_per_account.csv"

    fieldnames = ["source_url", "category", "author", "text"]

    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nCSV written: {out_file}")


if __name__ == "__main__":
    main()
