import requests

from .config import WEB_APP_URL

def _post(payload, timeout=45):
    response = requests.post(WEB_APP_URL, json=payload, timeout=timeout)
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Apps Script returned non-JSON: {response.text[:300]}") from exc
    if data.get("status") == "error":
        raise RuntimeError(data.get("message", "Apps Script error"))
    return data

def get_sources_and_memory():
    data = _post({"action": "get_sources"}, timeout=45)
    if data.get("status") != "ok":
        raise RuntimeError(f"Cannot get sources: {data}")
    sources = [
        source for source in (data.get("sources") or [])
        if source.get("url") and source.get("name")
    ]
    links = set(str(value).strip() for value in data.get("existingLinks", []) if value)
    numbers = set(str(value).strip().upper() for value in data.get("existingNumbers", []) if value)
    return sources, links, numbers

def save_results_in_batches(new_docs, source_status, batch_size=50):
    batches = [new_docs[i:i + batch_size] for i in range(0, len(new_docs), batch_size)]
    if not batches:
        result = _post({
            "action": "save_results", "new_docs": [], "source_status": source_status,
        })
        return int(result.get("added", 0))

    added = 0
    for index, batch in enumerate(batches):
        statuses = source_status if index == len(batches) - 1 else []
        result = _post({
            "action": "save_results", "new_docs": batch, "source_status": statuses,
        })
        added += int(result.get("added", len(batch)))
        print(f"[SHEETS] Đã đồng bộ lô {index + 1}/{len(batches)}: {len(batch)} văn bản.")
    return added
