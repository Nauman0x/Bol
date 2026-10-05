"""`python -m piper.train.export_onnx` using torch's TorchScript-based ONNX exporter.

    python scripts/piper_export_onnx.py --checkpoint X.ckpt --output-file X.onnx

From torch 2.9, torch.onnx.export defaults to the torch.export (dynamo) exporter,
which fails on VITS's stochastic duration predictor
(`assert (discriminant >= 0).all()` in the spline transform). Piper does not pass
dynamo=, so this sets dynamo=False before running Piper's export.
"""

import functools

import torch

torch.onnx.export = functools.partial(torch.onnx.export, dynamo=False)

from piper.train import export_onnx  # noqa: E402  (after the patch)

if __name__ == "__main__":
    export_onnx.main()
