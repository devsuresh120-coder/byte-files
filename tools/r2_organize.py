"""List the whole R2 bucket (and later copy loose files into per-series/per-episode folders).
env: R2_* secrets; ACTION=list (default) writes queue/r2_listing.txt."""
import os, sys, boto3
s3 = boto3.client('s3', endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
                  aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'], aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'], region_name='auto')
B = os.environ['R2_BUCKET']
import re
ACTION = os.environ.get('ACTION', 'list')
objs = []
for page in s3.get_paginator('list_objects_v2').paginate(Bucket=B):
    objs += [(o['Key'], o['Size']) for o in page.get('Contents', [])]
if ACTION == 'move-mc-root':
    # Merge Conflict's old loose files at the bucket root (epNN.mp4) -> merge-conflict/epNN.mp4 (same layout as blobby/)
    have = {k for k, _ in objs}
    for k, sz in sorted(objs):
        if re.fullmatch(r'ep\d+\.mp4', k):
            new = 'merge-conflict/' + k
            if new in have:
                print('skip (already there):', new); continue
            s3.copy_object(Bucket=B, Key=new, CopySource={'Bucket': B, 'Key': k}, ContentType='video/mp4', MetadataDirective='REPLACE')
            head = s3.head_object(Bucket=B, Key=new)
            if head['ContentLength'] != sz:
                sys.exit(f'size mismatch for {new}; root copy kept')
            s3.delete_object(Bucket=B, Key=k)
            print('moved', k, '->', new)
    objs = []
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=B):
        objs += [(o['Key'], o['Size']) for o in page.get('Contents', [])]
lines = [f"{k}\t{sz}" for k, sz in sorted(objs)]
top = {}
for k, sz in objs:
    t = k.split('/')[0] + '/' if '/' in k else '(root)'
    c, b = top.get(t, (0, 0)); top[t] = (c + 1, b + sz)
summary = [f"{t}: {c} files, {b/1e6:.0f} MB" for t, (c, b) in sorted(top.items())]
open('queue/r2_listing.txt', 'w').write('\n'.join(summary) + '\n\n' + '\n'.join(lines) + '\n')
print('\n'.join(summary))
