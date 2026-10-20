"""Validate exported correspondence sessions against original point arrays."""

import numpy as np

from .marker_refinement import rigid_alignment
from .poses import _rigid_matrix


def _matrix(value):
    if (not isinstance(value,list) or len(value)!=4 or
            any(not isinstance(row,list) or len(row)!=4 for row in value) or
            any(type(x) not in (int,float) for row in value for x in row)):
        raise ValueError("Expected a numeric 4 by 4 row-major transform")
    matrix=np.asarray(value,dtype="<f8")
    return _rigid_matrix(matrix.tobytes(),0,1e-5).copy()


def verify_landmark_session(session,source,target,source_sha256,target_sha256):
    """Return canonical rigid correction and explicit correspondence diagnostics.

    UI points may be float32 previews. IDs are checked against original arrays
    and the final fit uses original float64 coordinates, without mesh changes.
    """
    if type(session.get("format_version")) is not int or session["format_version"]!=1 or session.get("unit")!="mm":
        raise ValueError("Unsupported session version or unit")
    if session.get("source",{}).get("sha256")!=source_sha256 or session.get("target",{}).get("sha256")!=target_sha256:
        raise ValueError("Source/target content hash mismatch")
    kind=session.get("kind")
    if kind not in ("manual_landmarks","existing_candidate"):
        raise ValueError("Unsupported alignment session kind")
    provided=_matrix(session.get("transform_source_to_target"))
    if kind=="existing_candidate":
        return dict(matrix=provided,kind=kind,point_pairs=[],rmse_mm=None,
            note="User-selected existing transform; its recorded candidate provenance must be checked by the caller")
    pairs=session.get("point_pairs")
    if not isinstance(pairs,list) or not 3<=len(pairs)<=64:
        raise ValueError("Expected 3..64 point correspondences")
    source,target=np.asarray(source,float),np.asarray(target,float)
    if source.ndim!=2 or target.ndim!=2 or source.shape[1]!=3 or target.shape[1]!=3:
        raise ValueError("Expected original N by 3 point arrays")
    selected={"source":[],"target":[]};used={"source":set(),"target":set()};maximum_rounding_error=0.
    for pair in pairs:
        if not isinstance(pair,dict):raise ValueError("Malformed point pair")
        for name,array in (("source",source),("target",target)):
            row=pair.get(name,{})
            if not isinstance(row,dict):raise ValueError("Malformed point reference")
            rid=row.get("id")
            if type(rid) is not int or not 0<=rid<len(array) or rid in used[name]:
                raise ValueError("Invalid or duplicate original point ID")
            used[name].add(rid)
            value=row.get("xyz")
            if not isinstance(value,list) or len(value)!=3 or any(type(x) not in (int,float) for x in value):
                raise ValueError("Expected numeric XYZ preview coordinates")
            value=np.asarray(value,float);original=array[rid]
            if not np.isfinite(value).all() or not np.isfinite(original).all():raise ValueError("Nonfinite selected point")
            tolerance=np.maximum(.002,2*np.abs(np.spacing(original.astype(np.float32))).astype(float))
            rounding=np.abs(value-original)
            if np.any(rounding>tolerance):raise ValueError("Preview coordinates do not match original point ID")
            maximum_rounding_error=max(maximum_rounding_error,float(rounding.max()))
            selected[name].append(original)
    source_pairs,target_pairs=np.array(selected["source"]),np.array(selected["target"])
    matrix=rigid_alignment(source_pairs,target_pairs)
    prediction=source_pairs@matrix[:3,:3].T+matrix[:3,3]
    provided_prediction=source_pairs@provided[:3,:3].T+provided[:3,3]
    # The preview fit can differ slightly after returning to full precision.
    difference=float(np.linalg.norm(prediction-provided_prediction,axis=1).max())
    if difference>max(.01,maximum_rounding_error*10):raise ValueError("Exported transform disagrees with recomputed original-point fit")
    residuals=np.linalg.norm(prediction-target_pairs,axis=1)
    return dict(matrix=matrix,kind=kind,point_pairs=[dict(source_id=p["source"]["id"],target_id=p["target"]["id"],residual_mm=float(r)) for p,r in zip(pairs,residuals)],
        rmse_mm=float(np.sqrt(np.mean(residuals**2))),maximum_residual_mm=float(residuals.max()),
        maximum_preview_rounding_error_mm=maximum_rounding_error,maximum_export_fit_difference_mm=difference,
        note="Recomputed on original coordinates; residuals describe selected landmarks, not full-surface accuracy")
