import copy
import unittest
import numpy as np

from reconstruction_probe.landmark_sessions import verify_landmark_session


class LandmarkSessionTests(unittest.TestCase):
    def setUp(self):
        self.source=np.array([[0.,0,500.123456],[20,0,500.2],[0,30,510.3],[10,20,540.]])
        self.matrix=np.array([[0,-1,0,12],[1,0,0,-8],[0,0,1,4],[0,0,0,1]],float)
        self.target=self.source@self.matrix[:3,:3].T+self.matrix[:3,3]
        self.session=dict(format_version=1,unit="mm",kind="manual_landmarks",source=dict(sha256="source"),target=dict(sha256="target"),transform_source_to_target=self.matrix.tolist(),
            point_pairs=[dict(source=dict(id=i,xyz=p.astype(np.float32).astype(float).tolist()),target=dict(id=i,xyz=q.astype(np.float32).astype(float).tolist())) for i,(p,q) in enumerate(zip(self.source,self.target))])

    def verify(self,session):return verify_landmark_session(session,self.source,self.target,"source","target")

    def test_preview_rounding_returns_to_original_precision(self):
        result=self.verify(self.session)
        np.testing.assert_allclose(result["matrix"],self.matrix,atol=1e-10)
        self.assertLess(result["rmse_mm"],1e-10)

    def test_wrong_content_or_original_point_reference_is_rejected(self):
        for mutation in [lambda s:s["source"].update(sha256="wrong"),lambda s:s["point_pairs"][0]["source"].update(xyz=[1.,0.,500.123456]),lambda s:s["point_pairs"][0]["source"].update(id=True)]:
            session=copy.deepcopy(self.session);mutation(session)
            with self.assertRaises(ValueError):self.verify(session)

    def test_valid_rotation_with_the_wrong_translation_cannot_be_silently_applied(self):
        session=copy.deepcopy(self.session);session["transform_source_to_target"][0][3]+=10
        with self.assertRaisesRegex(ValueError,"disagrees"):self.verify(session)

    def test_duplicate_pair_cannot_supply_three_distinct_correspondences(self):
        session=copy.deepcopy(self.session);session["point_pairs"][1]=session["point_pairs"][0]
        with self.assertRaisesRegex(ValueError,"duplicate"):self.verify(session)


if __name__=="__main__":unittest.main()
