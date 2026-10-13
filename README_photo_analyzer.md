# 사진 EXIF + Gemini 평가기

사진 파일에서 촬영에 필요한 EXIF만 추출하고, Gemini의 구조화 출력(JSON Schema)을 사용해 구도·조명·색감·촬영 기술·최종 점수(각 10점 만점)와 범주별 미학 태그를 평가한 뒤 SQLite에 저장하는 단일 이미지 CLI입니다.

## 개인정보 처리

GPS 위치, 촬영 시각, 소유자/코멘트, MakerNote, 카메라·렌즈 일련번호는 업로드 이미지와 SQLite에 포함하지 않습니다. Gemini로 보내는 이미지는 새로 인코딩하며, 허용 목록의 카메라/렌즈 모델 및 조리개(F-number), 셔터(ExposureTime), ISO, 초점거리 등 촬영 설정만 EXIF에 다시 넣습니다. 같은 안전한 설정은 API 요청의 텍스트에도 함께 전달되어 촬영 기술 평가에 활용됩니다. Interactions API 요청은 `store=False`로 생성합니다. 다만 사진 픽셀 자체는 분석을 위해 Google Gemini API로 전송되며 Google의 API 데이터 처리 정책이 적용됩니다.

## 설치 및 API 키 설정 (Windows PowerShell)

```powershell
cd F:\desk\teamproject
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade -r .\requirements-photo-analyzer.txt
notepad .env
```

열리는 `.env` 파일에 발급받은 키를 입력하고 저장하세요.

```dotenv
GEMINI_API_KEY=발급받은_Gemini_API_키
```

분석기는 프로젝트의 `.env`를 읽고, 같은 이름의 Windows 환경변수가 이미 설정되어 있으면 그 값을 우선 사용합니다. `.env`는 `.gitignore`에 포함되어 저장소에 커밋되지 않으므로 키를 코드에 직접 입력하지 마세요.

## 실행

```powershell
python .\photo_analyzer.py "F:\photos\sample.jpg"
```

기본 DB는 저장소의 `photo_analysis.sqlite3`, 기본 모델은 `gemini-3.1-flash-lite`입니다. 다른 경로나 모델은 명령줄 옵션으로 바꿀 수 있습니다.

```powershell
python .\photo_analyzer.py "F:\photos\sample.jpg" `
  --db "F:\data\photo_reviews.sqlite3" `
  --model "gemini-3.1-flash-lite"
```

지원 입력 형식은 JPEG, MPO, PNG, WEBP입니다. MPO는 첫 프레임을 분석 대상으로 사용하고, 허용된 촬영 정보만 남긴 표준 JPEG로 재인코딩합니다. 너무 큰 이미지는 업로드 한도에 맞춰 리사이즈/재인코딩합니다. 표준 출력에는 파이프 처리 가능한 JSON 결과만, 저장 완료 메시지는 표준 오류에 출력합니다.

## 저장 구조

`photo_analyses` 테이블에 파일명, SHA-256, 표시 방향 기준 크기, 형식, 모델, 개인정보를 제외한 `exif_json`, 검증된 `analysis_json`, UTC 저장 시각을 저장합니다. 미학 태그는 `analysis_json.aesthetic_tags`에도 포함되며, 집계·검색을 위해 허용 어휘를 `photo_tag_catalog`, 사진별 태그를 `photo_analysis_tags`에 정규화해 저장합니다. 같은 사진을 다시 분석하면 새 행이 추가됩니다.

태그 범주는 시점, 구도·공간, 포즈·시선, 분위기, 피사체-배경 관계, 빛 표현, 색조 인상, 이야기 암시의 8가지입니다. 시점 어휘에는 정면·측면·후면·사선과 로우/하이 앵글 등이 포함됩니다. 각 범주는 이미지에서 확인되는 태그만 최대 3개 기록하며, 해당되지 않거나 근거가 부족하면 빈 배열로 둡니다.

## 오프라인 테스트

```powershell
python -m unittest -v
```

테스트는 Gemini API 네트워크를 호출하지 않으며, EXIF 허용 목록과 민감 정보 제외, 촬영 설정의 업로드·프롬프트 전달, 점수·태그 검증 및 정규화 SQLite 저장을 확인합니다.

## Excel로 분석 결과 관리

기존 사진 분석 명령과 SQLite 저장 흐름은 그대로 사용할 수 있습니다. pandas와 openpyxl로 분석 기록을 보기 좋은 `.xlsx` 파일로 내보내고, Excel에서 수정한 평가와 태그를 ID 기준으로 기존 DB에 반영할 수 있습니다. 기존 워크북에 태그 열이 없으면 빈 태그로 처리해 가져올 수 있습니다.

```powershell
# 기본 DB 전체 내보내기: 프로젝트 폴더에 photo_analyses.xlsx 생성
python .\photo_excel_manager.py export

# 저장 경로를 직접 지정할 수도 있습니다.
python .\photo_excel_manager.py export --output "F:/photos/photo_analyses.xlsx"

# Excel에서 편집·저장한 뒤 SQLite로 반영
python .\photo_excel_manager.py import "F:/photos/photo_analyses.xlsx"

# 다른 SQLite DB 사용
python .\photo_excel_manager.py export --db "F:/data/photo_reviews.sqlite3" --output "F:/data/photo_analyses.xlsx"
python .\photo_excel_manager.py import "F:/data/photo_analyses.xlsx" --db "F:/data/photo_reviews.sqlite3"

# 범주별 태그 사용 빈도 확인
python .\photo_excel_manager.py tags
```

워크북에는 분석 기록 표와 사용 안내 시트가 들어갑니다. 점수(0~10), 평가 메모, 최종 평가, 강점·개선점, 8개 범주의 태그, 검토 상태, 사용자 메모를 수정할 수 있습니다. 태그는 범주별 셀에서 줄바꿈으로 나누고, 안내 시트에 기재된 허용 어휘 중 범주당 최대 3개를 입력합니다. 검토 상태에는 `미검토`, `확인 필요`, `검토 완료` 목록이 제공됩니다. ID와 파일 정보는 표시용이며, 가져올 때는 DB의 해당 정보를 덮어쓰지 않습니다.

Excel 내보내기는 DB를 읽기 전용으로 열어 스키마나 데이터를 수정하지 않습니다. 가져오기는 기존 ID의 분석 내용·태그·검토 상태·사용자 메모만 갱신합니다. 새 행을 DB에 추가하거나 DB 행을 삭제하지 않으며, ID 중복·미등록 ID·필수 열 누락·잘못된 점수·허용되지 않은 태그·잘못된 검토 상태가 하나라도 있으면 전체 반영을 취소합니다. SQLite 트랜잭션으로 반영하므로 검증에 실패해 일부 행만 바뀌지 않습니다. 처음 가져오면 검토 필드와 태그 카탈로그·사진별 태그 테이블이 추가될 수 있으며, 기존 분석 기록은 유지됩니다. 기존 기록의 태그는 과거 분석 응답에 없으므로 자동 추정하지 않습니다. 사진을 다시 분석하거나 Excel에서 입력할 수 있습니다.

기본 출력 파일 `photo_analyses.xlsx`는 Git에서 제외됩니다. 직접 경로를 지정해 만든 다른 Excel 파일에는 파일명과 분석 내용 및 허용된 촬영 설정이 포함될 수 있으니 안전하게 보관하세요.

## HTML 분석 결과 화면

분석 점수와 해설을 브라우저에서 확인하고 싶다면 분석 명령에 `--html` 경로를 추가합니다. 평소처럼 JSON은 표준 출력으로 반환되고 SQLite에도 저장되며, 별도로 단독 실행할 수 있는 HTML 보고서가 생성됩니다. 보고서에는 최종 점수, 구도·조명·색감·촬영 기술 점수, 해설, 강점·개선점, 범주별 미학 태그 및 분석용 이미지 미리보기가 들어갑니다.

```powershell
python .\photo_analyzer.py "F:/photos/sample.jpg" --html "F:/reports/photo_analysis_report.html"
```

생성된 `.html` 파일을 Edge나 다른 브라우저에서 열면 됩니다. 보고서는 이미지 미리보기와 스타일을 안에 포함하므로 오프라인에서도 열 수 있습니다. 보고서에 이미지와 평가 내용이 포함될 수 있으니 공유·보관에 유의하세요.

**이 프로젝트에는 단독 HTML 보고서가 가장 간단한 선택**입니다. 별도 웹 프레임워크 없이 결과를 보여주고 보관·인쇄할 수 있습니다. 나중에 브라우저 화면에서 파일 선택·업로드와 기록 탐색까지 직접 하려면 Streamlit(또는 Gradio) 앱이 더 적합하지만, 로컬 웹 서버를 띄우는 구성과 추가 의존성이 필요합니다. Excel은 여러 건의 점수·메모를 표로 편집할 때, JSON은 다른 프로그램과 연동할 때 유용합니다.
