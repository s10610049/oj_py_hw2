from pypdf import PdfReader

from report import generate_report


def test_report_font_fallback_preserves_chinese_without_windows_fonts(tmp_path, monkeypatch):
    monkeypatch.setenv("WINDIR", str(tmp_path / "missing-windows"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "missing-local"))
    reportlab = generate_report._load_reportlab()

    fonts = generate_report._register_fonts(
        reportlab["pdfmetrics"],
        reportlab["TTFont"],
        reportlab["UnicodeCIDFont"],
    )

    assert fonts == {
        "body": "STSong-Light",
        "bold": "STSong-Light",
        "mono": "STSong-Light",
        "mono_bold": "STSong-Light",
    }

    output = tmp_path / "cjk-fallback.pdf"
    from reportlab.pdfgen import canvas

    document = canvas.Canvas(str(output))
    document.setFont(fonts["body"], 12)
    document.drawString(40, 800, "中文报告可复现")
    document.save()

    assert "中文报告可复现" in (PdfReader(output).pages[0].extract_text() or "")
