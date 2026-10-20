"""Start the local reconstruction Web studio."""
import argparse
from pathlib import Path
from reconstruction_probe.web_studio import serve

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8877);args=parser.parse_args()
    serve(Path(__file__).resolve().parents[1],args.port)
