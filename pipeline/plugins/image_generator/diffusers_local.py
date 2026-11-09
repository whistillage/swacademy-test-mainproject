"""HuggingFace diffusers 모델을 로컬 GPU 에서 실행한다.

model_id 만 바꾸면 다른 모델로 교체된다 (파이프라인 종류는 모델의 model_index.json 으로 자동 결정).
  예) black-forest-labs/FLUX.2-klein-4B, stabilityai/sd-turbo, stabilityai/sdxl-turbo

GPU 메모리가 부족하면 quantization 으로 줄인다 (bitsandbytes 필요).
  nf4  : 4비트. FLUX.2-klein-4B 기준 약 16GB -> 약 5GB (8GB GPU 에 모두 올라감)
  int8 : 8비트
  null : 양자화 안 함 (GPU 메모리가 충분할 때)
양자화할 구성요소는 quantize_components (기본: transformer, text_encoder. VAE 는 작아서 제외).

모델은 첫 generate() 때 불러온다. 그래서 01~03 단계 결과는 모델 로드 전에 먼저 저장된다.
모델이 지원하지 않는 옵션(negative_prompt 등)은 넘기지 않고 metadata.ignored 에 기록한다.

설치: pip install -r requirements-gpu.txt (CUDA 용 torch 포함, README 참고)
"""

from __future__ import annotations

import inspect
import io
import random
from typing import Any

from .base import GeneratedImage, GenerationResult, ImageGenerator, ImageRequest, register

_QUANT_BACKENDS = {
    "nf4": ("bitsandbytes_4bit", {"load_in_4bit": True, "bnb_4bit_quant_type": "nf4"}),
    "int8": ("bitsandbytes_8bit", {"load_in_8bit": True}),
}


@register("diffusers")
class DiffusersGenerator(ImageGenerator):
    def __init__(
        self,
        model_id: str,
        quantization: str | None = None,
        quantize_components: list[str] | None = None,
        torch_dtype: str = "bfloat16",
        device: str = "cuda",
        cpu_offload: bool = False,
        num_inference_steps: int | None = None,
        guidance_scale: float | None = None,
        local_files_only: bool = False,
    ) -> None:
        if quantization not in (None, *_QUANT_BACKENDS):
            raise ValueError(f"quantization 은 {list(_QUANT_BACKENDS)} 또는 null 이어야 합니다: {quantization!r}")
        self.model_id = model_id
        self.quantization = quantization
        self.quantize_components = list(quantize_components or ["transformer", "text_encoder"])
        self.torch_dtype = torch_dtype
        self.device = device
        self.cpu_offload = cpu_offload
        self.num_inference_steps = num_inference_steps
        self.guidance_scale = guidance_scale
        self.local_files_only = local_files_only
        self._pipe: Any = None

    def generate(self, request: ImageRequest) -> GenerationResult:
        import torch

        pipe = self._load()
        seed = request.seed if request.seed is not None else random.randint(0, 2**31 - 1)
        wanted: dict[str, Any] = {
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt or None,
            "width": request.width,
            "height": request.height,
            "num_images_per_prompt": max(1, request.num_images),
            "num_inference_steps": self.num_inference_steps,
            "guidance_scale": self.guidance_scale,
            "generator": torch.Generator(device="cpu").manual_seed(seed),
            **request.extra,
        }
        accepted = set(inspect.signature(pipe.__call__).parameters)
        kwargs = {k: v for k, v in wanted.items() if v is not None and k in accepted}
        ignored = sorted(k for k, v in wanted.items() if v is not None and k not in accepted)

        with torch.inference_mode():
            output = pipe(**kwargs)

        images = []
        for image in output.images:
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            images.append(GeneratedImage(data=buffer.getvalue(), mime_type="image/png"))
        return GenerationResult(
            images=images,
            model=self.model_id,
            metadata={
                "seed": seed,
                "pipeline": type(pipe).__name__,
                "quantization": self.quantization,
                "num_inference_steps": kwargs.get("num_inference_steps"),
                "guidance_scale": kwargs.get("guidance_scale"),
                "ignored": ignored,
                "gpu_peak_memory_gb": _peak_memory_gb(),
            },
        )

    def close(self) -> None:
        if self._pipe is None:
            return
        self._pipe = None
        try:
            import gc

            import torch

            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def _load(self) -> Any:
        if self._pipe is not None:
            return self._pipe
        try:
            import torch
            from diffusers import DiffusionPipeline
        except ImportError as exc:
            raise RuntimeError(
                "diffusers / torch 가 설치돼 있지 않습니다. pip install -r requirements-gpu.txt"
            ) from exc
        if self.device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA GPU 를 쓸 수 없습니다. CUDA 용 torch 가 설치됐는지 확인하세요 (README 의 GPU 설치)."
            )

        dtype = getattr(torch, self.torch_dtype)
        options: dict[str, Any] = {"torch_dtype": dtype, "local_files_only": self.local_files_only}
        if self.quantization:
            from diffusers.quantizers import PipelineQuantizationConfig

            backend, kwargs = _QUANT_BACKENDS[self.quantization]
            if self.quantization == "nf4":
                kwargs = {**kwargs, "bnb_4bit_compute_dtype": dtype}
            options["quantization_config"] = PipelineQuantizationConfig(
                quant_backend=backend,
                quant_kwargs=kwargs,
                components_to_quantize=self.quantize_components,
            )

        pipe = DiffusionPipeline.from_pretrained(self.model_id, **options)
        if self.cpu_offload:
            pipe.enable_model_cpu_offload()
        else:
            pipe.to(self.device)
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        self._pipe = pipe
        return pipe


def _peak_memory_gb() -> float | None:
    try:
        import torch

        if torch.cuda.is_available():
            return round(torch.cuda.max_memory_allocated() / 1024**3, 2)
    except ImportError:
        pass
    return None
