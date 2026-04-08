# HTML → PDF 변환기 (weasyprint 기반)
from __future__ import annotations
from pathlib import Path


def html_to_pdf(html_path: str | Path, pdf_path: str | Path | None = None) -> Path:
  '''HTML 파일을 PDF로 변환한다.

  Args:
    html_path: 원본 HTML 파일 경로
    pdf_path: 출력 PDF 경로 (None이면 html_path의 확장자만 .pdf로 변경)

  Returns:
    생성된 PDF 파일 경로
  '''
  import weasyprint

  html_path = Path(html_path)
  if pdf_path is None:
    pdf_path = html_path.with_suffix('.pdf')
  else:
    pdf_path = Path(pdf_path)

  pdf_path.parent.mkdir(parents=True, exist_ok=True)
  weasyprint.HTML(filename=str(html_path)).write_pdf(str(pdf_path))
  return pdf_path
