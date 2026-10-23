"""Run the unchanged mechanism audit against a new G00-G05 observation root."""
import argparse
from pathlib import Path
import audit_observations as audit

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name',choices=['G%02d'%i for i in range(6)])
    parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args();audit.ROOT=args.root;audit.main(args.name)
