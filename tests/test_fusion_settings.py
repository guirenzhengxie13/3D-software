import copy
import json
import unittest
from unittest.mock import patch

import test_web_fragments as fixture
from reconstruction_probe.fusion_settings import DEFAULT_FUSION_SETTINGS,fusion_settings
from reconstruction_probe.offline import file_sha256


class FusionSettingsTests(unittest.TestCase):
    def test_defaults_are_backward_compatible_and_not_shared_mutable(self):
        a=fusion_settings();a['voxel_mm']=1.;self.assertEqual(fusion_settings(),DEFAULT_FUSION_SETTINGS)
        self.assertEqual(fusion_settings(dict(voxel_mm=.8,truncation_mm=3.2,edge_threshold_mm=3,weight_threshold=2)),dict(voxel_mm=.8,truncation_mm=3.2,edge_threshold_mm=3.,weight_threshold=2.))

    def test_nonfinite_boolean_unknown_and_inconsistent_ranges_are_rejected(self):
        for patch_values in [dict(voxel_mm=True),dict(voxel_mm='0.6'),dict(voxel_mm=.1),dict(truncation_mm=float('nan')),dict(truncation_mm=float('inf')),dict(truncation_mm=.6),dict(truncation_mm=10),dict(weight_threshold=0),dict(command='run')]:
            with self.subTest(values=patch_values),self.assertRaises(ValueError):fusion_settings({**DEFAULT_FUSION_SETTINGS,**patch_values})

    def test_review_plan_and_execution_pin_same_settings_and_disallow_overrides(self):
        f=fixture.WebFragmentEditorTests();f.setUp();self.addCleanup(f.doCleanups);settings=dict(voxel_mm=.8,truncation_mm=3.2,edge_threshold_mm=3.,weight_threshold=2.)
        review=f.studio.fragments.preview({**f.request,'fusion_parameters':settings});folder=f.studio.fragments.reviews/review['id'];plan=json.loads((folder/'fragment-plan.json').read_text(encoding='utf-8'))
        self.assertEqual(review['fusion_parameters'],settings);self.assertEqual(plan['fusion_parameters'],settings)
        f.studio.fragments.load_review(review['id'],review['plan_sha256'],review['review_sha256'])
        with self.assertRaises(ValueError):f.studio.start_job({**f.start_request(review),'fusion_parameters':DEFAULT_FUSION_SETTINGS})
        record=json.loads((folder/'review.json').read_text(encoding='utf-8'));record['fusion_parameters']=DEFAULT_FUSION_SETTINGS;(folder/'review.json').write_text(json.dumps(record),encoding='utf-8')
        with self.assertRaises(ValueError):f.studio.fragments.load_review(review['id'],review['plan_sha256'],file_sha256(folder/'review.json'))

    def test_job_reads_only_hash_pinned_review_parameters(self):
        from types import SimpleNamespace
        from pathlib import Path
        f=fixture.WebFragmentEditorTests();f.setUp();self.addCleanup(f.doCleanups);settings=dict(voxel_mm=.8,truncation_mm=3.2,edge_threshold_mm=3.,weight_threshold=3.)
        review=f.studio.fragments.preview({**f.request,'fusion_parameters':settings})
        with patch('reconstruction_probe.web_studio.threading',SimpleNamespace(Thread=lambda **kwargs:SimpleNamespace(start=lambda:None))):job=f.studio.start_job(f.start_request(review))
        self.assertEqual(job['reviewed_fusion_parameters'],settings)
        path=Path(job['folder'])/'review-original.json';path.write_bytes(path.read_bytes()+b' ');loaded=f.studio.job(job['id'])
        self.assertNotIn('reviewed_fusion_parameters',loaded);self.assertIn('review_parameters_unavailable',loaded)

    def test_invalid_settings_do_not_create_review_artifacts(self):
        f=fixture.WebFragmentEditorTests();f.setUp();self.addCleanup(f.doCleanups)
        with self.assertRaises(ValueError):f.studio.fragments.preview({**f.request,'fusion_parameters':{'voxel_mm':.8}})
        self.assertFalse(f.studio.fragments.reviews.exists())

    def test_plan_swap_between_hash_and_load_is_rejected_before_execution(self):
        from reconstruction_probe.fragment_plan import load_fragment_inputs
        f=fixture.WebFragmentEditorTests();f.setUp();self.addCleanup(f.doCleanups);review=f.studio.fragments.preview(f.request);folder=f.studio.fragments.reviews/review['id'];path=folder/'fragment-plan.json';original=path.read_bytes()
        def changed(*args):
            plan=json.loads(original);plan['fusion_parameters']=dict(voxel_mm=.8,truncation_mm=3.2,edge_threshold_mm=3.,weight_threshold=3.);path.write_text(json.dumps(plan),encoding='utf-8');return load_fragment_inputs(*args)
        with patch('reconstruction_probe.web_fragments.load_fragment_inputs',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'加载期间'):f.studio.fragments.load_review(review['id'],review['plan_sha256'],review['review_sha256'])
        self.assertEqual(len(f.studio.jobs),1)


if __name__=='__main__':unittest.main()
