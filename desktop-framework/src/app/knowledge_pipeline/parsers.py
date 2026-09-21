"""Read-only parsing with explicit coverage and bounded resource use."""
from __future__ import annotations
import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree
from .contracts import MAX_TEXT, sha

SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".csv", ".json", ".bdf", ".nas", ".dat"}
MAX_BYTES = 20 * 1024 * 1024


def parse(raw: bytes, name: str) -> dict:
    suffix = Path(name).suffix.lower()
    if suffix not in SUFFIXES:
        raise ValueError("不支持的格式；旧版 .doc 请先转成 .docx")
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("单文件必须为非空且不超过 20 MiB")
    warnings, pages = [], []
    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise ValueError("加密 PDF 尚不支持")
        if len(reader.pages) > 2000:
            raise ValueError("PDF 超过 2000 页；请分册处理")
        for index, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            pages.append((index, text, "pdf_page_text"))
            if not text.strip():
                warnings.append(f"第 {index} 页没有可提取文本；未进行 OCR")
            if sum(len(p[1]) for p in pages) > MAX_TEXT:
                raise ValueError("正文超过当前单文件处理上限；未截断入库")
    elif suffix == ".docx":
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 4000 or sum(x.file_size for x in entries) > 40 * 1024 * 1024:
                raise ValueError("DOCX 解压规模超过限制")
            data = archive.read("word/document.xml")
        if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
            raise ValueError("拒绝包含 DTD 或实体声明的 XML")
        root = ElementTree.fromstring(data)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        text = "\n".join("".join(p.itertext()) for p in root.findall(".//w:p", ns))
        pages = [(0, text, "docx_body_text")]
        warnings.append("DOCX 位置为正文字符偏移，不伪造页码；页眉、批注、图片未解析")
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("gb18030")
            warnings.append("采用 GB18030 解码，请核对文字")
        if "\x00" in text:
            raise ValueError("文本中存在 NUL，疑似二进制资料")
        if suffix in {".bdf", ".nas", ".dat"}:
            if re.search(r"^\s*INCLUDE\b", text, re.MULTILINE | re.IGNORECASE):
                raise ValueError("BDF 含 INCLUDE；必须先在受管目录解析依赖，不读取任意本地路径")
            warnings.append("本入口保留 BDF 原文和候选信息；不解析子工况激活、坐标变换、组合载荷或单位制，不可作为求解器输入验收")
        pages = [(0, text, "decoded_text")]
    if sum(len(p[1]) for p in pages) > MAX_TEXT:
        raise ValueError("正文超过 1,000,000 字符；未静默截断")
    if not any(t.strip() for _, t, _ in pages):
        raise ValueError("没有可解析正文；扫描件需要单独 OCR 流程")
    segments = []
    for page, text, locator in pages:
        # Non-overlapping windows preserve complete coverage and exact offsets.
        for start in range(0, len(text), 4000):
            part = text[start:start + 4000]
            if part.strip():
                segments.append({"page": page, "start": start, "end": start + len(part),
                                 "text": part, "text_hash": sha(part), "locator": locator})
    return {"segments": segments, "pages": len(pages),
            "text_pages": sum(bool(t.strip()) for _, t, _ in pages),
            "warnings": warnings, "parser": "zhiheng-readonly/1",
            "coverage": "text_extracted" if not warnings else "text_with_limitations"}
