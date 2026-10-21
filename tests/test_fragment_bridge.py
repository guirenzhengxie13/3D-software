import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from reconstruction_probe.fragment_bridge import build_fragment_plan
from reconstruction_probe.fragment_plan import compile_fragment_plan
from reconstruction_probe.lod_cache import write_vertex_preview_ply
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import PathMapper
from reconstruction_probe.workflow import validate_plan


class FragmentBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.mapper=PathMapper(self.root)
        self.decoded=self.root/'decoded';self.decoded.mkdir()
        self.alignment=self.root/'alignment';self.alignment.mkdir()
        self.index=self.decoded/'index.json'
        self.save(self.index,dict(scan_id='scan_A',frames=[dict(id=x) for x in [0,8,2**40]],
            intrinsics=dict(Pl=dict(width=2,height=2,K=[[2,0,1],[0,2,1],[0,0,1]]))))
        for rid in [0,8,2**40]:
            folder=self.decoded/f'frame_{rid:010d}';folder.mkdir()
            np.savez_compressed(folder/'frame.npz',depth_mm=np.ones((2,2),np.float32)*100,
                                rgba=np.full((4,4),100,np.uint8))
            np.save(folder/'pose_optimized.npy',np.eye(4))
        xyz=np.array([[0,0,100],[10,0,100],[0,10,100],[10,10,100]],np.float32)
        self.matrix=np.eye(4);self.matrix[0,3]=10
        self.models={}
        for side,points in [('source',xyz),('target',xyz+[10,0,0])]:
            path=self.root/(side+'.ply');write_vertex_preview_ply(path,points,np.full((4,3),100,np.uint8),np.arange(4))
            self.models[side]=path
        self.record=self.root/'candidate.json';self.save(self.record,dict(candidates=[dict(label='frozen-geometric',transform=self.matrix.tolist())]))
        self.session=dict(format_version=1,unit='mm',kind='existing_candidate',
            source=dict(path=str(self.models['source']),sha256=file_sha256(self.models['source'])),
            target=dict(path=str(self.models['target']),sha256=file_sha256(self.models['target'])),
            candidate_label='frozen-geometric',candidate_reference=dict(path=str(self.record),sha256=file_sha256(self.record)),
            transform_source_to_target=self.matrix.tolist())
        self.session_path=self.root/'session.json';self.save(self.session_path,self.session)
        self.save(self.alignment/'session-original.json',self.session)
        self.summary=self.alignment/'summary.json'
        self.report=dict(status='reviewable_candidates_not_automatically_promoted',landmark_validation=dict(kind='existing_candidate'),
            input_sha256={str(p):file_sha256(p) for p in [*self.models.values(),self.session_path,self.record]},
            candidates=[dict(label='selected_frozen-geometric',transform=self.matrix.tolist())])
        self.save(self.summary,self.report)
        self.binding=dict(format_version=1,unit='mm',scan_id='scan_A',decoded_index_sha256=file_sha256(self.index),
            alignment_summary_sha256=file_sha256(self.summary),decision='Explicit synthetic component contract test',
            selection_roi_original_scan_mm=[[-5,-5,90],[30,30,110]],
            source=dict(path=str(self.models['source']),sha256=file_sha256(self.models['source']),frame_ids=[2**40],coordinate_frame='saved_scan_mm',basis='Known fixture in saved coordinates'),
            target=dict(path=str(self.models['target']),sha256=file_sha256(self.models['target']),frame_ids=[0],coordinate_frame='saved_scan_mm',basis='Known fixture in saved coordinates'))
        self.binding_path=self.root/'binding.json'

    def save(self,path,value):path.write_text(json.dumps(value),encoding='utf-8')

    def build(self,candidate='selected_frozen-geometric'):
        self.save(self.binding_path,self.binding)
        return build_fragment_plan(self.decoded,self.binding_path,self.alignment,candidate,self.mapper)

    def test_original_ids_pose_composition_roi_and_content_pins_survive_bridge(self):
        before={p:p.read_bytes() for p in [self.index,self.summary,self.record,self.session_path]}
        plan,audit=self.build();compiled=compile_fragment_plan(plan,'scan_A',file_sha256(self.index),[0,8,2**40])
        self.assertEqual(compiled['selected_frame_ids'],[0,2**40]);self.assertEqual(audit['unselected_frames'],1)
        self.assertEqual(audit['valid_saved_depth_observations_before_roi'],8)
        np.testing.assert_array_equal(compiled['corrections'][0],np.eye(4));np.testing.assert_array_equal(compiled['corrections'][1],self.matrix)
        self.assertEqual(plan['selection_roi_original_scan_mm'],self.binding['selection_roi_original_scan_mm'])
        for rid in [0,2**40]:
            for name in ['frame.npz','pose_optimized.npy']:
                p=self.decoded/f'frame_{rid:010d}'/name;self.assertEqual(plan['input_sha256'][str(p)],file_sha256(p))
        for p,data in before.items():self.assertEqual(p.read_bytes(),data)

    def test_index_models_candidate_and_verified_summary_are_not_interchangeable(self):
        mutations=[('index',lambda:setattr(self,'binding',{**self.binding,'decoded_index_sha256':'0'*64})),
            ('scan',lambda:self.binding.update(scan_id='scan_B')),
            ('model',lambda:self.binding['source'].update(sha256='0'*64)),
            ('unpinned',lambda:self.binding.pop('alignment_summary_sha256')),
            ('local_coordinates',lambda:self.binding['source'].update(coordinate_frame='camera_local'))]
        original=copy.deepcopy(self.binding)
        for label,mutate in mutations:
            self.binding=copy.deepcopy(original);mutate()
            with self.subTest(label=label),self.assertRaises(ValueError):self.build()

    def test_duplicate_boolean_unknown_and_cross_fragment_frame_ids_are_rejected(self):
        for ids in [[0],[True],[999],[2**40,2**40],[]]:
            self.binding['source']['frame_ids']=ids
            with self.subTest(ids=ids),self.assertRaises(ValueError):self.build()

    def test_missing_corrupt_depth_color_and_improper_pose_are_rejected(self):
        folder=self.decoded/f'frame_{2**40:010d}';p=folder/'frame.npz';original=p.read_bytes()
        for depth,color in [(np.ones((2,2),np.float32),np.zeros((3,4),np.uint8)),
                            (np.full((2,2),np.nan,np.float32),None),
                            (np.zeros((2,2),np.float32),None)]:
            values=dict(depth_mm=depth)
            if color is not None:values['rgba']=color
            np.savez_compressed(p,**values)
            with self.assertRaises(ValueError):self.build()
        p.write_bytes(original);pose=np.eye(4);pose[0,0]=-1;np.save(folder/'pose_optimized.npy',pose)
        with self.assertRaises(ValueError):self.build()
        (folder/'pose_optimized.npy').unlink()
        with self.assertRaisesRegex(ValueError,'missing'):self.build()

    def test_ambiguous_or_modified_candidate_cannot_enter_raw_frame_fusion(self):
        self.report['candidates']*=2;self.save(self.summary,self.report);self.binding['alignment_summary_sha256']=file_sha256(self.summary)
        with self.assertRaisesRegex(ValueError,'exactly one'):self.build()
        self.report['candidates']=self.report['candidates'][:1];self.report['candidates'][0]['transform'][0][3]=999
        self.save(self.summary,self.report);self.binding['alignment_summary_sha256']=file_sha256(self.summary)
        with self.assertRaisesRegex(ValueError,'disagrees'):self.build()

    def test_manual_original_point_fit_can_bind_the_same_explicit_frames(self):
        points=np.array([[0,0,100],[10,0,100],[0,10,100]],float)
        session=copy.deepcopy(self.session);session['kind']='manual_landmarks'
        session.pop('candidate_label');session.pop('candidate_reference')
        session['point_pairs']=[dict(source=dict(id=i,xyz=p.tolist()),target=dict(id=i,xyz=(p+[10,0,0]).tolist())) for i,p in enumerate(points)]
        self.save(self.session_path,session);self.save(self.alignment/'session-original.json',session)
        self.report['input_sha256'][str(self.session_path)]=file_sha256(self.session_path)
        self.report['landmark_validation']['kind']='manual_landmarks'
        self.report['candidates']=[dict(label='manual_landmarks',transform=self.matrix.tolist())]
        self.save(self.summary,self.report);self.binding['alignment_summary_sha256']=file_sha256(self.summary)
        plan,audit=self.build('manual_landmarks')
        self.assertEqual(audit['landmark_kind'],'manual_landmarks')
        np.testing.assert_allclose(plan['fragments'][1]['transform_to_parent_mm'],self.matrix,atol=1e-10)

    def test_workflow_can_reference_generated_plan_and_request_saved_control(self):
        scripts=self.root/'scripts';scripts.mkdir()
        for name in ['build_fragment_plan_from_alignment.py','reconstruct_fragment_plan.py']:(scripts/name).write_text('# fixture')
        self.save(self.binding_path,self.binding)
        workflow=dict(format_version=1,nodes=[
            dict(id='bind',tool='fragments.plan',parameters=dict(decoded=str(self.decoded),alignment=str(self.alignment),binding=str(self.binding_path),candidate='selected_frozen-geometric')),
            dict(id='fuse',tool='fragments.fuse',parameters=dict(decoded=str(self.decoded),plan=dict(node='bind',path='fragment-plan.json'))),
            dict(id='control',tool='fragments.fuse',parameters=dict(decoded=str(self.decoded),plan=dict(node='bind',path='fragment-plan.json'),saved_control=True))])
        validate_plan(workflow,self.root)
        workflow['nodes'][0]['parameters']['candidate']='--arbitrary command'
        with self.assertRaises(ValueError):validate_plan(workflow,self.root)


if __name__=='__main__':unittest.main()
