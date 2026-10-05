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
"""

import signal

from piper.train import __main__ as piper_train

signal.signal(signal.SIGINT, signal.default_int_handler)

piper_train._DEFAULT_CALLBACKS[:] = [
    cb for cb in piper_train._DEFAULT_CALLBACKS if getattr(cb, "monitor", None) != "val_mos"
]

if __name__ == "__main__":
    piper_train.main()
