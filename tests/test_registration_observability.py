import unittest

import numpy as np
from scipy.spatial.transform import Rotation

from reconstruction_probe.registration_observability import constraint_jacobian,constraint_spectrum


class ConstraintSpectrumTests(unittest.TestCase):
    def setUp(self):
        rng=np.random.default_rng(551)
        self.points=rng.normal(size=(200,3))*[10,20,30]
        self.normals=rng.normal(size=(200,3));self.normals/=np.linalg.norm(self.normals,axis=1)[:,None]
        self.center=np.array([2.,-4.,7.]);self.length=30.

    def test_jacobian_predicts_finite_rigid_perturbations(self):
        step=np.array([.2,-.3,.4,.5,-.1,.7])*1e-7
        J=constraint_jacobian(self.points,self.normals,self.center,self.length)
        rotated=(self.points-self.center)@Rotation.from_rotvec(step[:3]).as_matrix().T+self.center+self.length*step[3:]
        actual=np.einsum('ij,ij->i',rotated-self.points,self.normals)/self.length
        np.testing.assert_allclose(actual,J@step,atol=1e-14,rtol=1e-6)

    def test_single_plane_has_three_unconstrained_directions(self):
        x,y=np.meshgrid(np.linspace(-10,10,11),np.linspace(-10,10,11));p=np.column_stack((x.ravel(),y.ravel(),np.zeros(x.size)))
        n=np.tile([0.,0.,1.],(len(p),1));s=constraint_spectrum(p,n,[0,0,0],10.)
        self.assertEqual(s['numerical_rank_relative_1e_9'],3)
        np.testing.assert_allclose(np.asarray(s['gram_mean'])[[2,3,4]],0,atol=1e-15)

    def test_perfect_sphere_has_no_first_order_rotational_constraint(self):
        n=self.points/np.linalg.norm(self.points,axis=1)[:,None]
        s=constraint_spectrum(20*n,n,[0,0,0],20.)
        self.assertEqual(s['numerical_rank_relative_1e_9'],3)
        np.testing.assert_allclose(np.asarray(s['gram_mean'])[:3],0,atol=1e-15)

    def test_cylinder_without_caps_has_axial_translation_and_rotation_nulls(self):
        a,z=np.meshgrid(np.linspace(0,2*np.pi,100,endpoint=False),np.linspace(-20,20,20))
        n=np.column_stack((np.cos(a).ravel(),np.sin(a).ravel(),np.zeros(a.size)))
        p=10*n;p[:,2]=z.ravel();s=constraint_spectrum(p,n,[0,0,0],20.)
        self.assertEqual(s['numerical_rank_relative_1e_9'],4)
        np.testing.assert_allclose(np.asarray(s['gram_mean'])[[2,5]],0,atol=1e-15)

    def test_rigid_frame_change_preserves_spectrum(self):
        R=Rotation.from_rotvec([.2,.7,-.8]).as_matrix();shift=np.array([300,-700,500])
        a=constraint_spectrum(self.points,self.normals,self.center,self.length)
        b=constraint_spectrum(self.points@R.T+shift,self.normals@R.T,self.center@R.T+shift,self.length)
        np.testing.assert_allclose(a['eigenvalues'],b['eigenvalues'],atol=1e-13)
        self.assertEqual(a['numerical_rank_relative_1e_9'],6)

    def test_units_normal_signs_and_duplicate_rows_do_not_increase_mean_information(self):
        a=constraint_spectrum(self.points,self.normals,self.center,self.length)
        b=constraint_spectrum(self.points/1000,-self.normals*4,self.center/1000,self.length/1000)
        c=constraint_spectrum(np.tile(self.points,(3,1)),np.tile(self.normals,(3,1)),self.center,self.length)
        np.testing.assert_allclose(a['gram_mean'],b['gram_mean'],atol=1e-13)
        np.testing.assert_allclose(a['gram_mean'],c['gram_mean'],atol=1e-13)

    def test_reject_invalid_geometry_and_normalization(self):
        for p,n,c,L in [(self.points[:4],self.normals[:4],self.center,self.length),
            (self.points,np.zeros_like(self.normals),self.center,self.length),
            (self.points,self.normals,[0,0],self.length),(self.points,self.normals,self.center,0),
            (self.points,self.normals,self.center,float('nan')),
            (self.points+float('inf'),self.normals,self.center,self.length)]:
            with self.assertRaises(ValueError):constraint_spectrum(p,n,c,L)


if __name__=='__main__':unittest.main()
