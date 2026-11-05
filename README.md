# Figure Photo Grader

피규어 사진을 AI(Google Gemini 및 OpenAI GPT-6 Luna)로 평가하고, SQLite에 저장한 뒤 웹 대시보드·Excel·HTML·Lightroom XMP로 검토·선별(Culling)하는 종합 비평 및 갤러리 플랫폼입니다.

이 파일을 프로젝트의 공식 사용 설명서로 사용합니다. 시스템 아키텍처, 워크플로우 및 개발 방법론에 대한 심층 기술 문서는 **[WORKFLOW_AND_DEV_GUIDE.md](WORKFLOW_AND_DEV_GUIDE.md)**를 참조하세요.

사진 파일에서 촬영에 필요한 광학 EXIF만 안전하게 추출하고, 구조화 출력(JSON Schema)과 프롬프트 캐싱을 적용하여 구도·조명·색감·촬영 기술(각 10점 만점), 최종 종합 점수, 6대 물리 촬영 레시피 태그, 안면(눈동자) 초점 핀 상태를 정밀 비평합니다.

<p align="center">
  <img width="98%" alt="Figure Photo Grader Main Dashboard Gallery" src="https://github.com/user-attachments/assets/4c5f86a5-6453-4362-b7c0-a15110407245" />
</p>

## 개인정보 처리

GPS 위치, 촬영 시각(정밀 타임스탬프 제외), 소유자/코멘트, MakerNote, 카메라·렌즈 일련번호는 업로드 이미지와 SQLite에 포함하지 않습니다. AI로 전달하는 이미지는 새로 인코딩하며, 허용 목록의 카메라/렌즈 모델 및 조리개(F-number), 셔터(ExposureTime), ISO, 초점거리 등 촬영 설정만 EXIF에 보존합니다. 같은 안전한 설정은 API 요청의 텍스트에도 함께 전달되어 촬영 기술 평가에 활용됩니다. Interactions API 요청은 `store=False`로 생성합니다. 다만 사진 픽셀 자체는 분석을 위해 Google Gemini 또는 OpenAI API로 전송되며 각 사의 API 데이터 처리 정책이 적용됩니다.

## 설치 및 API 키 설정 (Windows PowerShell)

```powershell
cd C:\desk\figure-photo-grader\figure-photo-grader
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade -r .\requirements-photo-analyzer.txt
notepad .env
```

열리는 `.env` 파일에 발급받은 키를 입력하고 저장하세요. (OpenAI GPT-6 Luna 크로스체크 및 단독 평가를 함께 사용하려면 `OPENAI_API_KEY`도 입력합니다)

```dotenv
GEMINI_API_KEY=발급받은_Gemini_API_키
OPENAI_API_KEY=발급받은_OpenAI_API_키 (선택 사항: Luna 단독 평가 및 앙상블/크로스체크용)
```

분석기는 프로젝트의 `.env`를 읽고, 같은 이름의 Windows 환경변수가 이미 설정되어 있으면 그 값을 우선 사용합니다. `.env`는 `.gitignore`에 포함되어 저장소에 커밋되지 않으므로 키를 코드에 직접 입력하지 마세요.

## 피규어 촬영 세부 유형 및 심사 트랙 (--category)

피규어 사진 내부에서도 촬영 의도와 환경에 맞춰 공정한 평가가 이루어지도록 **4가지 세부 유형과 2대 심사 트랙**을 지원합니다.

- `auto` (기본값): 사진을 분석하여 아래 4개 유형 중 가장 적합한 것을 **자동 판별**하고 해당 전용 잣대로 심사합니다.
- `macro` (접사/디테일) → `[Track B: 통제된 전용 촬영 세팅]`: 피규어 얼굴, 눈동자 데칼, 의상 질감, 무기 조형 초근접 촬영
  - *특화 심사 기준*: 눈동자 데칼의 초정밀 칼초점, 코/귀가 날아가지 않는 적절한 매크로 심도, 미세 먼지/도색 마감 통제, 번들거리는 반사광(핫스팟) 억제
- `snap` (일상/야외 스냅) → `[Track A: 비통제 일상·야외 스냅]`: 자연광 아래 야외 출사, 여행 동행, 카페·식당 등 실제 일상 환경과 피규어의 상호작용
  - *특화 심사 기준*: 자연광(역광/측광/그늘 확산광)의 창의적 활용, 실제 환경과 피규어의 자연스러운 스케일감 조화, 계절감 및 일상적 스토리텔링, 자연스러운 여백
- `staging` (스튜디오 연출/디오라마) → `[Track B: 통제된 전용 촬영 세팅]`: 배경지, 다각도 조명 세팅, 디오라마 세트, 거울/수면 반영, 이펙트 파츠를 활용한 극적 연출
  - *특화 심사 기준*: 다각도 조명(키/필/림라이트)의 드라마틱한 입체감과 명암비, 디오라마와 피규어의 정교한 비율, 전·중·후경 3D 공간 레이어링, 역동적인 포징
- `general` (일반 피규어 촬영) → `[Track B: 통제된 전용 촬영 세팅]`: 전신/상반신 단정 스탠다드 포토
  - *특화 심사 기준*: 피규어 원형의 왜곡 없는 렌즈 화각과 프레이밍, 단정한 배경 분리, 자연스러운 피부톤 밸런스

```powershell
# 1. 자동 유형 판별 (기본값)
python .\photo_analyzer.py "sample.jpg"

# 2. 접사/디테일 전용 심사 기준으로 강제 지정
python .\photo_analyzer.py "sample.jpg" --category macro

# 3. 야외 스냅 사진 폴더 일괄 분석
python .\photo_analyzer.py ".\photos\" --category snap --workers 4
```

## 실행 모드 및 모델 티어 (Lite / Standard / 3.6 / 3.7 / Pro / Luna / Ensemble)

분석기는 피규어 및 캐릭터 모델 사진(Figure Photography)의 완성도를 전문적으로 비평하도록 최적화되어 있습니다. 작업 목적에 맞춰 다양한 AI 모델과 분석 모드를 선택할 수 있습니다.

- `--tier standard`: `gemini-3.5-flash-lite` (기본값) — 균형 잡힌 표준 화질 평가용
- `--tier lite`: `gemini-3.1-flash-lite` — 빠르고 가벼운 대량 분류 및 초고속 스크리닝용
- `--tier flash-3.6`: `gemini-3.6-flash` — 실험적 고성능 비평 모드
- `--tier flash-3.7`: `gemini-3.7-flash` — 차세대 초고속 심사 모드
- `--tier pro`: `gemini-3.8-flash` — 미세 디테일, 조명 질감, 심도 표현을 심층 분석하는 전문가급 모드
- `--tier luna`: `gpt-6-luna` — OpenAI 차세대 비평 모델 단독 엄격 심사 모드
- `--tier ensemble`: `Flash-Lite 3.5` + `GPT-6 Luna` — Gemini의 객관적 본평가에 Luna의 독립 크로스체크 비평을 덧붙이는 앙상블 모드
- `--fast` 또는 `--analysis-mode fast`: **대량 사진 경량 선별 모드 (Lightweight Culling)**
  - 6대 레시피 태그와 장문 노트를 생략하고, 5대 핵심 점수(구도·조명·색감·기술·최종) + 초점 핀 판정 + 1문장 핵심 사유만 1~2초 내로 고속 추출하여 대량의 B/C컷을 초고속으로 솎아냅니다.

```powershell
# 1. 단일 사진 표준 분석 (Standard - 기본값)
python .\photo_analyzer.py "F:\photos\sample.jpg"

# 2. 고화질 정밀 심층 비평 모드 (Pro)
python .\photo_analyzer.py "F:\photos\sample.jpg" --tier pro

# 3. OpenAI GPT-6 Luna 단독 엄격 심사 모드
python .\photo_analyzer.py "F:\photos\sample.jpg" --tier luna

# 4. Gemini + GPT-6 Luna 앙상블 크로스체크 모드
python .\photo_analyzer.py "F:\photos\sample.jpg" --tier ensemble

# 5. 대량 사진 초고속 경량 선별 모드 (Fast Mode)
python .\photo_analyzer.py "F:\photos\" --fast --workers 4

# 6. 모델명을 직접 지정할 수도 있습니다.
python .\photo_analyzer.py "F:\photos\sample.jpg" --model "gemini-3.8-flash"
```

## 폴더 일괄 분석 (Batch Mode)

단일 파일뿐만 아니라 **폴더 경로**를 지정하면 폴더 내 모든 사진을 병렬로 일괄 분석하고 비교 요약 보고서를 자동 생성합니다.

```powershell
# 폴더 내 모든 사진 일괄 분석 (워커 2개 기본)
python .\photo_analyzer.py "F:\photos\figure_set\"

# 4개 병렬 워커 + Pro 티어로 하위 폴더까지 일괄 분석
python .\photo_analyzer.py "F:\photos\figure_set\" --tier pro --workers 4 --recursive

# 경량 모드로 수백 장 초고속 일괄 선별
python .\photo_analyzer.py "F:\photos\figure_set\" --fast --workers 6

# 개별 보고서 폴더 및 비교 요약 HTML 경로 지정
python .\photo_analyzer.py "F:\photos\" `
  --report-dir "F:\reports\" `
  --summary-html "F:\reports\comparison.html"
```

일괄 분석 완료 시 터미널에 실시간 진행률과 점수 요약이 출력되며, `<폴더>/comparison.html`에 반응형 비교 표가 생성됩니다.

지원 입력 형식은 JPEG, MPO, PNG, WEBP입니다. MPO는 첫 프레임을 분석 대상으로 사용하고, 허용된 촬영 정보만 남긴 표준 JPEG로 재인코딩합니다. 너무 큰 이미지는 업로드 한도에 맞춰 리사이즈/재인코딩합니다. 표준 출력에는 파이프 처리 가능한 JSON 결과만, 저장 완료 메시지는 표준 오류에 출력합니다.

## 기존 분석 라이브러리 일괄 재평가 도구 (batch_reanalyze_all.py & 웹 모달)

이미 SQLite에 저장된 사진들을 최신 AI 모델(예: OpenAI GPT-6 Luna 또는 Gemini Flash 3.8)로 일괄 재평가하고 평가 척도를 통일할 수 있는 두 가지 경로를 제공합니다.

### 1. CLI 도구 (`batch_reanalyze_all.py`)
```powershell
# 1. 전체 라이브러리를 GPT-6 Luna 모델로 5개 워커 병렬 일괄 재평가
python .\batch_reanalyze_all.py --model luna --concurrency 5

# 2. 이전에 Flash-Lite로 평가된 사진들만 선별하여 Luna로 교체
python .\batch_reanalyze_all.py --model luna --only-flash-lite

# 3. 요청 간 대기 시간 지정 (Gemini 무료 티어 RPM 한도 조절 시)
python .\batch_reanalyze_all.py --model pro --delay 4.5 --concurrency 1
```

- `--concurrency, -c`: 병렬 워커 수를 1~50까지 지정하여 고속 재평가 수행.
- **안전한 이미지 원본 보존**: `data/photo_originals/`에 보관된 고해상도 이미지를 자동 탐색해 재분석하며, 파일이 없을 경우 기존 DB 썸네일로 안전하게 폴백합니다.

### 2. 웹 대시보드 내 "선택한 사진 AI 일괄 재평가" 모달
대시보드 상단의 `☑️ 사진 선택·컬렉션 정리` 모드에서 원하는 사진들을 체크한 뒤 `🔄 선택한 사진 일괄 재평가` 버튼을 누르면 직관적인 팝업 창이 열립니다.
- **작업 방식 선택**:
  - `⚙️ 모델 전면 재평가`: 선택한 모델로 종합 점수·세부 점수·태그를 새로 생성하여 덮어씁니다.
  - `🤝 크로스체크만 채워넣기 (경량 고속)`: 기존 주 점수는 보존하고, 상대 모델의 보조 의견만 빠르게 생성합니다. (`이미 크로스체크가 있는 사진은 건너뛰기` 스마트 스킵 지원)
- **분석 깊이**: `⚡ 경량 분석 (Fast)` vs `🔍 정밀 분석 (Full)`
- **🎯 병렬 채점 후 중앙값(Median) 채택**: 동일 사진을 3회(권장) 또는 5회 병렬 채점하여 튀는 이상치(Outlier)를 배제하고 가장 신뢰도 높은 중간값 결과를 저장합니다.
- **동시 처리 병렬 수**: 1장(극보수), 2장(기본 안정), 3장, 5장, 10장, 최대 50장(RPM 1K+ 초극속) 지원.
- 실시간 프로그레스 바(%), 남은 장수, 건별 완료 알림 스트림 제공.

## 저장 구조

- **`photo_analyses` 테이블**: 파일명, SHA-256, 표시 크기, 형식, 사용 모델, `exif_json`, `analysis_json`, `lr_advice_json`(라이트룸 추천 수치), `sns_advice_json`(SNS 크롭/캡션), `user_score`(사용자 직접 평점), `review_status`(미검토, 확인 필요, 검토 완료, 토너먼트 1위), `user_notes`(사용자 메모), `dhash`(연사 감지용 해시), `captured_at`(EXIF 촬영 일시), `is_excluded`(통계/갤러리 제외 플래그), UTC 저장 시각.
- **라이트룸 스타일 가상 컬렉션 (`photo_collections`, `photo_collection_items`)**: 폴더 트리와 무관하게 자유롭게 사진을 담고 분류할 수 있는 N:M 가상 앨범 테이블.
- **6대 물리 촬영 레시피 태그 정규화 테이블 (`photo_tag_catalog`, `photo_analysis_tags`)**: 태그 어휘 카탈로그 및 사진별 태그를 인덱싱하여 고속 필터링과 통계 연산 지원.
- **고해상도 프라이버시 클린 원본 폴더 (`photo_originals/`)**: DB 옆의 폴더에 고해상도 이미지를 보관하여 2.4배 확대 돋보기 검사 및 Canvas 무손실 SNS 크롭 다운로드 시 사용합니다. 원본 파일이 없으면 DB의 `thumbnail`로 즉시 폴백합니다.

### 6대 물리 촬영 레시피 태그 (Aesthetic Recipe Tags)
기존의 주관적·추상적 태그를 배제하고, 사진 촬영 시 물리적으로 설정·제어하는 6대 핵심 변수를 각 범주당 정확히 1개씩 단일 선택하여 엄격하게 기록합니다:
1. `shot_scale` (프레이밍 배율): `접사(페이스/디테일)`, `바스트샷(상반신)`, `풀샷(전신)`, `와이드(공간/배경 중심)`
2. `camera_angle` (카메라 앵글): `아이레벨(눈높이)`, `로우앵글(앙각)`, `하이앵글(부감)`, `더치앵글(기울임)`
3. `light_direction` (주광 방향): `순광(정면광)`, `측광(사광)`, `역광/림라이트`, `탑라이트(상단광)`, `전방위 확산광`
4. `light_quality` (빛의 성질): `소프트(부드러운 확산광)`, `하드(강한 직사광/대비)`, `컬러/네온조명`, `일상 앰비언트광`
5. `depth_of_field` (피사계 심도): `극얕은심도(배경완전흐림)`, `중간심도(배경형태인식)`, `깊은심도(팬포커스)`
6. `color_tone` (노출 및 색조): `하이키/웜톤`, `하이키/쿨톤`, `로우키/웜톤`, `로우키/쿨톤`, `뉴트럴(표준톤)`

## 점수 평가 척도 및 채점 루브릭 (Method A 스케일 스트레칭)

지나치게 후한 점수 인플레이션을 방지하고, 7~8점대에 점수가 몰리는 현상을 타파하여 사진의 객관적 완성도와 한계를 날카롭게 변별하도록 **방법 A 스케일 스트레칭(Scale Stretching)** 채점 기준을 적용합니다.

### 1. 점수 구간별 절대 기준표 (10점 만점)
- **9.5 ~ 10.0: S+컷 / 더 레전드 (한계 돌파)**
  - *진입 조건*: 4대 세부 점수(구도·조명·색감·기술) 중 최소 3개 이상이 9.3점 이상이고 전 항목 9.0점 이상이며, [5대 체크리스트 완전 무결점(Zero Defect)] 통과 필수.
  - *기준*: 기술적 무결점에 더해, 촬영자가 의도한 고유한 연출과 서사적 분위기(Scene Intent)가 100% 완결되어 피규어가 살아 숨 쉬는 캐릭터로 느껴지는 경지.
- **9.0 ~ 9.4: S컷 / 마스터피스 (프로 사진작가급)**
  - *진입 조건*: 5대 광학·구도 체크리스트에 치명적 결함이 없고, 전체적인 연출과 기술 완성도가 프로 작가 수준인 작품.
  - *기준*: 자연광/다각도 조명이 완벽히 통제되어 입체 명암비와 질감이 극대화되었거나, 전·중·후경 3D 공간 레이어링이 깊이 있게 완성된 컷. (세부점수 평균 8.8 이상 시 상방 시너지 +0.1~+0.2 반영)
- **8.3 ~ 8.9: A+컷 / 고완성도 화보 (핵심 버퍼존)**
  - 상급 수작들이 9점대 진입 장벽 앞에서 주저 없이 안착할 수 있는 고완성도 화보 구간.
  - 골든아워/역광 림라이트, 부드러운 전경 보케 액자, 피규어 스케일과 완벽히 맞물린 소품 스토리텔링으로 장난감 같은 이질감이 완전히 사라진 상급 컷.
- **7.5 ~ 8.2: A컷 / 입체감과 분위기 (수작)**
  - 깔끔한 배경 분리(보케), 부드러운 조명 각도로 플라스틱 번들거림(Hotspot)을 억제하고 얼굴과 의상에 자연스러운 입체 음영(Fall-off)을 형성한 탄탄한 수작.
- **6.5 ~ 7.4: B+컷 / 깔끔한 스탠다드 (새로운 기준 평균점)**
  - **단색 배경지 앞 눈동자 칼초점 기록 샷이나, 단순히 난간/소품 위에 올려두고 찍은 평이한 일상 스냅의 새로운 앵커(기준점: 6.8 ~ 7.2점)**.
  - 결함은 없으나 특별한 빛/공간 설계가 평이한 표준 샷은 관성적으로 8점대를 주지 않고 이 구간에 엄격히 안착시킵니다.
- **5.5 ~ 6.4: B컷 / 기초 기록 샷 (아쉬운 결함 존재)**
  - 피규어 안면 미세 핀 이탈, 형광등 직사광으로 인한 번들거림, 땡볕 얼굴 그림자, 어수선한 배경 노출 등 명확한 개선 여지가 있는 컷.
- **4.0 ~ 5.4: C컷 / 기술적 실패**
  - 심한 흔들림, 피사체 식별 불가, 세트장 밖 모니터 스탠드나 지저분한 방바닥이 노골적으로 노출되어 몰입감을 파괴한 샷.

### 2. 5대 광학·구도 체크리스트
AI는 점수를 책정하기 전 다음 5개 핵심 요소를 선행 판정합니다:
1. **안면(눈동자) 칼초점**: 아이 데칼의 선명도
2. **노출 및 계조 안정성**: 하이라이트 날림/암부 잠김 방지
3. **플라스틱 핫스팟 억제**: 번들거리는 반사광 통제
4. **배경 분리 및 몰입감**: 깔끔한 보케와 시선 집중도
5. **색온도 밸런스**: 피규어 본래 도색 피부톤 보존

### 3. 피규어 눈동자/페이스 초점 핀 정밀 판정 (`focus_status`)
- `완벽 칼초점`: 눈동자 데칼의 경계면과 반사광이 타협 없이 극도로 선명함
- `미세 앞핀`: 눈동자보다 앞쪽(앞머리 끝, 코끝, 무기)에 초점 맺힘
- `미세 뒤핀`: 눈동자보다 뒤쪽(귀, 머리 뒤편, 어깨)에 초점 맺힘
- `초점 이탈`: 피규어 얼굴 전반에 핀이 맞지 않거나 흔들림
- `판별 불가`: 극단적 심도/블러 등

### 4. 하단 워터마크/프레임 촬영 설정 자동 감지 (`detected_camera_settings`)
라이카 프레임 등 사진 하단 여백에 인쇄된 조리개, 셔터스피드, ISO, 초점거리를 OCR로 자동 감지하여 메타데이터가 손실된 WebP/SNS 사진도 광학 평가에 반영합니다.

## 오프라인 테스트

```powershell
python -m unittest discover -s tests
```

네트워크 API 호출 없이 모킹 및 로컬 엔진으로 수행되며, 프론트엔드 HTML-JS DOM 무결성, 6대 레시피 태그 스키마, 가상 컬렉션 N:M 연동, 성장 타임라인 집계, 날짜 세션 클러스터링, 통계 제외 필터, LLM 자가치유 파서 등 **122개 전체 단위 테스트**를 검증합니다.

## Excel로 분석 결과 관리

```powershell
# 기본 DB 전체 내보내기: photo_analyses.xlsx 생성
python .\photo_excel_manager.py export

# 저장 경로 직접 지정
python .\photo_excel_manager.py export --output "F:/photos/photo_analyses.xlsx"

# Excel에서 편집·저장한 뒤 SQLite로 반영 (ID 기준 안전 트랜잭션)
python .\photo_excel_manager.py import "F:/photos/photo_analyses.xlsx"

# 범주별 태그 사용 빈도 확인
python .\photo_excel_manager.py tags
```

## Culling & Review Web 대시보드

피규어 사진을 전문적으로 선별(Culling)하고, A/B 컷 1:1 비교, 연사 묶음 자동 선별, 블라인드 토너먼트, 블라인드 속도 채점, 성장 타임라인, 태그·화각 인사이트, 라이트룸 보정 수치 제안, SNS 무손실 크롭까지 원스톱으로 처리하는 반응형 웹 대시보드입니다.

<p align="center">
  <img width="85%" alt="Figure Photo Grader Detail Review Modal with Lightroom & Luna Cross-Check" src="https://github.com/user-attachments/assets/ae21b25b-eb07-4ca7-aa00-ee5d90423936" />
</p>

```powershell
python .\photo_dashboard.py
# 포트 및 바인딩 주소 지정
python .\photo_dashboard.py --host 127.0.0.1 --port 8080
```

브라우저에서 `http://localhost:8080`으로 접속하여 다음 기능들을 활용할 수 있습니다.

### 1. 사진 업로드 & 백엔드 성능 최적화
- **📁 폴더 통째로 선택 (`webkitdirectory`) & 드래그 앤 드롭**: 폴더 선택 시 하위 폴더까지 자동 탐색하며, 폴더명을 인식해 가상 컬렉션으로 자동 생성·배정.
- **⚡ Prompt & Context Caching 최적화**:
  - Gemini의 정적 비평 지침 대상 `types.CreateCachedContentConfig` 컨텍스트 캐싱 적용 (TTL 1800초).
  - OpenAI 프롬프트 캐싱을 위한 2단계 코디네이션 락(동일 사진 병렬 샘플링 시 콜드 캐시 스탬피드 방지) 적용.
  - 최대 50 병렬 동시성 세마포어로 API 호출 처리량 극대화.
- **🪟 Windows 파일 잠금 방지 인메모리 바이트 파이프라인**: 디스크 임시 파일 없이 메모리 상에서 이미지를 정제/인코딩하여 `[WinError 32]` 파일 핸들 잠금 오류 원천 차단.
- **⚡ SQLite WAL 모드 & 비지 타임아웃 (`busy_timeout=30000`)**: 멀티스레드 동시 읽기/쓰기 락을 완전 해소하고 썸네일 BLOB 쿼리 분리로 I/O 90% 이상 절감.
- **🛡️ LLM 자가치유 파서 (Self-Healing Parser)**: 토큰 분할 오탈자나 비정형 응답 발생 시 표준 상수로 자동 복구하고 점수 범위를 0~10으로 안전 클램핑.

### 2. 2단 슬림 툴바 & 라이브러리 스코프 제어
- **2열 슬림 상단바**: 컬렉션 칩, 날짜 필터 토글, 뷰 모드 탭, 슬림 점수 히스토그램을 컴팩트하게 배치.
- **🗂️ 라이트룸 스타일 가상 컬렉션 (Virtual Collections)**:
  - `+ 새 컬렉션` 생성, 이름변경, 삭제 지원.
  - `☑️ 사진 선택·컬렉션 정리` 모드로 여러 사진을 체크하여 특정 컬렉션에 한 번에 담거나 제외.
  - 컬렉션 칩 클릭 시 해당 컬렉션의 사진만 갤러리·통계·타임라인에 즉시 필터링.
- **📅 촬영 세션(Session) 칩 & 날짜 범위 필터 (Collapsible Drawer)**:
  - EXIF 촬영 일시를 기반으로 2시간 이내 연속 촬영분을 하나의 '출사 세션'으로 자동 묶어 원클릭 칩으로 제공.
  - 날짜 범위(From ~ To) 선택 시 대시보드 전역 스코프가 실시간 동기화.
- **🚫 사진 통계/갤러리 제외 필터 (`is_excluded`)**:
  - 카드 우측 메뉴나 상세 모달에서 `🚫 통계에서 제외` 토글 가능.
  - 프롬프트 테스트용 사진이나 불필요한 컷을 DB에서 삭제하지 않고도 인사이트 통계와 타임라인 곡선에서 안전하게 격리.
- **🌙 다크룸(Darkroom) 테마**: 야간 감상 및 색상 보정에 최적화된 저자극 암실 테마 원클릭 토글.

### 3. 선별(Culling) & 뷰 모드
- **⚡ 프로그레시브 청크 렌더링**: 40장 단위 점진적 렌더링 + `IntersectionObserver` 무한 스크롤로 수천 장 컬렉션에서도 60fps 부드러운 스크롤 유지.
- **👑 연사 자동 선별 및 B컷 판별 (B-1 Burst Grouping)**:
  - 64비트 dHash 지각적 해시, 파일명 시퀀스, EXIF 촬영 시각 하이브리드 군집화.
  - 연사 묶음 내 최고점수 컷을 `👑 Best Pick (1위)`으로 자동 선발하고 B컷에는 구체적 탈락 사유 표기.
- **1:1 Culling 비교 뷰**: 사진 A와 B를 나란히 놓고 점수 차이, 5대 세부 점수, 장단점 노트를 대조.
- **🏆 블라인드 토너먼트 선별 (B-3 Blind Culling)**: 점수 편견 없이 시각적 느낌만으로 1:1 토너먼트를 거쳐 나만의 최애 A컷 선발.
- **🎯 블라인드 내 점수 매기기 (Blind Rating Subsystem - Option A)**:
  - AI 점수를 가린 채 사진을 무작위로 제시받아 나만의 점수(0.0~10.0)를 직관적으로 입력.
  - 키보드 숫자 단축키 지원, 채점 직후 **AI 점수와의 차이 갭 분석 피드백** 즉각 노출.
  - 세션 완료 시 유저 vs AI 평균 점수, 상관관계, 가장 의견이 일치/불일치한 대표 사진 리포트 제공.
- **📈 사진 점수 성장 타임라인 (Score Growth Timeline View)**:
  - 상단 탭에서 `📈 성장 타임라인`으로 전환.
  - **5대 다중 스케일 그룹핑**: 출사 세션별, 주간별, 월간별, 분기별, 누적 마일리지별 점수 추이 집계.
  - **다중 지표 오버레이**: AI 종합 평균, 상위 25% A컷 풀(Top-25%), 최고점(Peak), 유저 직접 평점 평균, 4대 세부영역(구도·조명·색감·기술) 개별 곡선 선택 지원.
  - 반응형 SVG 차트 위 포인트 호버 시 사진 썸네일과 점수 툴팁 실시간 인터랙션.
- **2.4배 안면/눈동자 확대 돋보기 (Zoom Pan)**: 상세 모달에서 사진 클릭 시 마우스 커서를 따라 2.4배 정밀 확대되어 눈동자 데칼 초점 핀과 마감을 즉시 검증.

### 4. 🏷️ 6대 레시피 태그 & 🔭 화각 인사이트 (Analytics & Trends)
- **태그 및 화각 기반 다중 검색 & 필터링**:
  - AND(모두 포함) vs OR(하나라도 포함) 논리 연산 토글.
  - 6대 물리 촬영 레시피 태그 드롭다운 필터 및 인기 퀵 태그 버튼.
  - **🔭 5대 화각(초점거리) 원클릭 필터 바**: 24mm 이하 (광각), 35mm (준광각), 50mm (표준), 70~85mm (준망원), 100mm+ (망원/매크로), 화각 미식별 필터.
- **📊 독립 탭 — 태그 및 화각 인사이트**:
  - **🔭 화각대별 렌즈 성능 분석**: 5대 표준 화각대별 종합 성적표, 빈출 칭찬/약점 테마 Top 3 클러스터링 및 실제 AI 심사평 인용, 단일 mm 단위 정밀 랭킹.
  - **🏷️ 시각 레시피 태그별 미학 분석**: 최소 사진 수 필터, AI 점수 vs 내 점수 비교, 6대 카테고리별 스타일 경향성 비교 그리드.
  - 로컬 SQLite 인덱스 및 클라이언트 캐시 연산으로 **추가 API 호출 0회 (무료 & 즉시 렌더링)**.

### 5. 멀티 모델(Multi-LLM) & 양방향 크로스체크, 보정 슬라이더, SNS 크롭
- **⚙️ 작업별 AI 모델 설정 모달 (`ModelSettings`)**:
  - 사진 평가, 라이트룸 보정, SNS 크롭, SNS 캡션 각각의 기본 모델을 독립 지정하거나 4대 프리셋(`가성비`, `표준`, `Luna 풀패키지`, `최고 화질 Pro`)으로 일괄 적용.
  - 브라우저 `localStorage`에 영구 저장.
- **🤝 양방향 LLM 크로스체크 (Gemini ↔ OpenAI GPT-6 Luna)**:
  - 주 평가 모델이 Gemini이면 Luna가, OpenAI이면 Gemini가 신속히 상대 모델의 관점에서 보조 비평을 수행.
  - 상세 모달 내 독립된 크로스체크 카드에 총점, 4대 서브점수 스트립(`구도 8.5 / 조명 8.0`), 장단점 및 심사평을 병렬 노출.
- **Adobe Lightroom 추천 보정 슬라이더 수치 제안**:
  - 노출(EV), 대비, 하이라이트(번들거림 억제), 섀도우(암부 복원), 텍스처, 화이트밸런스 및 피규어 맞춤 리터칭 팁을 JSON으로 제안하고 영구 캐싱.
- **소셜 미디어(Instagram · X) 4대 규격 맞춤 크롭 & 👑 AI Best Pick**:
  - 단 1회 호출로 인스타그램(`4:5`, `1:1`), X(`16:9`, `3:4`), `원문 유지(No Crop)` 제안을 일괄 생성.
  - 모달에서 비율 클릭 시 원본 위에 **실시간 3분할 가이드 그리드 오버레이**.
  - 브라우저 Canvas 기반 **`[✂️ 이 비율로 잘라 다운로드]`** 및 **`[📥 원본 고해상도 다운로드]`** 무손실 저장 지원.
  - 피규어 특화 감성 캡션 및 다국어 해시태그 원클릭 복사.
- **📊 종합 API 사용량 모니터링**:
  - 모델별 호출 수, 실패율, 입력/출력 토큰, 캐시 적중 토큰(Gemini Context Cache / OpenAI Prompt Cache), 평균 응답시간 집계.
  - 날짜 범위(Date Range) 필터 및 대시보드 스코프 동기화 지원.
- **📥 Lightroom / Capture One XMP 원클릭 내보내기**:
  - 상단 버튼 클릭 시 원본 사진 옆에 Adobe 표준 `.xmp` 사이드카 파일 자동 생성 (별점 1~5성 및 컬러 라벨 동기화).

## Lightroom / Capture One XMP 사이드카 연동 (`--xmp`)

```powershell
# 단일 사진 분석 시 XMP 동시 생성
python .\photo_analyzer.py .\test_photo\fig1.webp --xmp

# 폴더 일괄 분석 시 전체 XMP 자동 생성
python .\photo_analyzer.py .\test_photo --xmp
```

- **별점(Rating) 매핑**:
  - 9.0 ~ 10.0: ★★★★★ (5성, Purple)
  - 8.3 ~ 8.9: ★★★★☆ (4성, Blue)
  - 7.5 ~ 8.2: ★★★☆☆ (3성, Green)
  - 5.5 ~ 7.4: ★★☆☆☆ (2성, Yellow)
  - 5.5 미만: ★☆☆☆☆ (1성, Red)

## HTML 분석 결과 화면

```powershell
python .\photo_analyzer.py "F:/photos/sample.jpg" --html "F:/reports/photo_analysis_report.html"
```

생성된 `.html` 파일은 이미지 미리보기와 스타일을 자체 내장하므로 인터넷 연결 없이 단독으로 브라우저에서 열람할 수 있습니다.
