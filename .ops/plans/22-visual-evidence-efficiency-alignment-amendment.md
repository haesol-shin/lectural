# Amendment plan: transform-aware visual confirmation for Issue #22

## Scope and evidence

**Understood as:** preserve the approved pHash-plus-direct-visual confirmation design, but add a bounded affine-alignment branch for a pHash-persistent candidate whose direct comparison fails solely because the same screen was panned or zoomed. No public contract changes are proposed here.

The approved plan's direct histogram/SSIM confirmation cannot solve the local source case at `.tmp/youtube-noPuRPDiY6k-20260919-actual/frames`: frames `00865` (432.5s), `00874` (437s), and `00888` (444s) show the same article under coordinate changes, while `00890` (~445s) is a true transition. At 640x360, direct SSIM for `865→874` / `865→888` is `.4545` / `.5823`; fixed OpenCV ORB/RANSAC alignment gives respectively 204/345 inliers (261/375 ratio-test matches), scales `1.1508`/`.9379`, and bidirectional masked SSIM minima `.9706`/`.9571`. The transition gives only three degenerate inliers despite a misleading `.9517` forward score.

The project pins `opencv-python>=4.5,<=4.6.0.66` (`pyproject.toml`, `uv.lock`). This plan targets that build family only. OpenCV 4.6 documents ORB's Hamming matcher and two-neighbor matching [here](https://docs.opencv.org/4.6.0/dc/dc3/tutorial_py_matcher.html), and `estimateAffinePartial2D`'s four-DOF/RANSAC parameters [here](https://docs.opencv.org/4.6.0/d9/d0c/group__calib3d.html).

## Decision path

1. Keep the existing 64-bit pHash, Hamming threshold, persistence count, sequential reference, and direct histogram/SSIM confirmation unchanged as the default path. It remains the only production behavior until the calibration contract below is frozen and passes.
2. Record the complete local reproduction state, not just endpoints: pHash values/distances, `PHASH_CHANGE_PERSISTENCE` counter, current kept reference, candidate start index, counter reset/confirmation, and whether the direct confirmation was attempted for every sampled member of `865→874→888`. Assert the expected persistent-change branch is reached for both `865→874` and `865→888`, rather than merely asserting a final kept-frame list.
3. Alignment is a secondary, fail-closed branch only after the existing persistent pHash candidate fails the approved direct same-slide test. It can return `same` only on its full geometry-and-visual proof. `not_same`, unavailable OpenCV, exception, or any failed gate keeps the approved direct-test result: distinct. It never converts the implementation into pHash-only dedupe.
4. If calibration fails to produce frozen thresholds or held-out validation fails, do one of two explicit outcomes: do not wire alignment and retain the approved pHash+direct histogram/SSIM production behavior, or stop the change with no production dedupe modification. Do not merge a fallback different from either outcome.

## Deterministic alignment contract

Run all alignment work for one `dedupe_frames` invocation in a short-lived, dedicated worker process; the host never calls OpenCV's RNG/thread setters. The worker handles its candidate sequence serially, calls `cv2.setRNGSeed(0)` immediately before ORB and every RANSAC call, calls `cv2.setNumThreads(1)` before processing, serializes only plain measurements/results back to the host, and exits before `dedupe_frames` returns. This contains OpenCV's process-global RNG/thread state and makes unrelated host OpenCV callers irrelevant. Metadata records `cv2.__version__`, package/version constraint, requested seed/thread count, worker protocol version, and resolved build. CI/benchmark pins the lockfile and records the resolved OpenCV build; a different major/minor build is unsupported until the corpus is revalidated.

Use exactly:

```python
cv2.ORB_create(nfeatures=1000, scaleFactor=1.2, nlevels=8,
    edgeThreshold=31, firstLevel=0, WTA_K=2,
    scoreType=cv2.ORB_HARRIS_SCORE, patchSize=31, fastThreshold=20)
cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False).knnMatch(..., k=2)
cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
    ransacReprojThreshold=3.0, maxIters=2000,
    confidence=0.99, refineIters=10)
```

Sort matches by `(queryIdx, trainIdx, distance)` and retain only rows with exactly two neighbors and `m.distance < 0.75 * n.distance`. The affine maps reference coordinates to candidate coordinates. Reject a missing/non-finite matrix, non-positive determinant or scale, and every gate below. Partial affine is intentional: translation, rotation, and uniform scale model pan/zoom without allowing shear/perspective to invent agreement.

For every numerical field, use these exact definitions in both calibration and production: `ratio_matches` is the count of retained ratio-test matches; `ratio_match_count` is the number of `knnMatch` rows containing exactly two neighbors; `inlier_count` is the number of nonzero entries in `estimateAffinePartial2D`'s final mask; `inlier_ratio = inlier_count / ratio_matches` (and is not evaluated when `ratio_matches == 0`). With `M=[[a,b,tx],[c,d,ty]]`, `determinant=a*d-b*c` and `scale=sqrt(a*a+c*c)`. Residuals are Euclidean pixel distances from every final-inlier reference keypoint transformed by final `M` to its matched candidate keypoint; median is the ordinary sorted middle (mean of the two middles when even) and P95 is the value at zero-based index `ceil(.95*n)-1`. `hull_support` is `area(convexHull(final-inlier reference keypoints)) / (reference_width * reference_height)` in the downscaled reference coordinate system. `eigenvalue_ratio` is the smaller/larger eigenvalue of the population 2x2 covariance matrix of those same downscaled reference coordinates; it is zero for a non-positive or non-finite larger eigenvalue. These fields are `not_evaluated` whenever their defined input is unavailable.

Decode BGR with `_cv2_imread_unicode(..., IMREAD_COLOR)`. For alignment, independently downscale each input to longest edge `<=640`, preserve aspect ratio, never upscale, `INTER_AREA`; the observed 640x360 images are therefore unresized. Convert only with `COLOR_BGR2GRAY`; no RGB conversion or color histogram accepts/rejects an alignment.

Warp reference BGR to candidate coordinates with `M`, candidate size, `INTER_LINEAR`, `BORDER_CONSTANT`, black value. Warp an all-255 reference support mask with the same transform, `INTER_NEAREST`, same border. Invert `M` and repeat candidate-to-reference. Before erosion, calculate both coverages as nonzero support pixels / destination pixels. Erode each mask once with all-ones 7x7 (the exact radius of the repository's 7x7 SSIM window); border pixels do not participate. In each direction use existing `_ssim` semantics exactly: float64 grayscale, edge-padded 7x7 box moments, `C1=(.01*255)^2`, `C2=(.03*255)^2`, arithmetic mean only over masked pixels. Acceptance requires the lower directional SSIM and both coverages to clear frozen thresholds.

Alignment metadata includes working shapes/scales, settings, ratio matches, inlier count/ratio, final-matrix inlier residual median/P95, affine/scale/determinant, convex-hull support, covariance eigenvalue ratio, both coverage values, both SSIM values, result, and first failed gate. It is internal diagnostic metadata unless separately approved for a public contract.

The canonical gate order is: (1) OpenCV availability and decode; (2) descriptor availability; (3) two-neighbor ratio-match minimum; (4) affine estimation; (5) finite matrix, determinant, and scale range; (6) inlier count and ratio; (7) residual median/P95; (8) non-collinearity and hull support; (9) forward and reverse overlap coverage; (10) forward and reverse masked SSIM. `first_failed_gate` is the first false predicate in that exact order. Record every metric available through that predicate; do not run a dependent later stage after an upstream prerequisite fails, and record it as `not_evaluated` rather than inventing a value.

## Calibration contract: no production wire before freeze

Add a deterministic fixture manifest committed with two immutable lists: `development` and `held_out`. Each row has an ID, generator seed/version, reference/candidate paths, expected label (`same` or `different`), transform class, and the required expected first-failure family for negatives. The real local case is recorded as observational evidence only, not a committed media fixture.

Development positives: exact pan/zoom transforms in both zoom directions, static duplicate, and the existing near duplicate. Development negatives: true transition proxy, same-palette/different-layout, incremental build, panned/zoomed incremental build, panned/zoomed shared-template-but-different-content, too few descriptors/neighbors, RANSAC failure, outlier-heavy, high residual, out-of-scale, collinear/concentrated inliers, one-way coverage failure, and low masked SSIM. Held-out rows use different seeds/content/transforms for every positive and negative class, including incremental/shared-template pan/zoom negatives.

The calibration command writes `docs/reports/alignment_thresholds_<date>.json`; the approved report path and SHA-256 become the canonical, committed source for production constants. It contains: input manifest hash; OpenCV package/version; exact settings; raw per-pair measurements; each threshold; inequality direction; development confusion matrix; held-out confusion matrix; and `frozen: true|false`. Threshold directions are fixed: minimum (`>=`) for ratio matches, inlier count, inlier ratio, hull area, eigenvalue ratio, both coverages, and both SSIMs; maximum (`<=`) for residual median/P95; inclusive range (`min <= scale <= max`) for scale. The artifact must identify every rejected candidate's first failed inequality. Production `config.py` constants must reproduce exactly this frozen vector; production code never recalibrates.

For each candidate parameter setting, choose thresholds only from the development rows. Form each minimum/maximum threshold candidate set from the sorted, finite observed development values for its metric; form `scale_min` and `scale_max` from the sorted, finite observed development scales, retaining only pairs where `scale_min <= scale_max`. Enumerate their Cartesian product in this fixed serialized field order: `ratio_matches`, `inlier_count`, `inlier_ratio`, `hull_support`, `eigenvalue_ratio`, `coverage`, `ssim`, `residual_median`, `residual_p95`, `scale_min`, `scale_max`. Keep vectors for which every development positive passes every inequality and every development negative fails at least one inequality. Select exactly one by descending lexicographic priority over the minimum fields in that order, then ascending `residual_median`, ascending `residual_p95`, descending `scale_min`, and ascending `scale_max`; field values use their IEEE-754 serialized hexadecimal representation, so there is no locale or decimal-format tie. Freeze it before production code is wired. Then run held-out rows without retuning: every held-out positive must pass and every held-out negative must fail. No valid vector, non-deterministic results, or any held-out error means `frozen:false`, no alignment wire, and the fallback in Decision path step 4.

## Required tests and benchmark gates

- Assert full `865→874→888` pHash persistence/candidate state and the attempted direct/alignment branch; assert `00890` is rejected by geometry, not merely retained.
- Cover every manifest class above, including panned/zoomed incrementals and shared-template negatives, and assert the specific failed gate where deterministic.
- Repeat the corpus ten times in one process and twice in fresh processes; require identical decisions and integer match/inlier counts. Matrices/float metrics use an explicit documented tolerance only.
- Assert pHash-near frames never invoke ORB; persistent candidates invoke it once; successful alignment avoids duplicate OCR; any failed alignment preserves the direct-gate distinct result. Preserve non-ASCII path and bounded-memory behavior.
- Extend `scripts/benchmark.py`, its schema/docs/contract tests with pHash candidates, alignment attempts/outcomes by failure reason, keypoints, matches, inliers, coverage/SSIM distributions, decode/warp pixels, OpenCV build/thread/seed, and stage CPU/RSS. Compare three warm repetitions before/after plus `--skip-ocr`; preserve the approved plan's correctness/resource tolerance and require zero regressions in duplicate drop, incremental retention, recall, and timestamp integrity.

## Execution order

1. Create manifest, generated corpus, calibration command, reproducibility report, and tests; freeze/validate thresholds.
2. Only if artifact says `frozen:true`, implement the private alignment helper and wire it into the persistent-candidate/direct-failure branch.
3. Add observability and benchmark evidence.
4. Run `uv run --with pytest --with numpy pytest -q`, `lectural doctor`, `git diff --check`, and the real benchmark. Any nonzero `lectural` exit is a hard failure.

## Unresolved decisions

The numerical threshold vector and whether `nfeatures=1000` meets x86_64/ARM64 resource gates remain unresolved by design. The calibration artifact, not intuition, resolves them; absent a frozen held-out-pass artifact, alignment is not wired.
