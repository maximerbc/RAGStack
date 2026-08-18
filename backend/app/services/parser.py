from __future__ import annotations

import re
from pathlib import Path

from app.services.chunking import Block
from bs4 import BeautifulSoup


class UnsupportedScannedPDF(ValueError):
    pass


class DocumentParser:
    DOC_TYPES = {".pdf", ".docx", ".html", ".htm"}

    def __init__(self, max_pdf_pages: int = 500):
        self.max_pdf_pages = max_pdf_pages

    def parse(self, path: Path) -> tuple[str, list[Block]]:
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md"}:
            return path.stem, self._parse_text(
                path.read_text(encoding="utf-8"), markdown=suffix == ".md"
            )
        if suffix in {".html", ".htm"}:
            return self._parse_html(path)
        if suffix in self.DOC_TYPES:
            return self._parse_docling(path)
        raise ValueError(f"Unsupported document type: {suffix}")

    def _parse_text(self, text: str, markdown: bool = False) -> list[Block]:
        if not text.strip():
            raise ValueError("The document contains no text")
        headings: list[str] = []
        blocks: list[Block] = []
        for part in re.split(r"\n\s*\n", text):
            part = part.strip()
            if not part:
                continue
            if markdown and re.match(r"^#{1,6}\s+", part):
                level = len(part) - len(part.lstrip("#"))
                heading = re.sub(r"^#{1,6}\s+", "", part.splitlines()[0]).strip()
                headings = headings[: level - 1] + [heading]
                rest = "\n".join(part.splitlines()[1:]).strip()
                if rest:
                    blocks.append(Block(rest, headings.copy()))
            else:
                blocks.append(Block(part, headings.copy()))
        return blocks

    def _parse_html(self, path: Path) -> tuple[str, list[Block]]:
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        for node in soup(["script", "style", "noscript"]):
            node.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else path.stem
        headings: list[str] = []
        blocks: list[Block] = []
        for node in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table"]):
            if node.name.startswith("h"):
                level = int(node.name[1])
                headings = headings[: level - 1] + [node.get_text(" ", strip=True)]
            else:
                text = str(node) if node.name == "table" else node.get_text(" ", strip=True)
                if text:
                    blocks.append(
                        Block(
                            text,
                            headings.copy(),
                            content_type="table" if node.name == "table" else "text",
                        )
                    )
        if not blocks:
            raise ValueError("The document contains no text")
        return title, blocks

    def _parse_docling(self, path: Path) -> tuple[str, list[Block]]:
        from docling.document_converter import DocumentConverter

        result = DocumentConverter().convert(path, max_num_pages=self.max_pdf_pages)
        document = result.document
        title = getattr(document, "name", None) or path.stem
        blocks: list[Block] = []
        headings: list[str] = []
        for item, _level in document.iterate_items():
            label = str(getattr(item, "label", "")).lower()
            text = getattr(item, "text", None)
            if "section_header" in label and text:
                headings = [*headings[-2:], text.strip()]
                continue
            if not text and "table" in label:
                try:
                    text = item.export_to_html()
                except Exception:
                    text = str(item)
            if not text or not str(text).strip():
                continue
            page = None
            prov = getattr(item, "prov", None) or []
            if prov:
                page = getattr(prov[0], "page_no", None)
            blocks.append(
                Block(
                    str(text).strip(),
                    headings.copy(),
                    page,
                    "table" if "table" in label else "text",
                )
            )
        text_tokens = sum(len(block.text.split()) for block in blocks)
        if path.suffix.lower() == ".pdf" and text_tokens < 20:
            raise UnsupportedScannedPDF(
                "This PDF appears scanned or image-only; OCR is not enabled in v1"
            )
        if not blocks:
            raise ValueError("The document contains no extractable text")
        return title, blocks
