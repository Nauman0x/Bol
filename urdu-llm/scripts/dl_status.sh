#!/usr/bin/env bash
# dl_status.sh : show size of each model file / partial, and growth over 30 s.
cd "$(dirname "$0")/.."
snap() { find models \( -name '*.incomplete' -o -name '*.gguf' \) -printf '%s %f\n' | sort -k2; }
a=$(snap); sleep 30; b=$(snap)
echo "$b" | cut -c1-80
sa=$(echo "$a" | awk '{s+=$1} END{print s+0}'); sb=$(echo "$b" | awk '{s+=$1} END{print s+0}')
echo "speed: $(( (sb-sa)/30/1024 )) KB/s; total $(( sb/1024/1024 )) MB"
ls dl_done.flag 2>&1; pgrep -af 'hf download' | grep -v pgrep | wc -l
