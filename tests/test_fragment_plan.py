import copy
import unittest

import numpy as np

from reconstruction_probe.fragment_plan import compile_fragment_plan


class FragmentPlanTests(unittest.TestCase):
    def plan(self):
        parent=np.array([[0.,-1,0,100],[1,0,0,50],[0,0,1,0],[0,0,0,1]])
        child=np.eye(4);child[0,3]=10
        return dict(format_version=1,unit='mm',scan_id='A',decoded_index_sha256='pinned-index',decision='explicit exploratory test',fragments=[
            dict(fragment_id=4,parent_fragment_id=None,frame_ids=[0],transform_to_parent_mm=parent.tolist()),
            dict(fragment_id=8,parent_fragment_id=4,frame_ids=[2**40],transform_to_parent_mm=child.tolist())])

    def test_parent_composition_and_full_vendor_frame_ids_are_preserved(self):
        plan=self.plan();compiled=compile_fragment_plan(plan,'A','pinned-index',[0,2**40])
        np.testing.assert_allclose(compiled['corrections'][8][:3,3],[100,60,0])
        self.assertEqual(compiled['selected_frame_ids'],[0,2**40])
        self.assertEqual({key.frame_id:value for key,value in compiled['ownership'].items()},{0:4,2**40:8})

    def test_cycles_absent_parents_and_duplicate_ownership_are_rejected(self):
        for kind in ['cycle','missing_parent','duplicate_frame','duplicate_fragment','improper']:
            p=self.plan()
            if kind=='cycle':p['fragments'][0]['parent_fragment_id']=8
            if kind=='missing_parent':p['fragments'][1]['parent_fragment_id']=99
            if kind=='duplicate_frame':p['fragments'][1]['frame_ids']=[0]
            if kind=='duplicate_fragment':p['fragments'][1]['fragment_id']=4
            if kind=='improper':p['fragments'][1]['transform_to_parent_mm'][0][0]=-1
            with self.assertRaises(ValueError,msg=kind):compile_fragment_plan(p,'A','pinned-index',[0,2**40])

    def test_stale_index_unknown_frame_or_missing_decision_cannot_be_applied(self):
        with self.assertRaisesRegex(ValueError,'revision'):compile_fragment_plan(self.plan(),'A','another-index',[0,2**40])
        with self.assertRaisesRegex(ValueError,'source frame'):compile_fragment_plan(self.plan(),'A','pinned-index',[0])
        plan=copy.deepcopy(self.plan());plan['decision']=''
        with self.assertRaisesRegex(ValueError,'decision'):compile_fragment_plan(plan,'A','pinned-index',[0,2**40])


if __name__=='__main__':unittest.main()
