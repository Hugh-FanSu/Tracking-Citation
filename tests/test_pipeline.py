import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/paper_citation_pipeline/engine/runtime'))
from pipeline import numbers, parse_tei, grobid_stage, merge_docling, main, pdf_evidence, pdf_citation_groups
from citation_recovery import recover_table_citations


def fixture(body, refs):
    return f'''<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader>
    <fileDesc><titleStmt><title>Study</title></titleStmt><sourceDesc><biblStruct>
    <analytic><author><persName><forename>Alice</forename><surname>Smith</surname></persName></author></analytic>
    </biblStruct></sourceDesc></fileDesc></teiHeader><text><body>{body}</body>
    <back><listBibl>{refs}</listBibl></back></text></TEI>'''.encode()


def bib(identifier, label=None, family="Smith", year="2020"):
    n = f' n="{label}"' if label is not None else ""
    return f'''<biblStruct xml:id="{identifier}"{n}><analytic><title>Paper {identifier}</title>
    <author><persName><surname>{family}</surname></persName></author></analytic>
    <monogr><imprint><date when="{year}"/></imprint></monogr></biblStruct>'''


class CitationTests(unittest.TestCase):
    @patch('citation_recovery.printed_bibliography_labels')
    def test_recover_table_range_with_three_sources(self, labels):
        labels.return_value = {f'b{n}': {'printed_number': n, 'page': 3, 'bbox': [0, n, 5, n+1]} for n in (15,16,17,18)}
        data = {'citation_mentions': [{'style': 'numeric'}] * 6,
                'bibliography': [], 'pages': [{'page': 1, 'height': 800}],
                'docling': {'blocks': [{'id': '#/tables/0', 'label': 'table', 'provenance': [{'page_no': 1, 'bbox': {'l': 0, 'r': 300, 't': 750, 'b': 600, 'coord_origin': 'BOTTOMLEFT'}}]}]},
                'unlinked_numeric_pdf_groups': [{'raw_marker': '[15–18]', 'expanded_numbers': [15,16,17,18], 'page': 1, 'bboxes': [[100,100,140,115]], 'context': 'References column'}]}
        recover_table_citations(Path('unused.pdf'), data)
        groups = data['recovered_pdf_table_citation_groups']
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['numeric_targets'][2]['target_ids'], ['b17'])
        # Same glyphs in an author-year document must not become recovered citations.
        data['citation_mentions'] = [{'style': 'author_year'}] * 6
        recover_table_citations(Path('unused.pdf'), data)
        self.assertEqual(data['recovered_pdf_table_citation_groups'], [])

    def test_numeric_ranges_and_superscripts(self):
        self.assertEqual(numbers("[15-18]"), [15, 16, 17, 18])
        self.assertEqual(numbers("¹⁵–¹⁸"), [15, 16, 17, 18])
        self.assertEqual(numbers("[2, 5–7; 9]"), [2, 5, 6, 7, 9])
        self.assertEqual(numbers("Smith, 2020"), [])
        self.assertEqual(numbers("[18-15]"), [])
        self.assertEqual(numbers("[1,"), [1])
        self.assertEqual(numbers("2]"), [2])
        self.assertEqual(numbers("[3;"), [3])

    def test_particle_size_mislabel_is_flagged_not_linked(self):
        d = parse_tei(fixture('<p>Particles <ref type="bibr">1000</ref>-3000 μm in size.</p>', bib("a")))
        m = d["citation_mentions"][0]
        self.assertEqual(m["citation_validity"], "suspected_non_citation_quantity")
        self.assertEqual(m["target_ids"], [])

    def test_range_uses_labels_not_bibliography_order(self):
        refs = "".join(bib(f"unrelated_id_{i}", n) for i, n in enumerate([18, 15, 17, 16]))
        data = parse_tei(fixture('<div><p>Evidence <ref type="bibr" target="#unrelated_id_1">[15-18]</ref>.</p></div>', refs))
        m = data["citation_mentions"][0]
        self.assertEqual(m["resolution"], "resolved")
        self.assertEqual([e["target_id"] for e in m["numeric_targets"]], ["unrelated_id_1", "unrelated_id_3", "unrelated_id_2", "unrelated_id_0"])

    def test_pdf_range_is_preserved_after_tei_expansion(self):
        page = MagicMock()
        marker = '[79–81]'
        chars = [{'c': c, 'bbox': [10+i*2, 10, 12+i*2, 20]} for i, c in enumerate(marker)]
        page.get_text.return_value = {'blocks': [{'lines': [{'spans': [{'chars': chars}]}]}]}
        mentions = []
        for n in (79, 80, 81):
            mentions.append({'id': f'c{n}', 'style': 'numeric', 'expanded_numbers': [n],
                             'coordinates': [{'page': 1, 'x': 10, 'y': 10, 'width': 14, 'height': 10}],
                             'numeric_targets': [{'number': n, 'target_id': f'b{n-1}'}]})
        result = pdf_citation_groups([page], mentions)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['raw_marker'], '[79–81]')
        self.assertEqual(result[0]['expanded_numbers'], [79, 80, 81])
        self.assertEqual(result[0]['resolution'], 'resolved')
        self.assertEqual(result[0]['numeric_targets'][1]['target_ids'], ['b79'])
        # If the middle TEI edge is missing, flag partial coverage rather than invent it.
        result = pdf_citation_groups([page], mentions[::2])
        self.assertEqual(result[0]['unresolved_numbers'], [80])

    def test_missing_range_targets_not_guessed(self):
        data = parse_tei(fixture('<p><ref type="bibr" target="#b14">[15-18]</ref></p>', ''.join(bib(f"b{i}") for i in range(20))))
        m = data["citation_mentions"][0]
        self.assertEqual(m["target_ids"], ["b14"])
        self.assertEqual(m["unresolved_numbers"], [15, 16, 17, 18])
        self.assertEqual(m["resolution"], "partial")

    def test_exact_offsets_repeated_author_year(self):
        body = '<div><head n="1">Intro</head><p>中文 <ref type="bibr" target="#b1">Smith (2020)</ref> and <ref type="bibr" target="#b1">Smith (2020)</ref>.</p></div>'
        data = parse_tei(fixture(body, bib("b1")))
        mentions = data["citation_mentions"]
        self.assertEqual(len(mentions), 2)
        self.assertNotEqual(mentions[0]["offsets"], mentions[1]["offsets"])
        for m in mentions:
            self.assertEqual(m["context"]["paragraph_text"][m["offsets"]["start"]:m["offsets"]["end"]], m["raw_marker"])
            self.assertEqual(m["target_ids"], ["b1"])

    def test_affiliation_only_author_is_not_a_person(self):
        raw = fixture('<p>Text</p>', '')
        raw = raw.replace(b'</analytic>', b'<author><affiliation><orgName>Institute</orgName></affiliation></author></analytic>', 1)
        data = parse_tei(raw)
        self.assertEqual(len(data["authors"]), 1)
        self.assertEqual(data["unassigned_affiliations"], ["Institute"])

    def test_ambiguous_author_year_and_dangling_target(self):
        data = parse_tei(fixture('<p><ref type="bibr">Smith, 2020</ref> <ref type="bibr" target="#missing">[5]</ref></p>', bib("a") + bib("b")))
        self.assertEqual(data["citation_mentions"][0]["resolution"], "unresolved")
        self.assertEqual(data["citation_mentions"][0]["candidate_target_ids"], ["a", "b"])
        self.assertEqual(data["citation_mentions"][1]["invalid_targets"], ["missing"])

    def test_hierarchy_and_caption_refs(self):
        data = parse_tei(fixture('<div><head n="2">Methods</head><p>Text</p></div><div><head n="2.1">Subsection</head><figure><figDesc><p>Caption <ref type="bibr" target="#b">[1]</ref></p></figDesc></figure></div>', bib("b")))
        self.assertEqual(data["sections"][1]["parent_id"], data["sections"][0]["id"])
        self.assertEqual(len(data["citation_mentions"]), 1)

    def test_conflicting_labels_are_not_inferred(self):
        data = parse_tei(fixture('<p><ref type="bibr">[1]</ref></p>', bib("a", 1) + bib("b", 1)))
        self.assertEqual(data["citation_mentions"][0]["target_ids"], [])

    def test_year_suffix_and_corporate_author_from_raw_tei(self):
        a = bib("a").replace('</biblStruct>', '<note type="raw_reference">Smith, A., 2020a. First.</note></biblStruct>')
        b = bib("b").replace('</biblStruct>', '<note type="raw_reference">Smith, A., 2020b. Second.</note></biblStruct>')
        org = '<biblStruct xml:id="u"><monogr><imprint><date when="2023"/></imprint></monogr><note type="raw_reference">UNEP, 2023. Report.</note></biblStruct>'
        d = parse_tei(fixture('<p><ref type="bibr">Smith et al. (2020b)</ref> <ref type="bibr">(UNEP, 2023)</ref></p>', a + b + org))
        self.assertEqual(d["citation_mentions"][0]["target_ids"], ["b"])
        self.assertEqual(d["citation_mentions"][1]["target_ids"], ["u"])

    def test_bare_narrative_year_is_not_numeric_citation(self):
        d = parse_tei(fixture('<p>Smith <ref type="bibr" target="#a">(2020)</ref></p>', bib("a")))
        self.assertEqual(d["citation_mentions"][0]["style"], "author_year")
        self.assertEqual(d["citation_mentions"][0]["expanded_numbers"], [])

    def test_docling_merge_never_creates_citations(self):
        data = {"paragraphs": [{"id": "p1", "text": "A long paragraph about marine debris evidence and effects.", "coordinates": [{"page": 1}]}], "citation_mentions": []}
        docling = {"blocks": [{"id": "#/texts/0", "label": "text", "text": data["paragraphs"][0]["text"], "provenance": [{"page_no": 1}]}], "reading_markdown": "Invented [999]"}
        merge_docling(data, docling)
        self.assertEqual(data["citation_mentions"], [])
        self.assertEqual(data["merge"]["aligned_paragraphs"], 1)
        self.assertNotIn("reading_markdown", data["docling"])

    @patch("pipeline.requests.Session")
    def test_requests_disable_proxy_and_send_original_bytes(self, factory):
        session = MagicMock()
        factory.return_value = session
        captured = []
        response = MagicMock(status_code=200, content=fixture("<p>Test</p>", ""))
        def post(*args, **kwargs):
            captured.append(kwargs["files"]["input"][1].read())
            return response
        session.post.side_effect = post
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "paper.pdf"
            source.write_bytes(b"%PDF-original-input")
            grobid_stage(source, Path(tmp) / "out.xml", "http://localhost:8070", 30, 0)
        self.assertFalse(session.trust_env)
        self.assertEqual(captured, [b"%PDF-original-input"])

    @patch("pipeline.process_pdf")
    def test_batch_continues_after_one_document_fails(self, process):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = root / "input"
            inputs.mkdir()
            (inputs / "a.pdf").touch()
            (inputs / "b.PDF").touch()
            process.side_effect = [ValueError("corrupt PDF"), {"file": "b.PDF", "status": "success"}]
            argv = ["pipeline", "--input", str(inputs), "--output", str(root / "output"), "--logs", str(root / "logs")]
            with patch("sys.argv", argv), patch("pipeline.LOG"):
                result = main()
            self.assertEqual(result, 1)
            self.assertEqual(process.call_count, 2)
            import json
            summary = json.loads((root / "output/run_summary.json").read_text())
            self.assertEqual([v["status"] for v in summary], ["failed", "success"])

    @patch("pymupdf.open")
    def test_superscript_detection_requires_same_page_and_overlap(self, open_pdf):
        doc = MagicMock()
        page = MagicMock()
        page.rect.width, page.rect.height = 600, 800
        page.get_text.return_value = {"blocks": [{"lines": [{"spans": [
            {"text": "15", "flags": 1, "bbox": [10, 10, 20, 20]},
        ]}]}]}
        doc.__iter__.return_value = iter([page])
        doc.__len__.return_value = 1
        doc.metadata = {}
        open_pdf.return_value.__enter__.return_value = doc
        # Supply a fresh iterator for each of the two passes through the PDF.
        doc.__iter__.side_effect = lambda: iter([page])
        data = {"citation_mentions": [{"id": "c1", "expanded_numbers": [15], "coordinates": [{"page": 1, "x": 9, "y": 9, "width": 12, "height": 12}]}]}
        pdf_evidence(Path("unused.pdf"), data)
        self.assertEqual(data["citation_mentions"][0]["typography"], "superscript")
        self.assertEqual(data["unlinked_superscript_candidates"], [])


if __name__ == "__main__":
    unittest.main()
