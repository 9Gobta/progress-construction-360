from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np

BEAM_PROMPT = (
    "horizontal structural ground beam reinforcement cage connecting two columns. "
    "horizontal structural beam timber formwork connecting two columns. "
    "horizontal concrete structural beam connecting two columns before formwork removal. "
    "horizontal exposed reinforced concrete structural beam connecting two columns."
)


@dataclass(frozen=True)
class BeamDetection:
    stage: str
    score: float
    box_xyxy: tuple[float, float, float, float]
    label: str


class BeamDetector(Protocol):
    def detect(self, images: Sequence[np.ndarray]) -> list[list[BeamDetection]]: ...


def stage_from_label(label: str) -> str | None:
    """Map an observed beam component to a construction stage.

    Absence is deliberately not mapped to NOT_STARTED: an object detector not
    finding a beam is not evidence that the planned beam has not started.
    """
    normalized = label.casefold()
    candidates: set[str] = set()
    if "rebar" in normalized or "reinforcement cage" in normalized:
        candidates.add("REBAR")
    if "formwork" in normalized or "shuttering" in normalized:
        candidates.add("FORMWORK")
    if "formwork removal" in normalized or "exposed reinforced concrete" in normalized:
        candidates.add("STRIPPED")
        candidates.discard("FORMWORK")
    elif "concrete poured" in normalized or "cast concrete" in normalized:
        candidates.add("CONCRETED")
        candidates.discard("FORMWORK")
    # Grounding DINO can occasionally return a phrase spanning two prompts.
    # Such a label is not valid stage evidence and must be reviewed instead.
    return next(iter(candidates)) if len(candidates) == 1 else None


def is_plausible_beam_box(
    box_xyxy: tuple[float, float, float, float],
    *,
    image_width: int,
    image_height: int,
) -> bool:
    """Reject column cages, poles and tiny boxes before stage voting.

    Each panorama is rendered with overlapping yaw views. A real beam that is
    strongly foreshortened in one view should therefore appear horizontally in
    a neighbouring view. Requiring a horizontal span is safer than accepting a
    vertical rebar cage as beam evidence.
    """
    x1, y1, x2, y2 = box_xyxy
    width = max(0.0, x2 - x1)
    height = max(0.0, y2 - y1)
    if width < image_width * 0.08 or height < image_height * 0.025:
        return False
    if width < height * 1.25:
        return False
    return width * height >= image_width * image_height * 0.003


class GroundingDinoBeamDetector:
    """Zero-shot beam detector used to bootstrap real image annotations.

    Imports are lazy so the API can still start on machines where the optional
    beam-ai dependency is not installed. Inference itself fails loudly instead
    of silently reverting to a colour/texture heuristic.
    """

    def __init__(
        self,
        *,
        model_id: str = "IDEA-Research/grounding-dino-tiny",
        device: str | None = None,
        box_threshold: float = 0.30,
        text_threshold: float = 0.25,
    ) -> None:
        try:
            import torch
            from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
        except ImportError as exc:  # pragma: no cover - depends on optional runtime
            raise RuntimeError(
                "ยังไม่ได้ติดตั้งตัวตรวจคานจริง: ติดตั้ง optional dependency 'beam-ai' ก่อน"
            ) from exc

        self._torch = torch
        self._device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._processor = AutoProcessor.from_pretrained(model_id)
        self._model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id)
        self._model.to(self._device)
        self._model.eval()
        self._box_threshold = box_threshold
        self._text_threshold = text_threshold

    def detect(self, images: Sequence[np.ndarray]) -> list[list[BeamDetection]]:
        if not images:
            return []
        # OpenCV supplies BGR while Hugging Face processors expect RGB.
        rgb_images = [image[:, :, ::-1] for image in images]
        prompts = [BEAM_PROMPT] * len(rgb_images)
        inputs = self._processor(
            images=rgb_images,
            text=prompts,
            return_tensors="pt",
            padding=True,
        ).to(self._device)
        with self._torch.inference_mode():
            outputs = self._model(**inputs)
        target_sizes = [(image.shape[0], image.shape[1]) for image in rgb_images]
        processed = self._processor.post_process_grounded_object_detection(
            outputs,
            inputs.input_ids,
            box_threshold=self._box_threshold,
            text_threshold=self._text_threshold,
            target_sizes=target_sizes,
        )
        batches: list[list[BeamDetection]] = []
        for result in processed:
            labels = result.get("text_labels", result.get("labels", []))
            detections: list[BeamDetection] = []
            for score, box, label in zip(
                result["scores"], result["boxes"], labels, strict=True
            ):
                label_text = str(label)
                stage = stage_from_label(label_text)
                if stage is None:
                    continue
                box_xyxy = tuple(float(value) for value in box.detach().cpu())
                if not is_plausible_beam_box(
                    box_xyxy,
                    image_width=rgb_images[0].shape[1],
                    image_height=rgb_images[0].shape[0],
                ):
                    continue
                detections.append(
                    BeamDetection(
                        stage=stage,
                        score=float(score.detach().cpu()),
                        box_xyxy=box_xyxy,
                        label=label_text,
                    )
                )
            batches.append(detections)
        return batches
