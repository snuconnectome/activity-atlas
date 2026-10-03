# Activity Atlas — TDD 구현과 작업계획

2026-10-03, Asia/Seoul. 장르: 기술 구현·검증 보고서. 작업 저장소: `/home/juke/git/activity-atlas`. 기반 main: `c024eed53626877bf60dbbc6f2c45efb5ba9205b`. 이번 결과는 로컬 구현·검증이며 원격 푸시와 Pages 배포를 포함하지 않는다.

## 결과

적대적 리뷰의 F01–F12를 대상으로 공개 보호, 수집·분석 무결성, 지표·시간축, 테스트·문서를 보강했다. 실패하는 합성 회귀 테스트를 먼저 만든 뒤 해당 구현을 수정했다. 공개 활동 합계 4,484건을 보존하면서 private/unknown 저장소의 이름·SHA·본문·정확한 시각·좌표를 공개 출력에서 제거했다. 원래 taxonomy 바이트는 로컬 비공개 경로에 그대로 보존했다.

## 작업계획과 현재 상태

| 순서 | 대상 | 구현과 검증 | 상태 |
|---|---|---|---|
| P0 | 공개 데이터 보호, F01–F02 | PUBLIC만 이름·링크·좌표; 나머지는 일별 집계. 제한된 출처가 하나라도 있는 토픽은 중립화. Pulse 공개 문장을 새로 구성. 원본·파생물 필드 allowlist. 동의 철회·혼합 동의 테스트 | 로컬 완료 |
| P1 | HTML 삽입, F03 | DOM textContent 또는 데이터 escape, 색상·수치 검증. Pulse·Latent·People·Lifecycle·Drift의 실제 브라우저 공격 문자열 테스트 | 검증 범위 통과 |
| P1 | 수집 무결성, F04–F05 | pi/all의 raw·derived·커서 분리. full 교체. 기간 밖 이벤트 제거. org/repo@sha 이벤트 ID. 수집 실패·잘못된 응답 시 이전 세대 보존 | 로컬 완료 |
| P1 | 분석 일치·최신성, F06·F08 | 원본 fingerprint, 분석 해시, 수집 완료 manifest, 이벤트 참조 검증. 누락·변조·같은 행 수의 다른 입력 거부. 수집 기간·시각 UI 표시 | 로컬 완료 |
| P1 | 지표 해석, F07·F09 | 활동 비중과 시간·예산 구분. PI 범위 승계 판정 비활성화. 1:1은 공유 repo PI commit 기록으로 명시, 참여 이전 PI commit 제외 | 로컬 완료 |
| P2 | 시간축·표본, F10–F11 | ISO week-year, 0건인 주 포함, 최근 8주 연속 sparkline, 0일 정렬, Network 전체 집계와 좌표 표본 분리 | 로컬 완료 |
| P2 | 유지보수, F12 | JSON 스키마 v0.3, 전체 artifact guard, 회귀 테스트·브라우저 CI, README·CLAUDE·About 현재 계약 반영 | 로컬 완료; 원격 CI 미실행 |
| 다음 | 수정본 공개 | 검토된 파일만 좁게 커밋·푸시 후 Pages 산출물과 원격 브라우저 재검증 | 미수행 |
| 별도 | 과거 Git 히스토리·기존 배포 파일 | 현재 버전 수정과 별개로 제거 범위·영향을 결정하고 실행 | 미수행 |
| 별도 | F13 working-memory | 사용자가 소유한 미추적 workmem.py, docs/working-memory.md, .serena 보존 | 이번 구현 제외 |

## 검증 증거

- 로컬 전체 회귀 테스트 38개: 34개 비브라우저 + 4개 브라우저 테스트. 건너뛴 테스트 없음.
- 공개 8페이지 HTTP 200, 테스트가 관측한 JavaScript pageerror 0. 주요 DOM 생성과 Overview 전체 합계 확인.
- 공격 문자열 검증: Pulse 문장, Latent 라벨·단어·툴팁 subject, People 카드, Lifecycle 표, Drift 붙여넣기 블록이 텍스트로 표시되고 공격 마커가 실행되지 않음.
- `quarto render` 성공. 전체 배포 산출물 검사 오류 0. PUBLIC JSON commit/topic/embedding/pulse 스키마 검증.
- 추적 파일과 명시한 새 구현 파일만 복사한 깨끗한 CI 입력 스냅샷에서도 비브라우저 테스트, 렌더, artifact guard, 브라우저 4개 테스트 통과. 실제 원격 Actions 실행은 하지 않음.
- `git diff --check` 통과. Python 소스 16개 AST 구문 확인. 관련 없는 원래 미추적 작업 보존.
- 수집 inventory에서 private/unknown으로 기록된 정확한 `org/repo`를 식별자 경계로 검사: 공개 JSON 및 렌더 텍스트 47개 파일에서 0건. 짧은 이름의 부분 문자열·접두사 일치는 실제 식별자 일치와 구분했다. 이 검사는 수집 시점 inventory 기준이며 재식별 가능성 전체를 증명하지 않는다.

## 실제 데이터 갱신

| 항목 | 결과 |
|---|---:|
| 수집 범위 | pi |
| 수집 시각 UTC | 2026-10-03T11:39:49.104580+00:00 |
| 수집 시각 KST | 2026-10-03 20:39:49 |
| 확인한 저장소 inventory | 486 |
| 수집 대상 저장소 성공 / 실패 | 313 / 0 |
| 원본 repo-commit 이벤트 | 4,484 |
| 공개 출력 행 / 일별 집계 행 | 1,067 / 619 |
| 공개 가중 합계 / Network 가중 합계 | 4,484 / 4,484 |
| 공개 좌표 | 424 |
| 분석 토픽 | 12 |
| 연속 관측 주 | 53 |

커밋은 저장소별 이벤트이므로 같은 SHA가 다른 저장소에 있으면 각각의 관계를 센다. 수집은 토큰으로 접근 가능한 세 조직의 최근 갱신된 비아카이브 저장소 기본 브랜치에 한정된다. 봇과 GitHub 계정에 연결되지 않은 커밋, GitHub 밖의 활동은 포함하지 않는다. 이번 실제 분석은 PI 범위만 수행했다. 전체 저자 수집 경로는 합성 테스트로 검증했다.

## 구조

```mermaid
flowchart LR
  A[로컬 수집: pi/all 분리] --> B[입력·분석 해시 검증]
  B --> C[공개 정책·집계 적용]
  C --> D[세대 교체·Quarto 렌더]
  D --> E[스키마·artifact·브라우저 검사]
```

기존 세대가 있으면 Linux renameat2 exchange로 디렉터리를 원자적으로 교환한다. 지원하지 않는 플랫폼은 교체를 실패 처리한다. 파일시스템 전원 장애의 영속성까지 검증한 것은 아니다. 파생 분석은 순차 저장하지만 join이 해시 불일치 세대를 공개하지 않는다.

## 즉시 검증

```bash
cd /home/juke/git/activity-atlas
python3 -m unittest discover -s tests -v
/home/juke/.local/quarto/bin/quarto render
python3 scripts/check_public.py --site _site
```

브라우저 테스트는 README의 localhost HTTP 서버와 `AA_TEST_URL`을 사용한다. URL 없는 단위 테스트 실행은 브라우저 4개를 명시적으로 건너뛴다.

## 남은 범위

현재 변경 파일은 미커밋 상태이고 공개 사이트는 이번 수정본으로 배포되지 않았다. CI 성공·사용자 효과·모든 상호작용·접근성·토픽의 과학적 타당성을 인증하지 않는다. 공개 저장소 예외 승인이나 제외 정책은 자동 결정하지 않았다. 수집 자동화는 추가하지 않았으며 월요일 CI는 공개 JSON 검증과 재렌더만 수행한다.

기존 리뷰는 당시 상태를 기록한 역사적 문서로 보존한다. 이번 구현은 새 보고서와 검증 증거로 구분한다. 원본 메시지·학생 이름·비공개 저장소 이름·인증정보는 이 보고서와 JSON 증거에 포함하지 않는다.
