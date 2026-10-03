# Activity Atlas

[Live dashboard](https://snuconnectome.github.io/activity-atlas/) · [Build](https://github.com/snuconnectome/activity-atlas/actions/workflows/build.yml)

GitHub 활동을 Overview·Latent·Lifecycle·Network·Pulse·Drift·1:1·About의 8개 화면으로 살펴보는 정적 대시보드입니다. 기본 수집은 PI 계정이며 커밋은 시간·예산·성과·면담의 측정값이 아닙니다.

## Why this exists

<!-- DRAFT by Claude — please refine in your own voice. Original TODO(human) guidance:
     What pattern in your work do you most want to see? What would change if you
     noticed it 6 months earlier? Who else (lab members, collaborators, your
     future self) might benefit from seeing this? -->

세 개 organization에 흩어진 지난 12개월의 commit을 돌아보면,
무엇이 어디로 흘러갔는지 내 머릿속에서도 이미 흐릿해진다.
제안서 마감 burst, 논문 review cycle, 강의 자료, 학생 협업 —
이 흐름들이 어떤 주제로 묶이는지, 어느 주에 무게중심이 어디 있었는지를
정량으로, 그리고 시각적으로 보고 싶다.

작년 가을에 이 그림이 있었다면 핵심 thread에 더 일찍 집중했을 것이고,
마감 직전 burst를 한두 주 평탄화했을 것이다.
이 atlas는 일차적으로 미래의 내가 자기 시간 배분을 정직하게 들여다보기 위한
거울이고, 부차적으로는 협력자들이 "지금 어디에 무게가 실려 있는지"를
빠르게 읽도록 돕는 도구다.


## Start here

공개 JSON은 이미 저장소에 들어 있으므로 원본·GitHub 토큰·ML 환경 없이 렌더할 수 있습니다.

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
quarto render
python3 scripts/check_public.py --site _site
```

실제 브라우저 검증은 두 터미널에서 실행합니다.

```bash
python3 -m http.server 9000 --bind 127.0.0.1 --directory _site
```

```bash
python3 -m playwright install chromium
AA_TEST_URL=http://127.0.0.1:9000 python3 -m unittest discover -s tests -p test_browser_safety.py -v
```

ARM64 DGX에서는 설치된 Chromium 경로를 `AA_CHROMIUM`으로 지정할 수 있습니다. 브라우저 테스트는 URL이 없으면 명시적으로 건너뜁니다. CI는 URL을 지정해 실행합니다.

## Data and interpretation

| 화면 | 내용 | 해석 범위 |
|---|---|---|
| Overview | 캘린더·계획 배분과 활동 비중·도메인 | 커밋 비중은 노동·예산·성과가 아님 |
| Latent | 메시지 임베딩의 UMAP·토픽 | 공개 가능한 점만 표시; 좌표 표본과 전체 활동은 다름 |
| Lifecycle | 관측 기여자·경과일·점검 후보 | PI 수집에서는 승계 위험을 판정하지 않음 |
| Network | 도메인 그래프·조직→토픽 | 산점도 표본과 독립된 전체 집계 사용 |
| Pulse | 연속 ISO 주별 수치와 전주 차이 | 0건인 주 포함; 공개 문장은 승인된 라벨로 재구성 |
| Drift | 공개 저장소 분류 점검 | 이름 패턴은 분류 제안; 사람의 확인 필요 |
| 1:1 | 내부 전용 계정 카드 | 공유 repo PI commit 기록은 면담·검토 증거가 아님 |
| About | 방법과 제한 | 수집 시각과 재렌더 시각을 구분 |

수집은 접근 가능한 세 조직의 최근 365일 내 갱신된 비아카이브 저장소의 기본 브랜치에서 수행합니다. GitHub 계정과 연결되지 않은 커밋 및 봇 계정은 제외합니다. `pi`는 PI 별칭을 통합하고 `all`은 연결된 저자 계정을 수집합니다. 저장소 밖 활동과 접근 불가능한 저장소는 관측하지 않습니다.

## Refresh locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export ACTIVITY_ATLAS_SCOPE=pi
.venv/bin/python scripts/fetch_commits.py --full
.venv/bin/python scripts/topic_model.py
.venv/bin/python scripts/weekly_pulse.py
.venv/bin/python scripts/join.py --profile pub
quarto render
python3 scripts/check_public.py --site _site
```

`gh` 인증은 로컬 수집에만 필요합니다. 원본과 모델 파생물은 `$ACTIVITY_ATLAS_DATA_DIR/scopes/<pi|all>/{raw,derived}`에 있습니다. 기본 루트는 `~/.local/share/activity-atlas`입니다. 범위를 바꾸려면 모든 단계에 같은 `ACTIVITY_ATLAS_SCOPE`를 설정합니다. `--all-authors`는 수집 범위를 `all`로 선택하며 이후 분석 단계에도 `ACTIVITY_ATLAS_SCOPE=all`이 필요합니다.

`--full`은 해당 범위를 새로 만들고, 증분 수집도 기간 밖·다른 저자 범위의 기존 행을 제거합니다. 저장소별 커서와 모델 레지스트리는 범위마다 분리됩니다. 이벤트 ID는 `org/repo@sha`이므로 같은 SHA의 다른 저장소 관계를 보존합니다.

CI의 월요일 08:00 UTC 일정은 **수집 없이 검증·재렌더·배포**만 수행합니다. Overview의 수집 시각은 실제 데이터 최신성이고 Pages 빌드 시각과 다릅니다. 로컬 검증 이후 공개 변경 파일을 검토하고 별도로 커밋·푸시합니다.

## Publication contract

| 계층 | 위치 | 정책 |
|---|---|---|
| 원본·모델 | 로컬 `scopes/<scope>/` | 본문·저자·원본 fingerprint 비공개 |
| 비공개 taxonomy | 로컬 `taxonomy/repos.json` | `seed_taxonomy.py`는 이 파일에 씀 |
| 공개 | `data/pub/` | PUBLIC 저장소만 이름·링크·좌표; private/unknown은 일별 그룹 합계 |
| 내부 | `data/lab/`, `_site-lab/` | Git 제외; 저자·본문 포함; 배포 금지 |

공개 본문은 공개 저장소이면서 동의한 저자에게만 허용합니다. 동의 파일이 없으면 허용하지 않습니다. 토픽에 제한된 출처가 하나라도 섞이면 라벨과 단어를 중립화합니다. Pulse는 원본 자유 문장을 복사하지 않습니다. 공개 정책 예외나 저장소 제외는 현재 자동 승인하지 않습니다.

join은 완료된 수집 manifest·입력 fingerprint·파생물 해시·이벤트 참조를 검증한 뒤 전체 출력 세대를 교체합니다. 누락·혼합된 분석은 기존 출력을 보존합니다. Linux `renameat2`가 없는 플랫폼에서는 기존 세대 교체가 실패하며 별도 지원이 필요합니다. 공개 manifest는 수집 범위·기간·시각과 공개 파일 digest를 담고 원본 fingerprint는 담지 않습니다.

```bash
ACTIVITY_ATLAS_SCOPE=all .venv/bin/python scripts/join.py --profile lab
QUARTO_PROFILE=lab quarto preview
```

기존 공개 Git 히스토리와 이미 배포된 과거 파일은 현재 파일 수정만으로 제거되지 않습니다. 히스토리 재작성 및 실제 Pages 배포는 별도 작업입니다.

## Maintainer map

- `scripts/aa_paths.py`: 범위·저장 경로
- `scripts/fetch_commits.py`: 수집과 원본 세대 교체
- `scripts/topic_model.py`, `weekly_pulse.py`: 분석과 파생물 해시
- `scripts/join.py`: 분류·공개 정책·페이지별 JSON
- `scripts/snapshot_contract.py`, `time_axis.py`: fingerprint·세대 교체·ISO 주
- `scripts/check_public.py`: 전체 배포 산출물 검사
- `data/schema.json`, `tests/`: 데이터·보호·시간축·브라우저 회귀 계약
- `CLAUDE.md`: 에이전트 온보딩
- `docs/reviews/2026-10-03/`: 적대적 리뷰와 수정 근거

로컬 working-memory 동반 기능은 별도 실험입니다. 사용자 소유 `scripts/workmem.py`와 `docs/working-memory.md`는 이번 대시보드 수정과 별도 범위로 유지합니다.

MIT — [LICENSE](LICENSE).
