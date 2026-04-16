"""FastAPI app에서 OpenAPI 스키마를 추출해 JSON 파일로 저장한다.

사용법:
  cd server
  uv run python scripts/gen_openapi.py

출력: dashboard/src/openapi.json
"""
import sys
import json
from pathlib import Path

# server 디렉토리를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from main import app
    schema = app.openapi()
    out_path = Path(__file__).parent.parent.parent / 'dashboard' / 'src' / 'openapi.json'
    out_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False))
    print(f'[gen_openapi] 저장 완료: {out_path}')
    print(f'  - 경로 수: {len(schema.get("paths", {}))}')
    print(f'  - 스키마 수: {len(schema.get("components", {}).get("schemas", {}))}')
except Exception as e:
    print(f'[gen_openapi] 실패: {e}', file=sys.stderr)
    sys.exit(1)
