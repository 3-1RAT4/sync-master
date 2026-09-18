import sys
import types

import pytest

from sync_master.tools import device


def _fake_torch(monkeypatch, available, name="Fake GPU", hip=None, version="2.13.0+test"):
    torch = types.ModuleType("torch")
    torch.__version__ = version
    torch.cuda = types.SimpleNamespace(is_available=lambda: available, get_device_name=lambda i: name)
    torch.version = types.SimpleNamespace(hip=hip)
    torch.backends = types.SimpleNamespace(cudnn=types.SimpleNamespace(enabled=True))
    monkeypatch.setitem(sys.modules, "torch", torch)
    return torch


def test_torch_device_prefers_the_gpu_when_torch_can_see_one(monkeypatch):
    torch = _fake_torch(monkeypatch, available=True)
    assert device.torch_device() == "cuda"
    assert torch.backends.cudnn.enabled is True  # CUDA build: cuDNN left alone
    _fake_torch(monkeypatch, available=False)
    assert device.torch_device() == "cpu"


def test_torch_device_disables_miopen_on_rocm(monkeypatch):
    torch = _fake_torch(monkeypatch, available=True, hip="7.1")
    assert device.torch_device() == "cuda"
    assert torch.backends.cudnn.enabled is False


def test_gpu_summary_warns_about_the_rocm_navi_override_only_when_relevant(monkeypatch):
    monkeypatch.delenv("HSA_OVERRIDE_GFX_VERSION", raising=False)

    _fake_torch(monkeypatch, available=True, name="AMD Radeon RX 6700 XT", hip="7.1")
    assert "HSA_OVERRIDE_GFX_VERSION=10.3.0" in device.gpu_summary()

    monkeypatch.setenv("HSA_OVERRIDE_GFX_VERSION", "10.3.0")
    assert "HSA_OVERRIDE" not in device.gpu_summary()
    assert "RX 6700 XT" in device.gpu_summary()

    _fake_torch(monkeypatch, available=True, name="NVIDIA thing", hip=None)  # CUDA build: no ROCm advice
    monkeypatch.delenv("HSA_OVERRIDE_GFX_VERSION", raising=False)
    assert "HSA_OVERRIDE" not in device.gpu_summary()

    _fake_torch(monkeypatch, available=False)
    assert "CPU" in device.gpu_summary()


def test_gpu_summary_copes_without_torch(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)  # makes `import torch` raise ImportError
    assert "not installed" in device.gpu_summary()
