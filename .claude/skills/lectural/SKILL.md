---
name: lectural
description: >-
  Use when the user gives a YouTube lecture URL (or several) and wants COMPLETE
  study notes — every spoken word, every on-screen text, and every slide/scene —
  turned into markdown. Triggers on "이 강의 정리해줘", "강의 영상 요약", "transcribe and
  summarize this lecture", or any YouTube link framed as study material. Produces
  a raw transcript + a structured summary and refuses to claim "done" until a
  completeness hook confirms nothing was missed.
argument-hint: <youtube-url> [more-urls...] [--force-stt] [--model medium]
---

# LecturAL — YouTube 강의 완전 정리

가장 중요한 약속: **사용자가 "이 강의를 다 정리했다"고 확신할 수 있어야 합니다.**
모든 발화·모든 화면 텍스트·모든 장면을 빠짐없이 잡습니다. 임의로 요약하거나
건너뛰지 마세요. 완전성은 Stop 훅이 강제합니다(아래).

## 동작 원리 (Option A-prime · 토큰 0)

결정론적 Python 코어가 **외부 LLM 없이** raw 산출물을 만들고, 당신(호스트
에이전트)은 선택적으로 요약을 *보강*만 합니다. 외부 API 토큰 비용은 0입니다.

1. **수집**: 자막 우선(yt-dlp/youtube-transcript-api). 자막이 없거나 `--force-stt`면
   오디오만 받아 faster-whisper(medium, int8, **CPU**)로 전사.
2. **시각**: ffmpeg로 키프레임/장면전환 추출(2fps) → 히스토그램/SSIM 중복 제거 →
   PaddleOCR(한/영, 없으면 Tesseract)로 슬라이드 텍스트. 점증 슬라이드는 분리 유지.
3. **합성**: `transcript.md`(raw, 타임스탬프) + `summary.md`(목차+커버리지+섹션별
   타임스탬프/슬라이드 링크) + `synthesis_input.json` + `coverage.json`.
4. **완전성**: `coverage.json`의 대사 공백·장면 커버리지·산출물 검사.

## 실행

먼저 외부 의존성을 확인하세요(없으면 명확한 설치 안내가 나옵니다):

```bash
python -c "from lectural.deps import preflight; [print(s) for s in preflight()]"
```

단일 또는 순차 배치:

```bash
# 설치: uv pip install -e ".[run]"   (ffmpeg, yt-dlp는 PATH에 필요)
lectural "https://youtu.be/<id>"
lectural "<url1>" "<url2>" --out ./output         # 여러 개 순차 처리
lectural "<url>" --force-stt --model medium       # 자막 무시하고 STT
```

산출물: `./output/<video-title>/` 아래 `transcript.md`, `summary.md`,
`frames/`, `coverage.json`, `synthesis_input.json`.

## 선택: 요약 보강 (토큰 0 유지)

`summary.md`는 이미 결정론적 baseline입니다. 더 풍부한 산문이 필요하면
`synthesis_input.json`(텍스트만, 이미지 미포함)만 읽고 산문을 보강하되, 필수
앵커(`<!-- lectural:baseline -->`, `## 커버리지 요약`, `## 목차`, 섹션 타임스탬프,
`frames/` 링크)는 **반드시 보존**하세요. 원본 이미지를 컨텍스트에 넣지 마세요.

## 완전성 게이트 (반드시 통과)

`.claude/settings.json`의 Stop 훅이 `python scripts/completeness_hook.py`를
실행합니다. 이 훅은 이번 세션에서 만든 모든 run의 `coverage.json`과 `summary.md`
앵커를 검사하고, 하나라도 실패하면 **exit 2로 "완료"를 차단**합니다. 게이트가
막으면 임의 요약으로 우회하지 말고 누락 원인(자막 공백, 미커버 장면, 빈 산출물)을
해결하세요. (Windows에서 `python`이 없으면 `py -3 scripts/completeness_hook.py`.)

## 범위

v1: 단일 + 순차 배치. **제외**(defer): 병렬 배치, 로컬 LLM 요약 폴백,
비개발자 UI, GPU 경로, 화자 분리/번역.

자세한 내용은 `references/pipeline.md`와 `docs/synthesis_contract.md` 참고.
