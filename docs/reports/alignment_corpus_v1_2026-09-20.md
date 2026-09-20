# Alignment corpus v1 diagnostic

`scripts/generate_alignment_image_corpus.py` generated immutable PNG sequence bytes at `tests/fixtures/visual_alignment/corpus_v1/` and the matching SHA-256 manifest at `tests/fixtures/visual_alignment/sequence_manifest_v1.json`. Development uses two authored seeds per class; held-out uses one disjoint seed and disjoint `source_content_id` per class. The observed YouTube source is not in either split.

Run:

```powershell
uv run python scripts/calibrate_alignment.py --manifest tests/fixtures/visual_alignment/sequence_manifest_v1.json --out .tmp/alignment-sequence-v1.json
```

Result: `frozen:false`. The command completed after the canonical-hash path was made fail-closed for non-finite OpenCV diagnostics. It did not write a production artifact.

The measured sequence result has development `TP=0, FN=4, TN=23, FP=0` and held-out `TP=0, FN=2, TN=12, FP=0`. Static/incremental sequence recipes did not cross the pHash persistence boundary, so they did not produce scored events; pan/zoom positives reached alignment but failed content change (development) or residual/coverage (held-out). This corpus therefore proves that the current generated-image recipe does not separate the required supported positives from negatives.

The first run was also ineligible under the then-current single-provider gate because the resolved environment contained `opencv-python`, `opencv-contrib-python`, and `opencv-python-headless` together. Production later standardized and calibrated that exact three-provider set at `4.6.0.66`; this older corpus remains diagnostic because its positive recipes still fail the measured separation requirements above, not because of the superseded provider rule.

Consequently this is diagnostic evidence only. Do not copy its thresholds into `lectural/config.py`, set `frozen:true`, or wire it into production. The promoted thresholds instead come from `real_sequence_v1`, whose revised positive/fallback recipes and fresh held-out split satisfy the frozen calibration gate.
