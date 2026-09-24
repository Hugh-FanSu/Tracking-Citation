"""Isolated, timeout-able Docling stage. Never derives citations from Markdown."""
import argparse
import json
from pathlib import Path


def make_converter(ocr):
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions(do_ocr=ocr, do_table_structure=True)
    try:
        from docling.datamodel.pipeline_options import HeadingHierarchyOptions
        options.heading_hierarchy_options = HeadingHierarchyOptions(enabled=True)
        options.generate_parsed_pages = True
    except ImportError:
        pass
    converter = DocumentConverter(format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=options)
    })
    return converter


def convert(converter, pdf, output):
    result = converter.convert(pdf, raises_on_error=False)
    status = result.status.value
    if status not in {"success", "partial_success"}:
        raise RuntimeError(f"Docling status={status}: {result.errors}")
    doc = result.document
    blocks = []
    for item, tree_depth in doc.iterate_items():
        raw = item.model_dump(mode="json")
        blocks.append({
            "id": item.self_ref,
            "label": item.label.value,
            "text": getattr(item, "text", ""),
            "tree_depth": tree_depth,
            "heading_level": getattr(item, "level", None),
            "parent": raw.get("parent"),
            "provenance": raw.get("prov", []),
        })
    payload = {
        "status": status, "errors": [str(e) for e in result.errors],
        "page_count": len(doc.pages), "blocks": blocks,
        "document": doc.export_to_dict(),
        "reading_markdown": doc.export_to_markdown(),
    }
    temp = output.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(output)


def serve(connection, ocr):
    # One model instance per batch; each request remains isolated by a timeout.
    import contextlib
    import traceback
    converter = None
    try:
        while True:
            request = connection.recv()
            if request is None:break
            pdf, output, log = map(Path, request)
            try:
                with log.open('a', encoding='utf-8') as stream, contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                    if converter is None:converter = make_converter(ocr)
                    convert(converter, pdf, output)
                connection.send({'ok': True})
            except Exception:
                connection.send({'ok': False, 'error': traceback.format_exc()})
    except EOFError:
        pass
    finally:
        connection.close()


class Worker:
    def __init__(self, ocr=False, target=serve):
        self.ocr, self.target = ocr, target
        self.process = self.connection = None

    def close(self, graceful=True):
        if graceful and self.process is not None and self.process.is_alive():
            try:self.connection.send(None)
            except (OSError,EOFError):pass
            self.process.join(timeout=5)
        if self.connection is not None:self.connection.close()
        if self.process is not None:
            if self.process.is_alive():self.process.terminate()
            self.process.join(timeout=5)
            if self.process.is_alive():self.process.kill();self.process.join()
            self.process.close()
        self.process = self.connection = None

    def run(self, pdf, output, log, timeout):
        import multiprocessing
        if self.process is None or not self.process.is_alive():
            self.close()
            ctx = multiprocessing.get_context('spawn')
            self.connection, child = ctx.Pipe()
            self.process = ctx.Process(target=self.target, args=(child, self.ocr), daemon=True)
            self.process.start();child.close()
        try:
            self.connection.send((str(pdf), str(output), str(log)))
            if not self.connection.poll(timeout):raise TimeoutError(f'Docling exceeded {timeout}s: {pdf}')
            result = self.connection.recv()
            if not result['ok']:raise RuntimeError(result['error'])
        except BaseException:
            self.close(graceful=False)
            raise
        payload = json.loads(Path(output).read_text())
        return {'status': payload['status'], 'page_count': payload['page_count'], 'errors': payload['errors']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('pdf', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--ocr', action='store_true')
    args = parser.parse_args()
    convert(make_converter(args.ocr), args.pdf, args.output)


if __name__ == '__main__':main()
