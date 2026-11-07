"""Copy one episode's files to Cloudflare R2 under byte-files/<tag>/ and record their public URLs in queue/r2.json.

Big videos never go into main's history (repo size): Claude pushes a temporary branch upload/<tag> that adds
_upload/<tag>/<files>; the "Copy videos to R2" workflow runs this script, writes r2.json to main and deletes the branch.
queue/schedule.csv refers to the files as r2:<tag>/<file>; the dashboard looks the URL up in queue/r2.json."""
import os, json, glob, hashlib, subprocess, sys
need = ['R2_ACCOUNT_ID', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET', 'R2_PUBLIC_URL']
missing = [k for k in need if not os.environ.get(k)]
if missing:
    sys.exit('Missing R2 secrets: ' + ', '.join(missing))
tag = os.environ.get('RELEASE_TAG', '').strip()
if not tag:
    sys.exit('RELEASE_TAG is empty')
import boto3
dl = os.environ.get('SRC_DIR', f'_upload/{tag}')
if not os.path.isdir(dl):
    sys.exit(f'no folder {dl}')
s3 = boto3.client('s3', endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
                  aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'], aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'], region_name='auto')
types = {'.mp4': 'video/mp4', '.png': 'image/png', '.jpg': 'image/jpeg', '.srt': 'application/x-subrip'}
path = os.environ.get('R2_JSON', 'queue/r2.json')
done = json.load(open(path)) if os.path.exists(path) else {}
base = os.environ['R2_PUBLIC_URL'].rstrip('/')
for f in sorted(glob.glob(f'{dl}/*')):
    name = os.path.basename(f)
    key = f'byte-files/{tag}/{name}'
    sha = hashlib.sha256(open(f, 'rb').read()).hexdigest()[:12]
    s3.upload_file(f, os.environ['R2_BUCKET'], key, ExtraArgs={'ContentType': types.get(os.path.splitext(name)[1], 'application/octet-stream')})
    done[f'r2:{tag}/{name}'] = {'key': key, 'url': f'{base}/{key}', 'sha': sha, 'bytes': os.path.getsize(f)}
    print('uploaded', key)
json.dump(done, open(path, 'w'), indent=1)
