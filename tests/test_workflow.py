import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from reconstruction_probe.offline import file_sha256
from reconstruction_probe.workflow import run_workflow, validate_plan
from reconstruction_probe.multi_scan import bound_evidence_path


class OfflineWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='offline-workflow-test-')
        self.workspace=Path(self.temporary.name)/'workspace with spaces';self.workspace.mkdir();(self.workspace/'scripts').mkdir()
        for script in ['analyze_multi_scan_fusion.py','trace_multi_scan_surface_point.py','export_pointcloud_region.py','build_ply_spatial_index.py']:
            (self.workspace/'scripts'/script).write_text('# test stub\n',encoding='utf-8')
        self.fusion=self.workspace/'existing fusion';self.fusion.mkdir();(self.fusion/'summary.json').write_text('{}',encoding='utf-8')
        self.plan=dict(format_version=1,input_sha256={str(self.fusion/'summary.json'):file_sha256(self.fusion/'summary.json')},nodes=[
            dict(id='evidence',tool='multi_scan.evidence',parameters=dict(fusion=str(self.fusion),max_points=100)),
            dict(id='trace',tool='multi_scan.trace',parameters=dict(fusion=str(self.fusion),evidence=dict(node='evidence',path='.'),category='source_only'))])
        self.out=self.workspace/'reports'/'test-run';self.calls=[]

    def tearDown(self):
        self.temporary.cleanup()

    def successful_tool(self,command,**kwargs):
        self.calls.append((command,kwargs));destination=Path(next(a.removeprefix('--out=') for a in command if a.startswith('--out=')))
        destination.mkdir();(destination/'summary.json').write_text(json.dumps(dict(tool=Path(command[1]).name)),encoding='utf-8')
        return SimpleNamespace(returncode=0)

    def test_output_references_use_recorded_argument_vectors_with_spaces(self):
        with patch('reconstruction_probe.workflow.subprocess.run',side_effect=self.successful_tool):
            state=run_workflow(self.plan,self.workspace,self.out)
        self.assertEqual(state['status'],'completed');self.assertEqual(len(self.calls),2)
        self.assertFalse(self.calls[0][1]['shell']);self.assertEqual(self.calls[0][1]['env']['PYTHONIOENCODING'],'utf-8')
        self.assertIn('--evidence='+str(self.out/'nodes'/'evidence'),self.calls[1][0])
        self.assertEqual(state['nodes'][0]['output_sha256']['summary.json'],file_sha256(self.out/'nodes/evidence/summary.json'))
        self.assertFalse(state['model_service_connected'])

    def test_changed_dependency_fails_before_second_tool_and_preserves_first_record(self):
        def observe(event):
            if event['event']=='operation_finished' and event['id']=='evidence':
                (self.out/'nodes/evidence/summary.json').write_text('changed',encoding='utf-8')
        with patch('reconstruction_probe.workflow.subprocess.run',side_effect=self.successful_tool):
            state=run_workflow(self.plan,self.workspace,self.out,on_event=observe)
        self.assertEqual(state['status'],'failed');self.assertEqual(len(self.calls),1)
        self.assertIn('Dependency outputs changed',state['nodes'][1]['error'])
        self.assertNotEqual(state['nodes'][0]['output_sha256']['summary.json'],file_sha256(self.out/'nodes/evidence/summary.json'))

    def test_cancel_after_one_operation_keeps_its_outputs_and_skips_next(self):
        cancel=self.workspace/'cancel.request'
        def observe(event):
            if event['event']=='operation_finished':cancel.touch()
        with patch('reconstruction_probe.workflow.subprocess.run',side_effect=self.successful_tool):
            state=run_workflow(self.plan,self.workspace,self.out,cancel_file=cancel,on_event=observe)
        self.assertEqual(state['status'],'cancelled_between_operations');self.assertEqual(state['not_run_operations'],['trace'])
        self.assertTrue((self.out/'nodes/evidence/summary.json').is_file());self.assertEqual(len(self.calls),1)

    def test_failure_stops_later_tools_without_changing_pinned_input(self):
        original=(self.fusion/'summary.json').read_bytes()
        with patch('reconstruction_probe.workflow.subprocess.run',return_value=SimpleNamespace(returncode=2)):
            state=run_workflow(self.plan,self.workspace,self.out)
        self.assertEqual(state['status'],'failed');self.assertEqual(state['nodes'][0]['exit_code'],2)
        self.assertEqual(state['not_run_operations'],['trace']);self.assertEqual((self.fusion/'summary.json').read_bytes(),original)

    def test_stale_pin_and_unsafe_recipes_are_rejected_before_output(self):
        (self.fusion/'summary.json').write_text('changed',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Pinned input changed'):
            run_workflow(self.plan,self.workspace,self.out)
        self.assertFalse(self.out.exists());self.plan['input_sha256']={}
        for change in ['unknown_tool','extra_parameter','parent_escape','forward_reference','boolean_samples']:
            plan=copy.deepcopy(self.plan)
            if change=='unknown_tool':plan['nodes'][0]['tool']='run_arbitrary_shell'
            if change=='extra_parameter':plan['nodes'][0]['parameters']['command']='echo bad'
            if change=='parent_escape':plan['nodes'][1]['parameters']['evidence']['path']='../outside'
            if change=='forward_reference':plan['nodes'][0]['parameters']['fusion']=dict(node='trace',path='.')
            if change=='boolean_samples':plan['nodes'][0]['parameters']['max_points']=True
            with self.assertRaises(ValueError,msg=change):validate_plan(plan,self.workspace)
        with self.assertRaises(ValueError):run_workflow(self.plan,self.workspace,self.workspace/'outside-reports')

    def test_surface_evidence_cannot_be_reused_with_another_fusion_revision(self):
        evidence=self.workspace/'evidence';evidence.mkdir();meta=evidence/'summary.json'
        meta.write_text(json.dumps(dict(input_sha256={str(self.fusion/'summary.json'):file_sha256(self.fusion/'summary.json')})),encoding='utf-8')
        self.assertEqual(bound_evidence_path(self.fusion,evidence),evidence/'joint_raw_depth-evidence.npz')
        (self.fusion/'summary.json').write_text('different revision',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'different fusion'):
            bound_evidence_path(self.fusion,evidence)

    def test_original_vertex_lists_are_passed_as_separate_checked_arguments(self):
        plan=dict(format_version=1,nodes=[dict(id='region',tool='cloud.region',parameters=dict(index=str(self.fusion),vertex_ids=[12,98765],radius_mm=5.))])
        with patch('reconstruction_probe.workflow.subprocess.run',side_effect=self.successful_tool):state=run_workflow(plan,self.workspace,self.out)
        self.assertEqual(state['status'],'completed');self.assertIn('--vertex-id=12',self.calls[0][0]);self.assertIn('--vertex-id=98765',self.calls[0][0])
        for ids in [[True],[1,1],[-1],[2**32]]:
            plan['nodes'][0]['parameters']['vertex_ids']=ids
            with self.assertRaises(ValueError):validate_plan(plan,self.workspace)
        plan['nodes'][0]['parameters']['vertex_ids']=[1];plan['nodes'][0]['parameters']['radius_mm']=float('nan')
        with self.assertRaises(ValueError):validate_plan(plan,self.workspace)


if __name__=='__main__':unittest.main()
