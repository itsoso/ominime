"""Local multimodal analysis backends for submission context."""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


CONTEXT_ANALYSIS_SYSTEM_PROMPT = (
    "You are OmniMe's local private multimodal context parser. "
    "Analyze the screenshot and metadata only to summarize the user's current dialog context. "
    "Return strict JSON. Do not infer sensitive facts that are not visible."
)


@dataclass
class MultimodalAnalysisRequest:
    submitted_text: str
    screenshot_path: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MultimodalAnalysisResponse:
    analysis_json: dict[str, Any] | None
    raw_output: str
    model: str
    status: str
    error: str | None = None


class MultimodalBackend(ABC):
    @abstractmethod
    def analyze_context(self, request: MultimodalAnalysisRequest) -> MultimodalAnalysisResponse:
        """Analyze submitted text plus optional screenshot/context metadata."""


def build_qwen_vl_messages(
    submitted_text: str,
    screenshot_path: str | None,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    metadata = metadata or {}
    prompt = {
        "submitted_text": submitted_text,
        "metadata": metadata,
        "required_json_schema": {
            "context_type": "chat|document|code|browser|terminal|unknown",
            "conversation_title": "string|null",
            "visible_participants": ["string"],
            "visible_topic": "string|null",
            "user_intent": "string|null",
            "submitted_text_clean": "string",
            "surrounding_messages_summary": "string|null",
            "visible_relevant_text": ["string"],
            "ui_location": {
                "app": "string",
                "window": "string|null",
                "container_role": "string|null",
            },
            "confidence": 0.0,
            "warnings": ["string"],
        },
    }

    content: list[dict[str, Any]] = []
    if screenshot_path:
        content.append({"type": "image", "image": screenshot_path})
    content.append(
        {
            "type": "text",
            "text": (
                "Analyze this Enter-submitted UI context. Return strict JSON only.\n"
                + json.dumps(prompt, ensure_ascii=False, indent=2)
            ),
        }
    )

    return [
        {"role": "system", "content": CONTEXT_ANALYSIS_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def parse_json_response(raw_output: str) -> dict[str, Any]:
    text = raw_output.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


class QwenVLTransformersBackend(MultimodalBackend):
    """Local Qwen2.5-VL backend using transformers and qwen-vl-utils."""

    def __init__(
        self,
        model_name: str = "Qwen/Qwen2.5-VL-7B-Instruct",
        max_new_tokens: int = 768,
        temperature: float = 0.1,
    ):
        self.model_name = model_name
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self._model = None
        self._processor = None

    def analyze_context(self, request: MultimodalAnalysisRequest) -> MultimodalAnalysisResponse:
        try:
            self._load_model()
        except Exception as exc:
            return MultimodalAnalysisResponse(None, "", self.model_name, "missing_dependency", str(exc))

        try:
            messages = build_qwen_vl_messages(
                request.submitted_text,
                request.screenshot_path,
                request.metadata,
            )
            raw_output = self._generate(messages)
            try:
                parsed = parse_json_response(raw_output)
            except Exception as exc:
                return MultimodalAnalysisResponse(None, raw_output, self.model_name, "invalid_json", str(exc))
            return MultimodalAnalysisResponse(parsed, raw_output, self.model_name, "ok")
        except Exception as exc:
            return MultimodalAnalysisResponse(None, "", self.model_name, "failed", str(exc))

    def _load_model(self):
        if self._model is not None and self._processor is not None:
            return

        from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration
        import torch

        self._processor = AutoProcessor.from_pretrained(self.model_name, trust_remote_code=True)
        device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        self._model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            self.model_name,
            torch_dtype=torch.float16 if device != "cpu" else torch.float32,
            device_map="auto" if device == "cuda" else None,
            trust_remote_code=True,
        )
        if device == "mps":
            self._model = self._model.to(device)

    def _generate(self, messages: list[dict[str, Any]]) -> str:
        from qwen_vl_utils import process_vision_info

        text = self._processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = self._processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        ).to(self._model.device)

        generated_ids = self._model.generate(
            **inputs,
            max_new_tokens=self.max_new_tokens,
            temperature=self.temperature,
            do_sample=self.temperature > 0,
        )
        generated_ids_trimmed = [
            output_ids[len(input_ids):]
            for input_ids, output_ids in zip(inputs.input_ids, generated_ids)
        ]
        return self._processor.batch_decode(
            generated_ids_trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0]


def get_multimodal_backend() -> MultimodalBackend | None:
    backend = os.getenv("MULTIMODAL_BACKEND", "qwen-vl-local").lower()
    if backend != "qwen-vl-local":
        return None
    return QwenVLTransformersBackend(
        model_name=os.getenv("QWEN_VL_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct"),
        max_new_tokens=int(os.getenv("QWEN_VL_MAX_NEW_TOKENS", "768")),
        temperature=float(os.getenv("QWEN_VL_TEMPERATURE", "0.1")),
    )
