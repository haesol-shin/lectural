# LecturAL

> YouTube 강의 영상 하나를 받아 **모든 발화·모든 화면 텍스트·모든 슬라이드**를 빠짐없이 잡아 markdown 학습 정리본으로 만들어 주는 Claude Code/Codex 스킬 + 재사용 Python CLI.

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![tests](https://img.shields.io/badge/tests-112%20passing-brightgreen.svg)](#개발테스트)
[![cost](https://img.shields.io/badge/external%20LLM%20tokens-0-success.svg)](#왜-lectural인가)

시험 기간, 강의가 유튜브에만 올라와 있을 때. LecturAL은 "이 강의 다 정리했다"는 **확신**을 주는 걸 목표로 합니다. 임의 요약으로 건너뛰지 않고, 빠진 게 없는지 **자동 검증 훅이 강제**합니다.

---

## 왜 LecturAL인가

- 🧾 **완전 전사본 + 구조화 요약본 둘 다** — 원본 한 줄도 잃지 않는 raw `transcript.md`와, 목차·슬라이드 링크가 달린 `summary.md`.
- 💸 **외부 LLM 토큰 0** — 전사·OCR·기본 요약 전부 결정론적으로 생성. 요약 보강은 이미 켜져 있는 호스트 에이전트(Claude/Codex)가 직접 하므로 별도 API 비용이 없습니다.
- 💻 **노트북(CPU)에서 동작** — GPU 불필요. `faster-whisper medium int8`을 CPU로 구동.
- 🇰🇷 **한국어·영어 자동** — 자막이 있으면 쓰고, 없으면 STT로 전사.
- 🚧 **누락 차단 게이트** — 대사 공백·장면 커버리지·산출물 존재를 검사해 통과 못 하면 "완료"를 막습니다.

## 동작 방식

```
YouTube URL ─▶ 수집(자막 우선 / 없으면 STT)
            ─▶ 시각: ffmpeg 키프레임·장면전환 → 중복 제거 → OCR
            ─▶ 합성: transcript.md + summary.md + frames/ + coverage.json
            ─▶ 완전성 훅: 통과 못 하면 "완료" 차단(exit 2)
```

`transcript.md`·OCR·기본 `summary.md`는 **LLM 없이** 만들어집니다. 호스트 에이전트는 `synthesis_input.json`(텍스트만, 이미지 미포함)만 읽고 요약 산문을 *선택적으로* 보강합니다.

## 요구 사항

- **Python 3.10+**
- **ffmpeg**, **yt-dlp** — PATH에 필요 (실제 영상 처리 시)
- (선택) **Tesseract** — PaddleOCR가 안 될 때의 폴백 OCR
- 패키지 관리: [`uv`](https://github.com/astral-sh/uv) 권장

## 설치

```bash
git clone <repo-url> LecturAL
cd LecturAL

# 코어 + 실행 의존성(yt-dlp, faster-whisper, opencv, paddleocr 등) 설치
uv pip install -e ".[run]"

# ffmpeg는 시스템 바이너리로 별도 설치 (Windows 예시)
winget install Gyan.FFmpeg
```

설치 후 의존성 상태를 먼저 확인하세요(없으면 설치 안내가 출력됩니다):

```bash
python -c "from lectural.deps import preflight; [print(s) for s in preflight()]"
```

## 빠른 시작

```bash
# 단일 강의
lectural "https://youtu.be/<VIDEO_ID>"

# 여러 강의 순차 처리 (친구가 강의 많을 때)
lectural "<url1>" "<url2>" --out ./output

# 자막을 믿지 못할 때 STT 강제
lectural "<url>" --force-stt --model medium
```

기대 출력:

```text
[OK] ./output/운영체제-1강/
완료 게이트는 Stop 훅(scripts/completeness_hook.py)이 최종 검증합니다.
```

## 출력 구조

```
output/<video-title>/
├── transcript.md          # 원본 전사본(raw, 타임스탬프 포함) — 모든 발화
├── summary.md             # 학습 정리본: 목차 + 커버리지 요약 + 섹션별 타임스탬프/슬라이드 링크
├── synthesis_input.json   # (선택) 호스트 에이전트 요약 보강용 입력 — 텍스트만
├── coverage.json          # 완전성 게이트 입력(대사 공백/장면 커버리지/산출물)
└── frames/                # 중복 제거된 슬라이드 이미지
```

## CLI 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `urls` | YouTube URL 1개 이상(순차 처리) | — |
| `--force-stt` | 자막 무시하고 STT로 전사 | off |
| `--model` | faster-whisper 모델 크기 | `medium` |
| `--out` | 출력 루트 디렉터리 | `./output` |

```bash
lectural --help
```

## 완전성 게이트 (핵심)

`.claude/settings.json`의 Stop 훅이 `python scripts/completeness_hook.py`를 실행합니다. 이 훅은 이번 실행에서 만든 **모든** run을 검사하고, 하나라도 아래에 걸리면 **exit 2로 "완료"를 차단**합니다:

1. **대사 공백** — 무음을 제외한, 60초 넘는 미전사 발화 구간이 없어야 함
2. **장면 커버리지** — 영상 전 구간에 키프레임이 있고, 슬라이드로 분류된 프레임엔 OCR 텍스트가 있어야 함
3. **산출물** — `transcript.md`·`summary.md`가 존재하고 비어있지 않으며, 필수 앵커(목차·커버리지·타임스탬프·슬라이드 링크)를 갖춰야 함

실패한 영상이나 처리되지 않은 영상도 게이트에 잡혀서 통과하지 못합니다(우회 불가, fail-closed). (Windows에서 `python`이 없으면 `py -3 scripts/completeness_hook.py`.)

## Claude Code / Codex 스킬로 쓰기

`.claude/skills/lectural/SKILL.md`가 포함되어 있어, 에이전트 세션에서 강의 URL을 던지면 자동으로 이 파이프라인을 호출합니다. 상세 동작은 `SKILL.md`와 `docs/synthesis_contract.md` 참고.

## 기술 스택

수집 `yt-dlp` + `youtube-transcript-api` · STT `faster-whisper`(CTranslate2 int8, CPU) · 시각 `ffmpeg` + `OpenCV`(히스토그램/SSIM 중복 제거) · OCR `PaddleOCR`(PP-OCRv5) → `Tesseract` 폴백 · 합성/커버리지/CLI는 의존성 없는 순수 Python.

## 개발·테스트

결정론적 로직(중복 제거·대사 공백·OCR 분리·요약 앵커·커버리지·훅·CLI)은 외부 바이너리/모델 없이 **오프라인 단위 테스트**로 검증됩니다.

```bash
uv run --with pytest --with numpy pytest -q     # 112 passed
```

외부 바이너리/모델이 필요한 실영상 경로는 `smoke`로 표시되어 기본 실행에서 제외됩니다. AC별 검증 현황은 [`docs/ac_verification.md`](docs/ac_verification.md) 참고.

## 프로젝트 구조

```
lectural/        # 재사용 코어 (acquisition, speech, vad, visual, ocr, synthesis, coverage, cli, runstate)
scripts/         # completeness_hook.py (Stop 훅)
.claude/         # skills/lectural/SKILL.md + settings.json(훅 wiring)
docs/            # synthesis_contract.md, ac_verification.md
tests/           # 오프라인 단위 + 적대적(red-team) 테스트
```

## 범위 (v1)

**포함**: 단일 + 순차 배치. **제외(추후)**: 병렬 배치, 로컬 LLM(Ollama) 요약 폴백, 비개발자용 GUI, GPU 가속, 화자 분리/번역. 핵심 파이프라인은 재사용 모듈로 분리되어 있어 추후 GUI나 독립 프로그램으로 감싸기 쉽습니다.

## 자주 묻는 질문

**Q. 자막이 없는 강의도 되나요?** — 네. 자막이 없거나 부실하면 오디오만 받아 STT로 전사합니다(`--force-stt`로 강제 가능).

**Q. 영상이 1~2시간이면 느리지 않나요?** — CPU STT는 길수록 느립니다. 기본 `medium`이며 너무 길면 경고하고, `--model small`로 속도/정확도를 조절할 수 있습니다.

**Q. OCR가 일부 프레임에서 빈 텍스트를 내요.** — 정상입니다. 말하는 사람만 잡힌 장면 등 텍스트 없는 프레임이 많아, OCR 실패율은 게이트로 쓰지 않습니다. "슬라이드로 분류된 프레임엔 텍스트가 있는가"만 검사합니다.

## 라이선스

아직 라이선스가 지정되지 않았습니다(개인 학습용). 공개 배포 전 `LICENSE` 추가를 권장합니다.
