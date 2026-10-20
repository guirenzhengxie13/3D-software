"""Archive observed capture/rotation metadata without inventing turntable telemetry."""

import argparse
import json
from pathlib import Path


def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();study=args.study.resolve();rows=[]
    for path in sorted((study/'decoded').glob('*/index.json')):
        index=read(path);scan=index.get('manifest_scan',{});manifest_path=Path(index['source_directory'])/index['source_manifest'];manifest=read(manifest_path)
        rows.append(dict(scan_id=index['scan_id'],saved_depth_records=index['status']['depth_decoded'],
            saved_pose_records=index['status']['poses_parsed'],optimized_pose_records=index['status']['optimized_poses_parsed'],
            manifest_vf_count_unverified_semantics=scan.get('vf_count'),rotate_state_unverified_semantics=scan.get('rotate_state'),
            view_rotate_angle_unverified_semantics=scan.get('view_rotate_angle'),support_gyro_saved_setting=scan.get('support_gyro'),
            per_frame_known_capture_timestamps=sum(f.get('capture_timestamp') is not None for f in index['frames']),
            project_create_time=manifest.get('create_time'),project_edit_time=manifest.get('edit_time'),
            settings_template_timestamp=manifest.get('param_template',{}).get('timeStamp'),
            actual_dataset_tables=index['table_counts']))
    report=dict(status='observed_metadata_not_turntable_encoder_log',projects=len(rows),
        confirmed_per_frame_turntable_angle_channel=False,confirmed_per_frame_capture_clock=False,
        all_physical_sensor_frames_preserved='not established',rows=rows,
        findings=['rotate_state is True in all supplied projects, including three with no saved depths; it does not provide a per-frame turntable trajectory.',
          'view_rotate_angle is one project-level value (0 or 90 here), not a sequence of per-frame physical encoder angles. Its vendor semantics are not verified.',
          'vf_count differs from decoded depth counts in many projects. It is not assumed to equal an exact UI frame counter or a physical camera frame count.',
          'Project creation/edit times and settings-template timestamps are not per-frame capture times.',
          'One scan saves 275 depth records but only 193 optimized poses. Saving depth and retaining optimized pose are distinct stages.',
          'Current files do not establish whether sensor frames during a user-observed non-incrementing UI interval were persisted. A controlled acquisition is needed to link behavior to saved records.',
          'Missing sequence-like values in opaque frame metadata are not sufficient evidence of dropped physical camera frames.'])
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(projects=len(rows),known_frame_timestamps=sum(r['per_frame_known_capture_timestamps'] for r in rows),turntable_telemetry_confirmed=False)))


if __name__=='__main__':main()
