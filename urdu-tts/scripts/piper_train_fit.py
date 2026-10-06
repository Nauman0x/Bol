"""`python -m piper.train` without Piper's val_mos checkpoint callback.

    python scripts/piper_train_fit.py fit --data.voice_name ... (same arguments as piper.train)

Piper always adds ModelCheckpoint(monitor="val_mos"). val_mos comes from the
UTMOS predictor, which needs torchaudio, and torchaudio has no release for the
torch version that supports this GPU (RTX 50xx needs torch >= 2.7 with CUDA 12.8+;
torchaudio stops at 2.11). Without val_mos, Lightning raises at the end of the
first epoch instead of skipping the callback. Run with --model.mos_metric none.

The file name keeps `pkill -INT -f piper.train` working as the stop command.
A process started in the background by a non-interactive shell inherits SIGINT
as ignored, and Python then never raises KeyboardInterrupt, so that stop
command did nothing; the handler is restored here so Lightning shuts down cleanly.

After a Ctrl-C, Lightning shuts down gracefully and then exits with code 1, the
same as a crash, so `train.sh auto` restarted training 30 s later. A run stopped
by SIGINT exits with 130 instead, which train.sh treats as "stop".

FREEZE (env var, comma-separated parameter-name prefixes such as
"model_g.enc_p,model_g.dp") keeps those parts of the model fixed. Freezing the
text encoder and duration predictor keeps the base voice's pronunciation and
timing and trains only how the voice sounds; with ~1 hour of noisy data,
training everything garbled pronunciation.

Piper's val_mel checkpoint only rewrites last.ckpt when val_mel improves, so a
resume after a power cut could go back many epochs. A "latest" checkpoint is
also written after every epoch.
"""

import logging
import os
import signal
import sys

from lightning.pytorch.callbacks import ModelCheckpoint
from piper.train import __main__ as piper_train
from piper.train.vits.lightning import VitsModel

_LOGGER = logging.getLogger("piper_train_fit")
_FREEZE = [p.strip() for p in os.environ.get("FREEZE", "").split(",") if p.strip()]
_on_fit_start = VitsModel.on_fit_start


def _on_fit_start_then_freeze(self):
    _on_fit_start(self)  # warmstart (if any) runs first
    frozen = 0
    for name, param in self.named_parameters():
        if any(name.startswith(prefix + ".") for prefix in _FREEZE):
            param.requires_grad_(False)
            frozen += param.numel()
    if _FREEZE:
        if not frozen:
            raise ValueError(f"FREEZE={_FREEZE} matched no parameters")
        _LOGGER.info("Froze %.1fM parameters under %s", frozen / 1e6, _FREEZE)


VitsModel.on_fit_start = _on_fit_start_then_freeze

_interrupted = False


def _on_sigint(signum, frame):
    global _interrupted
    _interrupted = True
    signal.default_int_handler(signum, frame)


signal.signal(signal.SIGINT, _on_sigint)

piper_train._DEFAULT_CALLBACKS[:] = [
    cb for cb in piper_train._DEFAULT_CALLBACKS if getattr(cb, "monitor", None) != "val_mos"
] + [ModelCheckpoint(filename="latest", monitor=None, save_top_k=1, every_n_epochs=1)]

if __name__ == "__main__":
    try:
        piper_train.main()
    except SystemExit:
        if _interrupted:
            sys.exit(130)
        raise
    if _interrupted:
        sys.exit(130)
