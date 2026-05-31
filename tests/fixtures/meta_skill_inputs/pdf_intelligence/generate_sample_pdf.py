from __future__ import annotations

from pathlib import Path


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(lines: list[str]) -> bytes:
    content_lines = ["BT", "/F1 11 Tf", "72 740 Td"]
    first = True
    for line in lines:
        if not first:
            content_lines.append("0 -18 Td")
        first = False
        content_lines.append(f"({_pdf_escape(line)}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("ascii")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        + stream
        + b"\nendstream",
    ]

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


def main() -> None:
    target = Path(__file__).with_name("router-evaluation-summary.pdf")
    lines = [
        "OpenSquilla Router Evaluation Summary",
        "Page 1 evidence fixture for meta-pdf-intelligence.",
        "Key finding: cost-aware routing reduced estimated spend by 31 percent.",
        "Key finding: fallback accuracy stayed above the acceptance threshold.",
        "Risk: latency increased when source documents required deep extraction.",
        "Recommendation: cite direct evidence and separate inference from facts.",
    ]
    target.write_bytes(build_pdf(lines))
    print(target)


if __name__ == "__main__":
    main()
