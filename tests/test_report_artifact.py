from pathlib import Path

from pypdf import PdfReader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "实验报告.pdf"


def test_final_report_is_complete_public_artifact():
    assert REPORT_PATH.is_file()
    assert REPORT_PATH.stat().st_size > 1_000_000

    reader = PdfReader(REPORT_PATH)
    assert not reader.is_encrypted
    assert len(reader.pages) == 15

    page_text = [(page.extract_text() or "") for page in reader.pages]
    full_text = "\n".join(page_text)
    assert min(map(len, page_text)) >= 200
    assert "程序设计训练在线评测系统" in page_text[0]
    assert "DEMO_GUIDE" not in full_text
    assert "PROJECT_WALKTHROUGH" not in full_text
    assert "TODO" not in full_text

    root = reader.trailer["/Root"]
    assert "/AcroForm" not in root
    assert not ("/Names" in root and "/JavaScript" in root["/Names"])

    assert reader.metadata.title == "程序设计训练在线评测系统"
    assert reader.metadata.author == "王健成"
