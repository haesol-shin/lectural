# Static visual duplicate regression fixture

`static_article_00.png` through `static_article_02.png` are consecutive 2fps
samples of one unchanged article screen. The latter two include a stable
top-left render artifact: it pushes pHash past its change gate while retaining
histogram/SSIM similarity. Thus the old pHash-only path keeps the false change,
whereas the confirming gate folds it back into the static screen. OCR output may
still drift between such samples, but is deliberately not used for this visual
decision. The fixture is image-only so it stays small and deterministic.
