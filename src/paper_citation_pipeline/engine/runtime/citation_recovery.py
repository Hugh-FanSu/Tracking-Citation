"""Conservative table-citation recovery using three independent structured signals."""
import re
import pymupdf


def printed_bibliography_labels(pdf, bibliography):
    labels = {}
    with pymupdf.open(pdf) as doc:
        words = {i + 1: p.get_text("words") for i, p in enumerate(doc)}
        for entry in bibliography:
            if not entry["coordinates"]:
                continue
            c = entry["coordinates"][0]
            possible = []
            for word in words[c["page"]]:
                match = re.fullmatch(r"\[(\d+)\]", word[4])
                if (match and 0 <= c["x"] - word[0] <= 45 and word[2] <= c["x"] + 2
                        and min(word[3], c["y"] + c["height"]) > max(word[1], c["y"])):
                    possible.append((int(match[1]), list(word[:4])))
            if len(possible) == 1:
                labels[entry["id"]] = {"printed_number": possible[0][0], "page": c["page"], "bbox": possible[0][1], "source": "original_pdf_words"}
    return labels


def recover_table_citations(pdf, data):
    data["recovered_pdf_table_citation_groups"] = []
    mentions = data["citation_mentions"]
    # Do not turn quantities in author-year papers into bibliography references.
    numeric = sum(m["style"] == "numeric" for m in mentions)
    if numeric < 5 or numeric < len(mentions) / 2:
        return
    labels = printed_bibliography_labels(pdf, data["bibliography"])
    data["printed_bibliography_labels"] = labels
    by_number = {}
    for identifier, evidence in labels.items():
        by_number.setdefault(evidence["printed_number"], []).append(identifier)
    heights = {p["page"]: p["height"] for p in data["pages"]}
    tables = []
    for block in data["docling"].get("blocks", []):
        if block["label"] != "table":
            continue
        for prov in block.get("provenance", []):
            b = prov["bbox"]
            height = heights[prov["page_no"]]
            if b.get("coord_origin") == "BOTTOMLEFT":
                rect = [b["l"], height - b["t"], b["r"], height - b["b"]]
            else:
                rect = [b["l"], b["t"], b["r"], b["b"]]
            tables.append((block["id"], prov["page_no"], pymupdf.Rect(rect)))
    for candidate in data.get("unlinked_numeric_pdf_groups", []):
        nums = candidate["expanded_numbers"]
        if not nums or any(n <= 0 or len(by_number.get(n, [])) != 1 for n in nums):
            continue
        associated = []
        for table_id, page, rect in tables:
            if page != candidate["page"]:
                continue
            if all(rect.contains(pymupdf.Rect(b)) for b in candidate["bboxes"]):
                associated.append(table_id)
        if not associated:
            continue
        # Explicit printed labels can never also count as in-text citations.
        if any(e["page"] == candidate["page"] and any(pymupdf.Rect(e["bbox"]).intersects(pymupdf.Rect(b)) for b in candidate["bboxes"]) for e in labels.values()):
            continue
        group = {**candidate, "id": f"recovered_table_group_{len(data['recovered_pdf_table_citation_groups']) + 1}",
                 "numeric_targets": [{"number": n, "target_ids": by_number[n]} for n in nums],
                 "method": "original_pdf_brackets_plus_docling_table_plus_printed_bibliography_labels",
                 "docling_table_ids": associated, "grobid_mention_ids": [],
                 "resolution": "resolved_by_pdf_evidence", "origin": "top-left", "unit": "PDF point"}
        data["recovered_pdf_table_citation_groups"].append(group)
