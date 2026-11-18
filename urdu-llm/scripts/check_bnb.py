"""check_bnb.py : confirm 4-bit bitsandbytes works on this GPU (sm_120) inside .venv-train."""
import torch, bitsandbytes as bnb
l = bnb.nn.Linear4bit(256, 256, quant_type="nf4", compute_dtype=torch.bfloat16).cuda()
y = l(torch.randn(2, 256, device="cuda", dtype=torch.bfloat16))
print("bnb", bnb.__version__, "cap", torch.cuda.get_device_capability(), "out", tuple(y.shape), "finite", bool(torch.isfinite(y).all()))
