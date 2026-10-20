"""Update generated workbench presentation while preserving embedded identities."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import re
from reconstruction_probe.offline import file_sha256


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--workspace',type=Path,default=Path(__file__).resolve().parents[1]);args=parser.parse_args();root=args.workspace.resolve();assets=root/'web/landmark-workbench'
    template=(assets/'index.html').read_text(encoding='utf-8');updated=[]
    for parent in [root/'reports/range2-study-20261018',root/'reports/pointcloud-scale-20261019']:
        for path in sorted(parent.rglob('*.html')):
            if 'workbench' not in path.name:continue
            old=path.read_text(encoding='utf-8');match=re.search(r'<script id="alignment-data" type="application/json">(.*?)</script>',old,re.S)
            if not match:continue
            payload=json.loads(match[1]);before=file_sha256(path)
            page=template.replace('__DATA__',match[1],1)
            for marker,name in [('__MATH__','registration_math.js'),('__RASTER__','point_raster.js'),('__APP__','app.js')]:page=page.replace(marker,(assets/name).read_text(encoding='utf-8'),1)
            newmatch=re.search(r'<script id="alignment-data" type="application/json">(.*?)</script>',page,re.S)
            if json.loads(newmatch[1])!=payload:raise ValueError('Embedded model/session identities changed')
            if old==page:continue
            backup=root/'.cache/workbench-page-backups'/before/(path.name);backup.parent.mkdir(parents=True,exist_ok=True)
            if not backup.exists():backup.write_bytes(path.read_bytes())
            path.write_text(page,encoding='utf-8');updated.append(dict(path=str(path),before_sha256=before,after_sha256=file_sha256(path),backup=str(backup),embedded_data_unchanged=True))
    out=root/'reports/web-studio';out.mkdir(exist_ok=True,parents=True)
    (out/'workbench-upgrade.json').write_text(json.dumps(dict(updated_at_utc=datetime.now(timezone.utc).isoformat(),pages=updated),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(updated=len(updated),identities_preserved=True)),flush=True)

if __name__=='__main__':main()
