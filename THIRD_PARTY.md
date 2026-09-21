# Third-party components

The application dynamically links the unmodified PySide6/Qt libraries. Qt and PySide6 are available under LGPLv3/GPLv3/commercial terms. Users may replace compatible shared libraries and debug modifications as allowed by LGPLv3. Source and notices: https://code.qt.io/ and https://www.qt.io/licensing/open-source-lgpl-obligations

Qwen3-14B: Apache-2.0, https://huggingface.co/Qwen/Qwen3-14B-GGUF (model LICENSE is downloaded beside the weights).

Qwen3-8B: Apache-2.0, https://huggingface.co/Qwen/Qwen3-8B-GGUF (model LICENSE is downloaded beside the weights).

Qwen3-4B-Instruct-2507: Apache-2.0 base model from https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507. The selectable Q8_0 GGUF artifact is distributed by Unsloth at https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF.

PaddleOCR and PaddlePaddle: Apache-2.0, https://github.com/PaddlePaddle/PaddleOCR and https://github.com/PaddlePaddle/Paddle

llama.cpp: MIT, https://github.com/ggml-org/llama.cpp

OpenCV: Apache-2.0, https://github.com/opencv/opencv

NVIDIA CUDA runtime, cuDNN, cuBLAS, cuFFT, cuRAND, cuSOLVER, cuSPARSE and nvJitLink: NVIDIA CUDA Toolkit and cuDNN licenses, https://docs.nvidia.com/cuda/eula/index.html and https://docs.nvidia.com/deeplearning/cudnn/latest/reference/eula.html

Python: PSF license, https://docs.python.org/3/license.html

Dependency license files are retained in the bundled package metadata. Build tool versions are captured in requirements-lock.txt. The model manifest records weight checksums and the runtime release.json records official binary checksums.
