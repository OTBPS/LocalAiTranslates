"""PaddleOCR implementation and language-routing helpers."""

import logging
import os
import threading
import time
from pathlib import Path

from .core import TARGET_LANGUAGES, Cancelled, OcrLine, OcrResult
from .models import OCR_MODEL_IDS, resolve_model_path

LOGGER = logging.getLogger(__name__)
PERFORMANCE_LOGGER = logging.getLogger("screen_translator.performance")
STANDARD_REC = "PP-OCRv5_mobile_rec"
KOREAN_REC = "korean_PP-OCRv5_mobile_rec"


def script_counts(text):
    counts = {"hangul": 0, "kana": 0, "han": 0, "latin": 0}
    for char in text:
        if "\uac00" <= char <= "\ud7af":
            counts["hangul"] += 1
        elif "\u3040" <= char <= "\u30ff":
            counts["kana"] += 1
        elif "\u4e00" <= char <= "\u9fff":
            counts["han"] += 1
        elif "a" <= char.lower() <= "z":
            counts["latin"] += 1
    return counts


def text_language(text):
    counts = script_counts(text)
    if counts["hangul"]:
        return "ko"
    if counts["kana"]:
        return "ja"
    if counts["han"]:
        return "zh-Hans"
    if counts["latin"]:
        return "en"
    return "auto"


def dominant_language(lines):
    scores = {code: 0.0 for code in TARGET_LANGUAGES}
    for line in lines:
        counts = script_counts(line.text)
        weight = max(0.25, line.confidence)
        if counts["hangul"]:
            scores["ko"] += weight * (counts["hangul"] * 3 + counts["latin"])
        elif counts["kana"]:
            scores["ja"] += weight * (counts["kana"] * 3 + counts["han"])
        else:
            scores["zh-Hans"] += weight * counts["han"] * 2
            scores["en"] += weight * counts["latin"]
    language, score = max(scores.items(), key=lambda item: item[1])
    return language if score else "en"


def representative_indices(polygons, limit=6):
    """Choose large samples while retaining top/middle/bottom coverage."""
    if len(polygons) <= limit:
        return list(range(len(polygons)))
    geometry = []
    for index, polygon in enumerate(polygons):
        xs, ys = zip(*polygon, strict=True)
        geometry.append((index, (max(xs) - min(xs)) * (max(ys) - min(ys)), (min(ys) + max(ys)) / 2))
    minimum = min(item[2] for item in geometry)
    span = max(1.0, max(item[2] for item in geometry) - minimum)
    selected = []
    for band in range(3):
        candidates = [item for item in geometry if min(2, int((item[2] - minimum) / span * 3)) == band]
        if candidates:
            selected.append(max(candidates, key=lambda item: item[1])[0])
    for index, _, _ in sorted(geometry, key=lambda item: item[1], reverse=True):
        if index not in selected:
            selected.append(index)
        if len(selected) == limit:
            break
    return selected


def prefer_korean(standard, korean):
    korean_hits = 0
    standard_score = korean_score = 0.0
    count = 0
    for index in set(standard) & set(korean):
        standard_text, standard_confidence = standard[index]
        korean_text, korean_confidence = korean[index]
        counts = script_counts(korean_text)
        letters = sum(counts.values()) or 1
        hangul_ratio = counts["hangul"] / letters
        if counts["hangul"] >= 2 and hangul_ratio >= 0.2:
            korean_hits += 1
        standard_score += standard_confidence
        korean_score += korean_confidence + 0.2 * hangul_ratio
        count += 1
    return bool(count and korean_hits and korean_score / count >= standard_score / count + 0.02)


class OcrEngine:
    def __init__(self, root, allow_cpu=False):
        self.root = Path(root).resolve()
        self.allow_cpu = allow_cpu
        self.recognizers = {}
        self.detector = None
        self.device = None
        self.mode = "未加载"
        self.lock = threading.RLock()

    def _configure_environment(self):
        # All paths are explicit. Paddle must not discover/download models at inference time.
        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["PADDLE_PDX_DISABLE_TELEMETRY"] = "1"
        os.environ["FLAGS_allocator_strategy"] = "auto_growth"
        os.environ["PADDLE_PDX_LOCAL_FONT_FILE_PATH"] = str(
            Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
        )

    def _choose_device(self):
        if self.device:
            return
        import paddle

        if paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0:
            self.device, self.mode = "gpu:0", "CUDA"
        elif self.allow_cpu:
            self.device, self.mode = "cpu", "CPU（速度较慢）"
        else:
            raise RuntimeError("OCR CUDA 不可用；请安装 GPU 版程序，或在设置中允许 CPU 降级")

    def _component_options(self):
        options = {"device": self.device, "enable_mkldnn": False}
        if self.device == "cpu":
            options["cpu_threads"] = min(8, os.cpu_count() or 4)
        return options

    def _ensure_detector(self, token, progress):
        self._configure_environment()
        self._choose_device()
        if self.detector is None:
            token.check()
            progress(f"正在加载文字检测模型 · {self.mode}…")
            from paddleocr import TextDetection

            self.detector = TextDetection(
                model_name="PP-OCRv5_mobile_det",
                model_dir=str(
                    resolve_model_path(
                        self.root,
                        OCR_MODEL_IDS["PP-OCRv5_mobile_det"],
                        "ocr-detection",
                    )
                ),
                **self._component_options(),
            )

    def _recognizer(self, name, token, progress):
        if name not in self.recognizers:
            token.check()
            progress(f"正在加载文字识别模型 · {self.mode}…")
            from paddleocr import TextRecognition

            self.recognizers[name] = TextRecognition(
                model_name=name,
                model_dir=str(
                    resolve_model_path(
                        self.root,
                        OCR_MODEL_IDS[name],
                        "ocr-recognition-ko" if name == KOREAN_REC else "ocr-recognition",
                    )
                ),
                **self._component_options(),
            )
        return self.recognizers[name]

    def _predict(self, name, crops, indices, token, progress):
        if not indices:
            return {}
        recognizer = self._recognizer(name, token, progress)
        # Similar widths share a batch, reducing padding and GPU work.
        order = sorted(indices, key=lambda index: crops[index].shape[1] / max(1, crops[index].shape[0]))
        token.check()
        progress(f"正在识别文字 · {self.mode}…")
        results = list(
            recognizer.predict(
                [crops[index] for index in order], batch_size=32 if self.device != "cpu" else 8
            )
        )
        token.check()
        output = {}
        for index, result in zip(order, results, strict=True):
            output[index] = (str(result["rec_text"]), float(result["rec_score"]))
        return output

    def _reset_for_cpu(self):
        self.detector = None
        self.recognizers.clear()
        self.device, self.mode = "cpu", "CPU（速度较慢）"

    def warmup(self, source_language, token, progress):
        """Load and prime OCR components using synthetic in-memory pixels."""
        if source_language not in ("auto", *TARGET_LANGUAGES):
            raise ValueError("不支持的输入语言")
        with self.lock:
            try:
                self._ensure_detector(token, progress)
                import numpy as np

                synthetic_page = np.zeros((64, 256, 3), dtype=np.uint8)
                synthetic_crop = np.zeros((32, 160, 3), dtype=np.uint8)
                token.check()
                list(self.detector.predict(synthetic_page, limit_side_len=1280, limit_type="max"))
                names = (
                    (STANDARD_REC, KOREAN_REC)
                    if source_language == "auto"
                    else (KOREAN_REC if source_language == "ko" else STANDARD_REC,)
                )
                for name in names:
                    self._predict(name, [synthetic_crop], [0], token, progress)
            except Cancelled:
                raise
            except Exception:
                # A transient startup failure must not lock the real capture into a stale mode.
                self.detector = None
                self.recognizers.clear()
                self.device = None
                self.mode = "未加载"
                raise

    def _recognize_once(self, image, source_language, token, progress):
        started = time.monotonic()
        self._ensure_detector(token, progress)
        token.check()
        progress(f"正在定位文字 · {self.mode}…")
        import cv2
        import numpy as np

        detection_started = time.monotonic()
        detected = self.detector.predict(image, limit_side_len=1280, limit_type="max")[0]
        detection_ms = (time.monotonic() - detection_started) * 1000
        polygons, crops = [], []
        for poly in detected["dt_polys"]:
            x, y, w, h = cv2.boundingRect(np.asarray(poly, dtype=np.float32))
            x1, y1 = max(0, x), max(0, y)
            x2, y2 = min(image.shape[1], x + w), min(image.shape[0], y + h)
            if x2 > x1 and y2 > y1:
                polygons.append([(float(x), float(y)) for x, y in poly])
                crops.append(image[y1:y2, x1:x2])
        if not crops:
            timings = {
                "detection": round(detection_ms, 1),
                "routing": 0.0,
                "recognition": 0.0,
                "total": round((time.monotonic() - started) * 1000, 1),
            }
            return OcrResult([], source_language if source_language != "auto" else "en", self.mode, timings)

        all_indices = list(range(len(crops)))
        routing_ms = 0.0
        cached = {STANDARD_REC: {}, KOREAN_REC: {}}
        if source_language == "auto":
            routing_started = time.monotonic()
            samples = representative_indices(polygons)
            cached[STANDARD_REC] = self._predict(STANDARD_REC, crops, samples, token, progress)
            cached[KOREAN_REC] = self._predict(KOREAN_REC, crops, samples, token, progress)
            primary = KOREAN_REC if prefer_korean(cached[STANDARD_REC], cached[KOREAN_REC]) else STANDARD_REC
            secondary = STANDARD_REC if primary == KOREAN_REC else KOREAN_REC
            routing_ms = (time.monotonic() - routing_started) * 1000
        else:
            primary = KOREAN_REC if source_language == "ko" else STANDARD_REC
            secondary = None

        recognition_started = time.monotonic()
        primary_results = dict(cached[primary])
        remaining = [index for index in all_indices if index not in primary_results]
        primary_results.update(self._predict(primary, crops, remaining, token, progress))

        if secondary:
            uncertain = [index for index, (_, confidence) in primary_results.items() if confidence < 0.72]
            secondary_results = dict(cached[secondary])
            missing = [index for index in uncertain if index not in secondary_results]
            secondary_results.update(self._predict(secondary, crops, missing, token, progress))
            for index in uncertain:
                if index not in secondary_results:
                    continue
                primary_text, primary_confidence = primary_results[index]
                candidate_text, candidate_confidence = secondary_results[index]
                candidate_language = text_language(candidate_text)
                plausible_korean = (
                    secondary == KOREAN_REC
                    and candidate_language == "ko"
                    and candidate_confidence >= primary_confidence - 0.03
                )
                plausible_standard = (
                    secondary == STANDARD_REC
                    and candidate_language in ("zh-Hans", "ja")
                    and candidate_confidence > primary_confidence + 0.025
                )
                if plausible_korean or plausible_standard or candidate_confidence > primary_confidence + 0.08:
                    primary_results[index] = (candidate_text, candidate_confidence)

        lines = []
        for index, polygon in enumerate(polygons):
            if index not in primary_results:
                continue
            text, confidence = primary_results[index]
            language = text_language(text)
            if language == "auto" and source_language != "auto":
                language = source_language
            lines.append(OcrLine(polygon, text, confidence, language))
        detected_language = source_language if source_language != "auto" else dominant_language(lines)
        recognition_ms = (time.monotonic() - recognition_started) * 1000
        timings = {
            "detection": round(detection_ms, 1),
            "routing": round(routing_ms, 1),
            "recognition": round(recognition_ms, 1),
            "total": round((time.monotonic() - started) * 1000, 1),
        }
        PERFORMANCE_LOGGER.info(
            "OCR timing ms device=%s detection=%.1f routing=%.1f recognition=%.1f total=%.1f",
            self.mode,
            timings["detection"],
            timings["routing"],
            timings["recognition"],
            timings["total"],
        )
        return OcrResult(lines, detected_language, self.mode, timings)

    def recognize(self, image, source_language, token, progress):
        if source_language not in ("auto", *TARGET_LANGUAGES):
            raise ValueError("不支持的输入语言")
        with self.lock:
            try:
                return self._recognize_once(image, source_language, token, progress)
            except Cancelled:
                raise
            except Exception as error:
                if self.allow_cpu and self.device != "cpu":
                    LOGGER.warning("OCR CUDA failed, falling back to CPU: %s", type(error).__name__)
                    progress("OCR CUDA 启动失败，正在切换到 CPU…")
                    self._reset_for_cpu()
                    return self._recognize_once(image, source_language, token, progress)
                if self.device != "cpu":
                    raise RuntimeError(
                        "OCR CUDA 初始化或推理失败；请关闭占用显存的应用，或允许 CPU 降级"
                    ) from error
                raise
