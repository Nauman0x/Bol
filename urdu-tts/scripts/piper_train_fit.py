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
"""

import signal
import sys

from piper.train import __main__ as piper_train

_interrupted = False


def _on_sigint(signum, frame):
    global _interrupted
    _interrupted = True
    signal.default_int_handler(signum, frame)


signal.signal(signal.SIGINT, _on_sigint)

piper_train._DEFAULT_CALLBACKS[:] = [
    cb for cb in piper_train._DEFAULT_CALLBACKS if getattr(cb, "monitor", None) != "val_mos"
]

if __name__ == "__main__":
    try:
        piper_train.main()
    except SystemExit:
        if _interrupted:
            sys.exit(130)
        raise
    if _interrupted:
        sys.exit(130)
