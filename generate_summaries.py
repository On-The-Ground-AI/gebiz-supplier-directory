"""
Generate short AI summaries for GeBIZ supplier descriptions using Claude Haiku.
Uses Message Batches API for cost efficiency (~$1.25 total).
Adds description_short field to each supplier in suppliers.json.
"""
import json
import time
import anthropic

JSON_PATH = "suppliers.json"
MIN_DESC_LEN = 50

SYSTEM = (
    "You summarise Singapore government supplier company profiles. "
    "Write exactly 1 sentence (max 160 characters) capturing what the company does and its key focus. "
    "Be specific, not generic. No filler phrases like 'dedicated to' or 'committed to'. "
    "Start with the company's activity, not its name. Output only the summary sentence."
)

def main():
    with open(JSON_PATH) as f:
        suppliers = json.load(f)

    # Find suppliers that need summaries
    to_summarise = [
        s for s in suppliers
        if s.get("description") and len(s["description"]) >= MIN_DESC_LEN
        and not s.get("description_short")
    ]
    print(f"Suppliers to summarise: {len(to_summarise)}")

    client = anthropic.Anthropic()

    # Build batch requests
    requests = []
    for s in to_summarise:
        desc = s["description"][:800]  # trim very long descriptions
        requests.append({
            "custom_id": s["code"],
            "params": {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 100,
                "system": SYSTEM,
                "messages": [{"role": "user", "content": desc}],
            },
        })

    print(f"Submitting batch of {len(requests)} requests...")
    batch = client.messages.batches.create(requests=requests)
    batch_id = batch.id
    print(f"Batch ID: {batch_id}")
    print(f"Status: {batch.processing_status}")

    # Poll until done
    while True:
        time.sleep(15)
        batch = client.messages.batches.retrieve(batch_id)
        counts = batch.request_counts
        done = counts.succeeded + counts.errored + counts.canceled
        print(f"  {done}/{len(requests)} done (succeeded={counts.succeeded}, errored={counts.errored})", flush=True)
        if batch.processing_status == "ended":
            break

    print(f"\nBatch complete. Retrieving results...")

    # Build code -> summary map
    summaries = {}
    for result in client.messages.batches.results(batch_id):
        if result.result.type == "succeeded":
            text = result.result.message.content[0].text.strip()
            summaries[result.custom_id] = text

    print(f"Got {len(summaries)} summaries")

    # Apply summaries to suppliers
    applied = 0
    for s in suppliers:
        code = s.get("code")
        if code in summaries:
            s["description_short"] = summaries[code]
            applied += 1

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(suppliers, f, ensure_ascii=False, indent=2)

    print(f"Applied {applied} summaries and saved {JSON_PATH}")

    # Show samples
    samples = [s for s in suppliers if s.get("description_short")][:3]
    for s in samples:
        print(f"\n{s['name']}:")
        print(f"  Original ({len(s['description'])} chars): {s['description'][:120]}...")
        print(f"  Summary  ({len(s['description_short'])} chars): {s['description_short']}")


if __name__ == "__main__":
    main()
