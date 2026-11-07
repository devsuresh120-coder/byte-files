#!/bin/bash
# Run from the root of the social-hub checkout: handles ONE upload branch (copy to R2, record links, delete the branch).
set -e
B="$1"
echo "== branch $B"
git fetch -q --depth=1 origin "$B"
git checkout -q FETCH_HEAD -- data/byte-files/_upload
cp data/byte-files/queue/r2.json /tmp/r2.json 2>/dev/null || echo '{}' > /tmp/r2.json
for d in data/byte-files/_upload/*/; do
  F="$(basename "$d")"
  RELEASE_TAG="$F" SRC_DIR="${d%/}" R2_JSON=/tmp/r2.json python ../tools/r2_upload.py
done
git reset -q; rm -rf data/byte-files/_upload
ok=0
for i in 1 2 3 4 5; do
  git pull -q --rebase --autostash
  python3 -c "import json,os; p='data/byte-files/queue/r2.json'; cur=json.load(open(p)) if os.path.exists(p) else {}; cur.update(json.load(open('/tmp/r2.json'))); json.dump(cur, open(p,'w'), indent=1)"
  git add data/byte-files/queue/r2.json
  if git diff --cached --quiet; then ok=1; break; fi
  git commit -qm "byte-files: R2 links ${B#upload/} [skip ci]"
  if git push -q; then ok=1; break; fi
  git reset -q --hard HEAD~1; sleep 5
done
[ $ok -eq 1 ] || { echo "could not save r2.json"; exit 1; }
git push -q origin --delete "$B"
