"""Where the heavy models run.

Whisper and pyannote both take a torch device. Nothing here is NVIDIA-specific:
under ROCm, PyTorch exposes an AMD card through the same "cuda" device name,
so torch.cuda.is_available() is the right question on either vendor - as long
as the installed torch is the build for the card that's actually present (a
CUDA wheel on an AMD machine silently runs everything on the CPU).
"""

import logging
import os

_logger = logging.getLogger(__name__)


def torch_device() -> str:
    import torch

    if torch.cuda.is_available():
        name = torch.cuda.get_device_name(0)
        if torch.version.hip:
            # MIOpen (ROCm's cuDNN) JIT-compiles some kernels at runtime and the
            # pip wheels don't ship the rocrand headers that needs; pyannote's
            # LSTM trips it ("miopenStatusUnknownError"). With it off, torch's
            # own GPU kernels run instead - measured 7x faster than the CPU
            # on an RX 6700 XT, so nothing of value is lost.
            torch.backends.cudnn.enabled = False
        _logger.info("using GPU: %s", name)
        return "cuda"
    _logger.info("no GPU available to torch (%s); using CPU", torch.__version__)
    return "cpu"


def gpu_summary() -> str:
    """One line for bootstrap: what torch build is installed and what it can see.
    Never runs a kernel - on an unsupported AMD target that would segfault
    rather than raise, which is exactly what the warning is for."""
    try:
        import torch
    except ImportError:
        return "torch not installed (the whisper/diarization extras are what pull it in)"

    build = f"torch {torch.__version__}"
    if not torch.cuda.is_available():
        return f"{build} - no GPU visible; transcription and diarization will use the CPU"

    line = f"{build} - {torch.cuda.get_device_name(0)}"
    if torch.version.hip and not os.environ.get("HSA_OVERRIDE_GFX_VERSION"):
        line += (
            " (ROCm: if this is an RX 6600/6700-class card, set HSA_OVERRIDE_GFX_VERSION=10.3.0"
            " in credentials.env - without it the first kernel segfaults)"
        )
    return line
