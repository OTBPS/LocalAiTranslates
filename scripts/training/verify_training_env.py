"""Fail fast when the local CUDA/QLoRA environment is not usable."""

from __future__ import annotations

import json

import bitsandbytes as bnb
import torch


def main() -> int:
    if not torch.cuda.is_available():
        raise RuntimeError("PyTorch cannot access CUDA")
    device = torch.device("cuda:0")
    properties = torch.cuda.get_device_properties(device)

    left = torch.randn(512, 512, device=device, dtype=torch.bfloat16, requires_grad=True)
    right = torch.randn(512, 512, device=device, dtype=torch.bfloat16)
    loss = (left @ right).float().square().mean()
    loss.backward()
    if left.grad is None or not torch.isfinite(left.grad).all():
        raise RuntimeError("CUDA backward pass produced an invalid gradient")

    weights = torch.randn(1024, 1024, device=device, dtype=torch.bfloat16)
    quantized, state = bnb.functional.quantize_4bit(weights, quant_type="nf4")
    restored = bnb.functional.dequantize_4bit(quantized, state)
    relative_error = (weights - restored).abs().mean() / weights.abs().mean()
    if relative_error >= 0.2:
        raise RuntimeError(f"NF4 quantization error is unexpectedly high: {relative_error.item()}")

    report = {
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "bitsandbytes": bnb.__version__,
        "device": properties.name,
        "compute_capability": f"{properties.major}.{properties.minor}",
        "vram_gib": round(properties.total_memory / 1024**3, 2),
        "bf16_supported": torch.cuda.is_bf16_supported(),
        "nf4_relative_error": round(relative_error.item(), 6),
        "status": "ok",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
