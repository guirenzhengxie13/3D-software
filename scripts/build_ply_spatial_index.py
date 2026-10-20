"""Create a source-bound disk index for exact local vertex queries."""

import argparse
import json
from pathlib import Path

from reconstruction_probe.ply_spatial_index import build_ply_spatial_index


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--unit',choices=['mm'],required=True);parser.add_argument('--tile-mm',type=float,default=5.);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();report=build_ply_spatial_index(args.source,args.out,args.tile_mm)
    print(json.dumps({key:report[key] for key in ['source_vertex_count','finite_source_points','tiles','index_bytes','elapsed_seconds']}),flush=True)


if __name__=='__main__':main()
