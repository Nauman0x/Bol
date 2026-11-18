"""inspect_gguf.py <gguf> : print chat template, BOS/EOS/EOT ids and the stop-token candidates from GGUF metadata."""
import sys
from gguf import GGUFReader
r = GGUFReader(sys.argv[1])
def val(k):
    f = r.fields.get(k)
    if f is None: return None
    v = f.contents() if hasattr(f, "contents") else None
    return v
for k in ["tokenizer.ggml.model","tokenizer.ggml.eos_token_id","tokenizer.ggml.bos_token_id","tokenizer.ggml.eot_token_id","tokenizer.ggml.padding_token_id"]:
    print(k, val(k))
t = val("tokenizer.chat_template"); print("template:", (t or "")[:700])
