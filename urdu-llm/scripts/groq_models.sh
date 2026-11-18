#!/usr/bin/env bash
export GROQ_API_KEY=$(grep -E '^GROQ_API_KEY=' /mnt/c/Users/Ehtesham/Bol/bol/.env | head -1 | cut -d= -f2- | tr -d '\r"')
curl -s https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY" | python3 -c "import sys,json; print(sorted(m['id'] for m in json.load(sys.stdin)['data']))"
