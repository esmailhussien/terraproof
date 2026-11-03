"""Scientific workflow command-line boundary; importable core is UI-independent."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .intent import SCHEMA, approve, plan, write
from .lst import execute, repair, verify


def main(argv=None):
    parser = argparse.ArgumentParser(prog='terraproof workflow')
    subs = parser.add_subparsers(dest='action', required=True)
    init = subs.add_parser('init', help='write an unapproved local ST workflow template')
    init.add_argument('file'); init.add_argument('--metadata', required=True); init.add_argument('--aoi', required=True)
    init.add_argument('--start', required=True); init.add_argument('--end', required=True)
    init.add_argument('--reject-qa-bits', type=int, nargs='+', required=True)
    init.add_argument('--min-valid-fraction', type=float, required=True)
    p = subs.add_parser('plan', help='admit inputs and show scientific choices without processing')
    p.add_argument('file')
    a = subs.add_parser('approve', help='record review of exact intent and input bytes')
    a.add_argument('file'); a.add_argument('--out', required=True); a.add_argument('--reviewer', required=True)
    a.add_argument('--expect-digest', required=True)
    r = subs.add_parser('run', help='execute, verify and publish a new run directory')
    r.add_argument('approval'); r.add_argument('--out', required=True)
    v = subs.add_parser('verify', help='recheck every pixel against original approved inputs')
    v.add_argument('approval'); v.add_argument('directory')
    repair_parser = subs.add_parser('repair', help='one regeneration into a new directory, preserving old evidence')
    repair_parser.add_argument('approval'); repair_parser.add_argument('directory'); repair_parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    if args.action == 'init':
        if Path(args.file).exists():
            raise ValueError('template output already exists')
        document = {'schema': SCHEMA, 'id': 'local-land-surface-temperature',
                    'intent': {'quantity': 'land-surface-temperature', 'unit': 'degree_Celsius',
                               'aoi': str(Path(args.aoi).resolve()), 'acquired_between': [args.start, args.end],
                               'reject_qa_bits': args.reject_qa_bits, 'min_valid_fraction': args.min_valid_fraction},
                    'source': {'metadata': str(Path(args.metadata).resolve()), 'representation': 'usgs-native-dn'}}
        write(args.file, document)
        result = {'status': 'draft', 'file': str(Path(args.file).resolve()), 'approved': False}
    elif args.action == 'plan':
        result = plan(args.file)
    elif args.action == 'approve':
        result = approve(args.file, args.out, reviewer=args.reviewer, expected_digest=args.expect_digest)
    elif args.action == 'run':
        result = execute(args.approval, args.out)
    elif args.action == 'repair':
        result = repair(args.approval, args.directory, args.out)
    else:
        result = verify(args.approval, args.directory)
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
    return 3 if result.get('status') in ('unresolved', 'incomplete', 'failed') else 0


if __name__ == '__main__':
    raise SystemExit(main())
