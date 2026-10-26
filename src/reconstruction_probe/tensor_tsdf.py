"""A CPU tensor voxel-block TSDF adapter with metric depth and physical RGB."""

import numpy as np
import open3d as o3d


class TensorTSDFVolume:
    def __init__(self, voxel_m, truncation_m, block_count=2000, maximum_active_blocks=12000, weight_threshold=0.):
        if not 0<voxel_m<truncation_m or block_count<1 or weight_threshold<0:
            raise ValueError("Positive voxel and larger truncation required")
        self.voxel_m = voxel_m
        self.multiplier = truncation_m/voxel_m
        self.maximum_active_blocks = maximum_active_blocks
        self.weight_threshold = weight_threshold
        dtype = o3d.core.Dtype.Float32
        self.grid = o3d.t.geometry.VoxelBlockGrid(attr_names=("tsdf","weight","color"),
            attr_dtypes=(dtype,dtype,dtype),attr_channels=((1,),(1,),(3,)),
            voxel_size=voxel_m,block_resolution=16,block_count=block_count,
            device=o3d.core.Device("CPU:0"))

    def integrate(self, rgbd, intrinsic, extrinsic):
        # Legacy RGBD depth has already been normalized to metres. Float input
        # color in the tensor API is normalized; uint8 values must not be fed
        # as 0..255 floats or extracted colors would be off by a factor 255.
        source_depth,source_color = np.asarray(rgbd.depth),np.asarray(rgbd.color)
        if source_color.dtype != np.uint8:
            raise ValueError("Tensor adapter expects legacy RGBD uint8 color")
        if not np.any(source_depth>0):
            return
        depth = o3d.t.geometry.Image(o3d.core.Tensor(np.array(source_depth,dtype=np.float32)))
        color = o3d.t.geometry.Image(o3d.core.Tensor(np.array(source_color,dtype=np.float32)/255.))
        K = o3d.core.Tensor(intrinsic.intrinsic_matrix,o3d.core.Dtype.Float64)
        E = o3d.core.Tensor(np.asarray(extrinsic),o3d.core.Dtype.Float64)
        blocks = self.grid.compute_unique_block_coordinates(depth,K,E,1.,2.,self.multiplier)
        if blocks.num_elements():
            self.grid.integrate(blocks,depth,color,K,E,1.,2.,self.multiplier)
        if self.grid.hashmap().size()>self.maximum_active_blocks:
            raise MemoryError("Tensor TSDF active-block research limit exceeded")

    def extract_point_cloud(self):
        return self.grid.extract_point_cloud(weight_threshold=self.weight_threshold).to_legacy()

    def extract_triangle_mesh(self):
        return self.grid.extract_triangle_mesh(weight_threshold=self.weight_threshold).to_legacy()

    def diagnostics(self):
        return {"active_blocks":self.grid.hashmap().size(),"block_resolution":16,
            "attribute_bytes_per_voxel":20,"device":"CPU:0",
            "active_attribute_bytes":self.grid.hashmap().size()*16**3*20,
            "voxel_m":self.voxel_m,"truncation_voxel_multiplier":self.multiplier,
            "extraction_weight_threshold":self.weight_threshold,"maximum_active_blocks":self.maximum_active_blocks}
