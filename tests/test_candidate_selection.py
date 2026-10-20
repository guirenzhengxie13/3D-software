import unittest
import numpy as np

from reconstruction_probe.candidate_selection import hypothesis_rms_displacement,distinct_hypothesis_indices


class AlignmentHypothesisTests(unittest.TestCase):
    def test_object_displacement_is_invariant_to_a_common_coordinate_rebase(self):
        points=np.array([[10,0,500],[30,0,500],[20,20,520]],float)
        first=np.eye(4);second=np.array([[0,-1,0,20],[1,0,0,-20],[0,0,1,0],[0,0,0,1]],float)
        base=np.array([[1,0,0,300],[0,0,-1,800],[0,1,0,-40],[0,0,0,1]],float)
        moved=points@base[:3,:3].T+base[:3,3]
        original=hypothesis_rms_displacement(first,second,points)
        changed=hypothesis_rms_displacement(base@first@np.linalg.inv(base),base@second@np.linalg.inv(base),moved)
        self.assertAlmostEqual(original,changed,places=10)

    def test_nearby_repeats_do_not_crowd_out_an_opposite_orientation(self):
        points=np.array([[-10,0,0],[10,0,0],[0,20,0]],float)
        same=np.eye(4);near=same.copy();near[0,3]=.2
        flipped=np.diag([-1.,-1.,1.,1.]);repeat=flipped.copy();repeat[1,3]=.1
        self.assertEqual(distinct_hypothesis_indices([same,near,flipped,repeat],points,maximum=3,minimum_rms=2),[0,2])

    def test_nonrigid_or_nonfinite_hypotheses_cannot_enter_comparison(self):
        points=np.array([[0.,0.,1.]])
        for bad in [np.diag([2.,1.,1.,1.]),np.full((4,4),np.nan)]:
            with self.assertRaises(ValueError):
                hypothesis_rms_displacement(np.eye(4),bad,points)


if __name__=="__main__":unittest.main()
