#!/usr/bin/env bash
# qalb_template.sh : fetch Qalb's original tokenizer_config.json and print its chat template + eos.
curl -sfL https://huggingface.co/enstazao/Qalb-1.0-8B-Instruct/resolve/main/tokenizer_config.json -o /tmp/qalb_tc.json && python3 -c "
import json; d=json.load(open('/tmp/qalb_tc.json')); print('eos:',d.get('eos_token')); t=d.get('chat_template'); print(t if t else 'NO TEMPLATE')"
