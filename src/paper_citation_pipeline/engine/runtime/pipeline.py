#!/usr/bin/env python3
"""Original PDF -> parallel GROBID/Docling -> provenance-aware JSON + reading MD."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
from importlib.metadata import version
import json
import logging
from pathlib import Path
import re
import subprocess
import sys
import time
import unicodedata

from lxml import etree
import requests

ROOT = Path(__file__).resolve().parent
NS = {"t": "http://www.tei-c.org/ns/1.0"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")
LOG = logging.getLogger("paper_pipeline")


def dump_json(path, data):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def text(element):
    return "" if element is None else "".join(element.itertext())


def clean(element):
    return " ".join(text(element).split())


def first(node, query):
    nodes = node.xpath(query, namespaces=NS)
    return nodes[0] if nodes else None


def coords(raw):
    result = []
    for part in (raw or "").split(";"):
        try:
            page, x, y, w, h = map(float, part.split(","))
            result.append({"page": int(page), "x": x, "y": y,
                           "width": w, "height": h,
                           "origin": "top-left", "unit": "PDF point"})
        except ValueError:
            continue
    return result


def all_coords(node):
    return coords(node.get("coords")) or [
        c for child in node.xpath(".//*[@coords]") for c in coords(child.get("coords"))
    ]


def numbers(marker):
    """Expand only wholly numeric markers, never author-year strings or prose."""
    # GROBID splits multi-citation brackets into fragments such as '[1,' and '2]'.
    value = marker.translate(SUPERSCRIPTS).strip().strip("[](){} ,;\t\r\n")
    value = re.sub(r"[–—−]", "-", value)
    if not re.fullmatch(r"\d+(?:\s*(?:-|,|;)\s*\d+)*", value):
        return []
    result = []
    for part in re.split(r"[,;]", value):
        endpoints = [int(x.strip()) for x in part.split("-")]
        if len(endpoints) == 1:
            result.extend(endpoints)
        elif len(endpoints) == 2 and 0 < endpoints[0] <= endpoints[1] <= endpoints[0] + 500:
            result.extend(range(endpoints[0], endpoints[1] + 1))
        else:
            return []
    return list(dict.fromkeys(result))


def authors(node):
    result = []
    for author in node.xpath("./t:author", namespaces=NS):
        name = first(author, "./t:persName")
        organization = clean(first(author, "./t:orgName"))
        direct_name = (author.text or "").strip()
        if name is None and not organization and not direct_name:
            continue  # affiliation-only TEI author nodes are not people
        given = " ".join(clean(e) for e in author.xpath("./t:persName/t:forename", namespaces=NS))
        family = clean(first(author, "./t:persName/t:surname"))
        result.append({"name": " ".join(filter(None, [given, family])) or organization or direct_name or clean(name),
                       "given": given or None, "family": family or None,
                       "affiliations": [clean(first(e, "./t:note[@type='raw_affiliation']")) or clean(e) for e in author.xpath("./t:affiliation", namespaces=NS)],
                       "coordinates": all_coords(name) if name is not None else []})
    return result


def inline_refs(node):
    """Preserve exact TEI text and character offsets, including repeated markers."""
    parts, found = [], []
    position = 0

    def add(s):
        nonlocal position
        if s:
            parts.append(s)
            position += len(s)

    def walk(current):
        start = position
        add(current.text)
        for child in current:
            walk(child)
            add(child.tail)
        if etree.QName(current).localname == "ref" and current.get("type") == "bibr":
            found.append((current, start, position))

    walk(node)
    return "".join(parts), sorted(found, key=lambda r: r[1])


def parse_tei(raw):
    root = etree.fromstring(raw, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    if etree.QName(root).localname != "TEI":
        raise ValueError("Response is not a TEI document")
    analytic = first(root, ".//t:teiHeader/t:fileDesc/t:sourceDesc/t:biblStruct/t:analytic")
    title = clean(first(root, ".//t:teiHeader/t:fileDesc/t:titleStmt/t:title"))
    bibliography = []
    for i, b in enumerate(root.xpath(".//t:listBibl/t:biblStruct", namespaces=NS)):
        analytic_b = first(b, "./t:analytic")
        author_node = analytic_b if analytic_b is not None else first(b, "./t:monogr")
        date = first(b, ".//t:imprint/t:date")
        raw_citation = clean(first(b, "./t:note[@type='raw_reference']"))
        raw_year_match = re.search(r"\b(?:18|19|20)\d{2}[a-z]?\b", raw_citation)
        raw_year = raw_year_match.group() if raw_year_match else None
        parsed_year = (date.get("when") or clean(date)) if date is not None else None
        year_label = raw_year if raw_year and parsed_year and raw_year[:4] == parsed_year[:4] else parsed_year
        raw_author_prefix = raw_citation.split(",", 1)[0].strip() if "," in raw_citation else None
        explicit_number = b.get("n")
        label = first(b, "./t:label")
        if not explicit_number and label is not None:
            explicit_number = clean(label)
        if not explicit_number:
            match = re.match(r"^\s*(?:\[(\d+)\]|(\d+)\.)\s+", raw_citation)
            if match:
                explicit_number = next(v for v in match.groups() if v)
        numeric_label = numbers(explicit_number or "")
        bibliography.append({
            "id": b.get(XML_ID) or f"bibliography_{i}", "order": i + 1,
            "label": explicit_number,
            "numeric_label": numeric_label[0] if len(numeric_label) == 1 else None,
            "title": clean(first(b, "./t:analytic/t:title")) or clean(first(b, "./t:monogr/t:title")),
            "authors": authors(author_node) if author_node is not None else [],
            "year": parsed_year, "year_label": year_label,
            "raw_author_prefix": raw_author_prefix,
            "venue": clean(first(b, "./t:monogr/t:title")),
            "identifiers": [{"type": e.get("type"), "value": clean(e)} for e in b.xpath(".//t:idno", namespaces=NS)],
            "raw_citation": raw_citation or None,
            "coordinates": all_coords(b), "source": "grobid_tei",
        })
    sections, div_ids = [], {}
    for i, div in enumerate(root.xpath(".//t:text/t:body//t:div", namespaces=NS)):
        sid = div.get(XML_ID) or f"section_{i + 1}"
        div_ids[div] = sid
        head = first(div, "./t:head")
        ancestor = next((p for p in div.iterancestors() if p in div_ids), None)
        sections.append({"id": sid, "title": clean(head), "number": head.get("n") if head is not None else None,
                         "parent_id": div_ids.get(ancestor), "hierarchy_source": "tei_nesting",
                         "coordinates": all_coords(head) if head is not None else [], "source": "grobid_tei"})
    # GROBID often emits flat divs; infer only unambiguous numbered ancestors.
    numbered = {s["number"].rstrip("."): s["id"] for s in sections if s["number"]}
    for section in sections:
        number = (section["number"] or "").rstrip(".")
        if section["parent_id"] is None and "." in number:
            parent = numbered.get(number.rsplit(".", 1)[0])
            if parent:
                section.update(parent_id=parent, hierarchy_source="heading_number_inference")
    paragraphs, mentions = [], []
    # Capture references in abstracts, captions, notes, headings and body; not bibliography.
    containers = root.xpath(".//t:abstract//t:p | .//t:text//t:p | .//t:text//t:note | .//t:text//t:figDesc | .//t:text//t:head | .//t:text//t:cell", namespaces=NS)
    containers = [e for e in containers if not e.xpath("ancestor::t:listBibl", namespaces=NS)]
    selected = set(containers)
    containers = [e for e in containers if not any(p in selected for p in e.iterancestors())]
    captured_refs = set()

    def append_container(node):
        pid = f"paragraph_{len(paragraphs) + 1}"
        paragraph_text, refs = inline_refs(node)
        if not paragraph_text.strip():
            return
        ancestor = next((p for p in node.iterancestors() if p in div_ids), None)
        in_abstract = bool(node.xpath("ancestor::t:abstract", namespaces=NS))
        paragraph = {"id": pid, "kind": "abstract" if in_abstract else etree.QName(node).localname,
                     "text": paragraph_text, "section_id": div_ids.get(ancestor),
                     "coordinates": all_coords(node), "citation_ids": [], "source": "grobid_tei"}
        paragraphs.append(paragraph)
        for ref, start, end in refs:
            if ref in captured_refs:
                continue
            captured_refs.add(ref)
            marker = paragraph_text[start:end]
            numeric = numbers(marker)
            if re.fullmatch(r"\s*\(?(?:18|19|20)\d{2}[a-z]?\)?\s*", marker) and not any(b["numeric_label"] in numeric for b in bibliography):
                numeric = []  # narrative citations can contain the year alone
            mention = {
                "id": f"citation_{len(mentions) + 1}", "paragraph_id": pid,
                "section_id": paragraph["section_id"], "raw_marker": marker,
                "raw_marker_source": "grobid_tei", "raw_target": ref.get("target"),
                "grobid_targets": [v.lstrip("#") for v in (ref.get("target") or "").split()],
                "expanded_numbers": numeric,
                "style": "numeric" if numeric else "author_year" if re.search(r"\b(?:18|19|20)\d{2}[a-z]?\b", marker) else "unknown",
                "typography": "superscript" if re.search(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]", marker) or "sup" in (ref.get("rend") or "").lower() else "unknown",
                "offsets": {"start": start, "end": end, "unit": "unicode_codepoint", "end_exclusive": True},
                "context": {"text": paragraph_text[max(0, start - 250):min(len(paragraph_text), end + 250)],
                            "start": max(0, start - 250), "end": min(len(paragraph_text), end + 250),
                            "paragraph_text": paragraph_text},
                "coordinates": coords(ref.get("coords")), "source": "grobid_tei",
            }
            mentions.append(mention)
            paragraph["citation_ids"].append(mention["id"])

    for container in containers:
        append_container(container)
    for ref in root.xpath(".//t:ref[@type='bibr']", namespaces=NS):
        if ref not in captured_refs and not ref.xpath("ancestor::t:listBibl", namespaces=NS):
            append_container(ref)
    resolve_mentions(mentions, bibliography)
    for mention in mentions:
        mention["citation_validity"] = "model_extracted"
        start, end = mention["offsets"]["start"], mention["offsets"]["end"]
        paragraph = mention["context"]["paragraph_text"]
        tail = paragraph[end:end + 40]
        # Preserve TEI false positives but flag quantity ranges, never silently turn
        # a particle size (e.g. 1000-3000 μm) into a bibliography relation.
        if (mention["style"] == "numeric" and not mention["grobid_targets"]
                and re.fullmatch(r"\d+", mention["raw_marker"].strip())
                and re.match(r"\s*[-–]\s*\d+\s*(?:μm|µm|mm|cm|kg|mg|km)\b", tail)):
            mention["citation_validity"] = "suspected_non_citation_quantity"
            mention["validity_evidence"] = paragraph[max(0, start - 40):end + 60]
    return {"title": title, "authors": authors(analytic) if analytic is not None else [],
            "unassigned_affiliations": [clean(first(e, "./t:note[@type='raw_affiliation']")) or clean(e)
                                        for e in analytic.xpath("./t:author[not(t:persName) and not(t:orgName)]/t:affiliation", namespaces=NS)] if analytic is not None else [],
            "abstract": clean(first(root, ".//t:profileDesc/t:abstract")),
            "sections": sections, "paragraphs": paragraphs,
            "bibliography": bibliography, "citation_mentions": mentions}


def norm(value):
    return re.sub(r"\W+", "", unicodedata.normalize("NFKC", value).casefold())


def resolve_mentions(mentions, bibliography):
    """TEI targets take precedence. Range expansion requires evidenced number mapping."""
    ids = {b["id"] for b in bibliography}
    label_sets = {}
    for b in bibliography:
        if b["numeric_label"] is not None:
            label_sets.setdefault(b["numeric_label"], set()).add(b["id"])
    for mention in mentions:
        nums = mention["expanded_numbers"]
        targets = mention["grobid_targets"]
        if len(nums) == len(targets) == 1 and targets[0] in ids:
            label_sets.setdefault(nums[0], set()).add(targets[0])
    label_map = {k: next(iter(v)) for k, v in label_sets.items() if len(v) == 1}
    for mention in mentions:
        links = [{"target_id": t, "method": "grobid_target", "confidence": None}
                 for t in dict.fromkeys(mention["grobid_targets"]) if t in ids]
        invalid = [t for t in mention["grobid_targets"] if t not in ids]
        numeric_targets = [{"number": n, "target_id": label_map.get(n)} for n in mention["expanded_numbers"]]
        for entry in numeric_targets:
            if entry["target_id"] and entry["target_id"] not in [l["target_id"] for l in links]:
                links.append({"target_id": entry["target_id"], "method": "evidenced_numeric_label", "confidence": None})
        candidates = []
        if not links and mention["style"] == "author_year":
            # Conservative fallback: single year + first-author surname; ambiguity stays unresolved.
            years = re.findall(r"\b(?:18|19|20)\d{2}[a-z]?\b", mention["raw_marker"])
            if len(years) == 1:
                lead = re.split(r"\bet\s+al\b|[,;&(]", mention["raw_marker"].lstrip("( "), maxsplit=1)[0]
                for b in bibliography:
                    family = b["authors"][0].get("family") if b["authors"] else None
                    aliases = {norm(v) for v in (family, b.get("raw_author_prefix")) if v}
                    year_label = b.get("year_label") or b["year"] or ""
                    if norm(lead) in aliases and year_label == years[0]:
                        candidates.append(b["id"])
                if len(candidates) == 1:
                    links.append({"target_id": candidates[0], "method": "unique_author_year_inference", "confidence": None})
        unresolved_numbers = [e["number"] for e in numeric_targets if e["target_id"] is None]
        # An explicit TEI target for a single number itself resolves that number.
        status = "resolved" if links and not invalid and not unresolved_numbers else "partial" if links else "unresolved"
        mention.update(target_ids=[l["target_id"] for l in links], links=links,
                       numeric_targets=numeric_targets, unresolved_numbers=unresolved_numbers,
                       invalid_targets=invalid, candidate_target_ids=candidates, resolution=status)


def pdf_evidence(pdf, data):
    """Use original PDF spans to verify superscript typography, never invent reference targets."""
    import pymupdf
    with pymupdf.open(pdf) as doc:
        data["page_count"] = len(doc)
        pages = [{"page": i + 1, "width": p.rect.width, "height": p.rect.height,
                  "unit": "PDF point"} for i, p in enumerate(doc)]
        superscripts = []
        for i, page in enumerate(doc):
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    line_text = "".join(s["text"] for s in line["spans"])
                    for span in line["spans"]:
                        if (span["flags"] & 1 or re.search(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]", span["text"])) and numbers(span["text"]):
                            superscripts.append({"page": i + 1, "bbox": span["bbox"], "raw_marker": span["text"],
                                                 "expanded_numbers": numbers(span["text"]), "context": line_text,
                                                 "source": "original_pdf_span", "matched_citation_ids": []})
        for m in data["citation_mentions"]:
            matches = []
            for span in superscripts:
                if not set(span["expanded_numbers"]) & set(m["expanded_numbers"]):
                    continue
                for c in m["coordinates"]:
                    x0, y0, x1, y1 = span["bbox"]
                    if c["page"] == span["page"] and min(x1, c["x"] + c["width"]) > max(x0, c["x"]) and min(y1, c["y"] + c["height"]) > max(y0, c["y"]):
                        matches.append(span)
                        span["matched_citation_ids"].append(m["id"])
                        break
            if matches:
                m["typography"] = "superscript"
                m["pdf_marker_evidence"] = [{k: v for k, v in s.items() if k != "matched_citation_ids"} for s in matches]
        data["pages"] = pages
        data["unlinked_superscript_candidates"] = [s for s in superscripts if not s["matched_citation_ids"]]
        data["pdf_metadata"] = doc.metadata
        data["unlinked_numeric_pdf_groups"] = []
        data["pdf_citation_groups"] = pdf_citation_groups(doc, data["citation_mentions"], data["unlinked_numeric_pdf_groups"])


def pdf_citation_groups(doc, mentions, unlinked=None):
    """Recover printed numeric marker groups from PDF characters and TEI coordinates.

    GROBID can replace [79–81] with [79][80][81]. Keep both representations,
    including precise original-PDF geometry, without consulting Markdown.
    """
    by_page = {}
    for m in mentions:
        if m.get("style") != "numeric" or m.get("citation_validity", "").startswith("suspected_non_citation"):
            continue
        m["pdf_group_ids"] = []
        for c in m["coordinates"]:
            by_page.setdefault(c["page"], []).append((m, c))
    groups = []
    pattern = re.compile(r"\[\s*\d+(?:\s*[,;–—−-]\s*\d+)*\s*\]")
    for page_number, page in enumerate(doc, 1):
        if not by_page:
            continue
        for block in page.get_text("rawdict").get("blocks", []):
            chars = []
            for line_index, line in enumerate(block.get("lines", [])):
                for span in line["spans"]:
                    chars.extend((char["c"], char["bbox"], line_index) for char in span["chars"])
                chars.append(("\n", None, line_index))
            block_text = "".join(c[0] for c in chars)
            for match in pattern.finditer(block_text):
                expanded = numbers(match.group())
                if not expanded:
                    continue
                line_rects = {}
                for _, box, line_index in chars[match.start():match.end()]:
                    if box is None:
                        continue
                    if line_index not in line_rects:
                        line_rects[line_index] = list(box)
                    else:
                        r = line_rects[line_index]
                        r[:] = [min(r[0], box[0]), min(r[1], box[1]), max(r[2], box[2]), max(r[3], box[3])]
                linked = {}
                for m, c in by_page.get(page_number, []):
                    for box in line_rects.values():
                        if (min(box[2], c["x"] + c["width"]) > max(box[0], c["x"])
                                and min(box[3], c["y"] + c["height"]) > max(box[1], c["y"])):
                            if set(m["expanded_numbers"]) & set(expanded):
                                linked[m["id"]] = m
                if not linked:
                    if unlinked is not None:
                        unlinked.append({"raw_marker": match.group(), "expanded_numbers": expanded,
                                         "page": page_number, "bboxes": list(line_rects.values()),
                                         "context": block_text[max(0, match.start()-160):match.end()+160],
                                         "source": "original_pdf_characters"})
                    continue
                numeric_targets = []
                for n in expanded:
                    ids = sorted({entry["target_id"] for m in linked.values() for entry in m["numeric_targets"]
                                  if entry["number"] == n and entry["target_id"]})
                    numeric_targets.append({"number": n, "target_ids": ids})
                group_id = f"pdf_group_{len(groups) + 1}"
                unresolved = [entry["number"] for entry in numeric_targets if len(entry["target_ids"]) != 1]
                groups.append({"id": group_id, "raw_marker": match.group(), "source": "original_pdf_characters",
                               "page": page_number, "bboxes": list(line_rects.values()), "origin": "top-left", "unit": "PDF point",
                               "expanded_numbers": expanded, "numeric_targets": numeric_targets,
                               "citation_ids": list(linked), "unresolved_numbers": unresolved,
                               "resolution": "resolved" if not unresolved else "partial",
                               "context": block_text[max(0, match.start() - 160):match.end() + 160]})
                for m in linked.values():
                    m["pdf_group_ids"].append(group_id)
    return groups


def merge_docling(data, docling):
    """Keep both representations; attach scored, page-constrained structural alignments."""
    blocks = docling.get("blocks", [])
    by_page = {}
    for block in blocks:
        for page in {p["page_no"] for p in block.get("provenance", [])}:
            by_page.setdefault(page, []).append(block)
    alignments = []
    for p in data["paragraphs"]:
        candidates = {b["id"]: b for c in p["coordinates"] for b in by_page.get(c["page"], [])}
        if not candidates:
            candidates = {b["id"]: b for b in blocks}
        a = norm(p["text"])
        matched = []
        for block in candidates.values():
            b = norm(block["text"])
            if min(len(a), len(b)) < 30:
                continue
            if a in b or b in a:
                score = min(len(a), len(b)) / max(len(a), len(b))
                if score >= 0.25:
                    matched.append({"docling_id": block["id"], "score": round(score, 4), "method": "text_containment"})
            elif 0.5 < len(a) / len(b) < 2:
                score = SequenceMatcher(None, a, b, autojunk=False).ratio()
                if score >= 0.8:
                    matched.append({"docling_id": block["id"], "score": round(score, 4), "method": "text_similarity"})
        p["docling_matches"] = sorted(matched, key=lambda x: -x["score"])
        if matched:
            alignments.append({"paragraph_id": p["id"], "matches": p["docling_matches"]})
    doc_sections, stack = [], []
    for block in blocks:
        if block["label"] != "section_header":
            continue
        level = block.get("heading_level") or 1
        while stack and stack[-1][0] >= level:
            stack.pop()
        doc_sections.append({"id": block["id"], "title": block["text"], "level": level,
                             "parent_id": stack[-1][1] if stack else None,
                             "provenance": block["provenance"], "source": "docling"})
        stack.append((level, block["id"]))
    data["docling"] = {k: v for k, v in docling.items() if k != "reading_markdown"}
    data["docling"]["sections"] = doc_sections
    data["merge"] = {"citation_authority": "grobid_tei", "body_layout_authority": "docling_structured_json",
                     "strategy": "preserve_both_and_align_by_page_and_text", "alignments": alignments,
                     "aligned_paragraphs": len(alignments),
                     "unmatched_docling_ids": [b["id"] for b in blocks if b["id"] not in {m["docling_id"] for a in alignments for m in a["matches"]}]}


def grobid_stage(pdf, destination, url, timeout, retries):
    # Ignore HTTP_PROXY, HTTPS_PROXY, ALL_PROXY and netrc for every GROBID request.
    session = requests.Session()
    session.trust_env = False
    params = [("consolidateHeader", "0"), ("consolidateCitations", "0"),
              ("includeRawCitations", "1"), ("includeRawAffiliations", "1"),
              ("segmentSentences", "1"), ("generateIDs", "1")]
    params += [("teiCoordinates", tag) for tag in ("ref", "biblStruct", "p", "s", "head", "persName", "figure", "formula")]
    try:
        for attempt in range(retries + 1):
            try:
                with pdf.open("rb") as stream:
                    response = session.post(url.rstrip("/") + "/api/processFulltextDocument",
                                            files={"input": (pdf.name, stream, "application/pdf")},
                                            data=params, headers={"Accept": "application/xml"},
                                            timeout=(15, timeout))
                if response.status_code == 204 or not response.content:
                    raise ValueError("GROBID returned no content")
                response.raise_for_status()
                # Preserve exact response bytes, even before semantic extraction.
                destination.write_bytes(response.content)
                parse_tei(response.content)
                return {"status": "success", "http_status": response.status_code}
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
                retryable = not isinstance(exc, requests.HTTPError) or exc.response.status_code in {429, 502, 503, 504}
                if not retryable or attempt == retries:
                    raise
                LOG.warning("GROBID retry %s/%s for %s: %s", attempt + 1, retries, pdf.name, exc)
                time.sleep(min(5 * (attempt + 1), 20))
    finally:
        session.close()


def docling_stage(pdf, destination, timeout, ocr, log_path):
    command = [sys.executable, str(ROOT / "docling_worker.py"), str(pdf), str(destination)]
    if ocr:
        command.append("--ocr")
    with log_path.open("w", encoding="utf-8") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        tail = log_path.read_text(encoding="utf-8")[-3000:]
        raise RuntimeError(f"Docling exited {result.returncode}; see {log_path}: {tail}")
    payload = json.loads(destination.read_text(encoding="utf-8"))
    return {"status": payload["status"], "page_count": payload["page_count"], "errors": payload["errors"]}


def process_pdf(pdf, args):
    started = time.perf_counter()
    with pdf.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    tei = args.output / "tei" / f"{pdf.stem}.tei.xml"
    docling_path = args.output / "docling" / f"{pdf.stem}.docling.json"
    manifest = args.output / "json" / f"{pdf.stem}.stages.json"
    config = {"grobid_url": args.grobid_url, "ocr": args.ocr, "stage_schema": 1,
              "docling_version": version("docling")}
    previous = json.loads(manifest.read_text()) if args.resume and manifest.exists() else {}
    reusable = previous.get("sha256") == digest and previous.get("config") == config
    stages = {}

    def run_stage(name, destination, action):
        start = time.perf_counter()
        if reusable and destination.exists() and previous.get("stages", {}).get(name, {}).get("status") == "success":
            LOG.info("%s: reuse %s", pdf.name, name)
            prior = previous["stages"][name]
            return {**prior, "cached": True, "seconds": 0.0,
                    "original_seconds": prior.get("original_seconds", prior["seconds"])}
        LOG.info("%s: start %s", pdf.name, name)
        try:
            info = action()
            elapsed = round(time.perf_counter() - start, 3)
            return {**info, "cached": False, "seconds": elapsed, "original_seconds": elapsed}
        except Exception as exc:
            LOG.exception("%s: %s failed", pdf.name, name)
            return {"status": "failed", "error": str(exc), "seconds": round(time.perf_counter() - start, 3)}

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = {
            pool.submit(run_stage, "grobid", tei, lambda: grobid_stage(pdf, tei, args.grobid_url, args.grobid_timeout, args.retries)): "grobid",
            pool.submit(run_stage, "docling", docling_path, lambda: (args.docling_worker.run(pdf, docling_path, args.logs / f"{pdf.stem}.docling.log", args.docling_timeout) if getattr(args, "docling_worker", None) else docling_stage(pdf, docling_path, args.docling_timeout, args.ocr, args.logs / f"{pdf.stem}.docling.log"))): "docling",
        }
        for future in as_completed(pending):
            name = pending[future]
            stages[name] = future.result()
            LOG.info("%s: %s %s (%.1fs)", pdf.name, name, stages[name]["status"], stages[name]["seconds"])
            dump_json(manifest, {"sha256": digest, "config": config, "stages": stages})
    empty = {"title": None, "authors": [], "abstract": None, "sections": [], "paragraphs": [], "bibliography": [], "citation_mentions": []}
    data = parse_tei(tei.read_bytes()) if stages["grobid"]["status"] == "success" else empty
    data.update(schema_version="1.0.0", source={"pdf": str(pdf), "sha256": digest},
                created_at=datetime.now(timezone.utc).isoformat(), stages=stages,
                software={name: version(name) for name in ("docling", "docling-core", "PyMuPDF", "requests", "lxml")})
    pdf_evidence(pdf, data)
    docling = json.loads(docling_path.read_text()) if stages["docling"]["status"] in {"success", "partial_success"} else {}
    merge_docling(data, docling)
    from citation_recovery import recover_table_citations
    recover_table_citations(pdf, data)
    statuses = [s["status"] for s in stages.values()]
    data["status"] = "success" if all(s == "success" for s in statuses) else "failed" if all(s == "failed" for s in statuses) else "partial_success"
    mentions = data["citation_mentions"]
    data["quality"] = {"bibliography_count": len(data["bibliography"]), "citation_mentions": len(mentions),
                       "resolved_mentions": sum(m["resolution"] == "resolved" for m in mentions),
                       "partial_mentions": sum(m["resolution"] == "partial" for m in mentions),
                       "unresolved_mentions": sum(m["resolution"] == "unresolved" for m in mentions),
                       "citation_edges": sum(len(m["target_ids"]) for m in mentions),
                       "warnings": []}
    data["quality"]["suspected_non_citation_ids"] = [m["id"] for m in mentions if m.get("citation_validity", "").startswith("suspected_non_citation")]
    data["quality"]["printed_numeric_groups"] = len(data["pdf_citation_groups"])
    data["quality"]["printed_numeric_range_groups"] = sum(bool(re.search(r"[-–—−]", g["raw_marker"])) for g in data["pdf_citation_groups"])
    data["quality"]["incomplete_printed_group_ids"] = [g["id"] for g in data["pdf_citation_groups"] if g["resolution"] != "resolved"]
    data["quality"]["recovered_pdf_table_groups"] = len(data["recovered_pdf_table_citation_groups"])
    data["quality"]["recovered_pdf_table_edges"] = sum(len(e["target_ids"]) for g in data["recovered_pdf_table_citation_groups"] for e in g["numeric_targets"])
    suspect_entries = []
    for b in data["bibliography"]:
        # Several publication-year/title starts can signal references merged by GROBID.
        starts = re.findall(r",\s*(?:18|19|20)\d{2}[a-z]?\.\s+[A-Z]", b["raw_citation"] or "")
        if len(starts) > 1:
            suspect_entries.append(b["id"])
    data["quality"]["possible_merged_bibliography_ids"] = suspect_entries
    if suspect_entries:
        data["quality"]["warnings"].append("Some bibliography entries contain multiple publication-year/title starts; check possible GROBID segmentation errors.")
    if not mentions:
        data["quality"]["warnings"].append("No GROBID citation mentions found; this does not prove the PDF has no citations.")
    if data["unlinked_superscript_candidates"]:
        data["quality"]["warnings"].append("Unlinked superscript numbers may be footnotes, exponents or missed citations; inspect before using.")
    if docling and not any(b["text"].strip() for b in docling["blocks"]):
        data["quality"]["warnings"].append("Docling text is empty; rerun with --ocr for scanned PDFs.")
        data["status"] = "partial_success"
    data["timing_seconds"] = {"total": round(time.perf_counter() - started, 3), **{k: v["seconds"] for k, v in stages.items()}}
    dump_json(args.output / "json" / f"{pdf.stem}.json", data)
    reading = docling.get("reading_markdown") or "\n\n".join(p["text"] for p in data["paragraphs"])
    markdown = f"<!-- Reading output only. Citation relations: ../json/{pdf.stem}.json -->\n\n" + reading
    if not docling:
        markdown += "\n\n## Bibliography\n\n" + "\n\n".join(b["raw_citation"] or b["title"] for b in data["bibliography"])
    (args.output / "md" / f"{pdf.stem}.md").write_text(markdown, encoding="utf-8")
    LOG.info("%s: %s; %s pages, %s refs, %s mentions; %.1fs", pdf.name, data["status"], data["page_count"], len(data["bibliography"]), len(mentions), data["timing_seconds"]["total"])
    return {"file": pdf.name, "status": data["status"], "page_count": data["page_count"], "timing_seconds": data["timing_seconds"], "quality": data["quality"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "input")
    parser.add_argument("--output", type=Path, default=ROOT / "output")
    parser.add_argument("--logs", type=Path, default=ROOT / "logs")
    parser.add_argument("--grobid-url", default="http://localhost:8070")
    parser.add_argument("--grobid-timeout", type=int, default=600)
    parser.add_argument("--docling-timeout", type=int, default=1800)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--ocr", action="store_true", help="Enable OCR for scanned PDFs")
    parser.add_argument("--resume", action="store_true", help="Reuse successful stages only when source hash and config match")
    parser.add_argument("--only", nargs="+", help="Only process these PDF stems or filenames")
    args = parser.parse_args()
    args.input, args.output, args.logs = (p.resolve() for p in (args.input, args.output, args.logs))
    args.logs.mkdir(parents=True, exist_ok=True)
    for folder in ("tei", "json", "md", "docling"):
        (args.output / folder).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(args.logs / "pipeline.log", encoding="utf-8")])
    files = sorted(p for p in args.input.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
    if args.only:
        selected = {Path(name).stem for name in args.only}
        missing = selected - {p.stem for p in files}
        if missing:
            LOG.error("Requested PDFs missing: %s", sorted(missing))
            return 2
        files = [p for p in files if p.stem in selected]
    if not files:
        LOG.error("No PDF files in %s", args.input)
        return 2
    if len({p.stem.casefold() for p in files}) != len(files):
        LOG.error("Duplicate PDF stems would overwrite output; rename inputs first")
        return 2
    summary = []
    for pdf in files:
        start = time.perf_counter()
        try:
            summary.append(process_pdf(pdf, args))
        except Exception as exc:
            LOG.exception("%s: document failed; continuing batch", pdf.name)
            failure = {"file": pdf.name, "status": "failed", "error": str(exc), "seconds": round(time.perf_counter() - start, 3)}
            dump_json(args.output / "json" / f"{pdf.stem}.json", failure)
            summary.append(failure)
        dump_json(args.output / "run_summary.json", summary)
    return 0 if all(s["status"] == "success" for s in summary) else 1


if __name__ == "__main__":
    sys.exit(main())
