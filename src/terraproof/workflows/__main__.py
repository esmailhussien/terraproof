"""Scientific workflow command-line boundary; importable core is UI-independent."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .intent import SCHEMA, approve, plan, write
from .lst import execute, repair, verify
from .sources import REQUEST, BYTE_CAP, discover, acquire


def main(argv=None):
    parser = argparse.ArgumentParser(prog='terraproof workflow')
    subs = parser.add_subparsers(dest='action', required=True)
    init = subs.add_parser('init', help='write an unapproved local ST workflow template')
    init.add_argument('--metadata', required=True)
    source_init = subs.add_parser('source-init', help='write a public Landsat source-search request; no network access')
    source_init.add_argument('--max-scene-cloud', type=float, required=True, help='catalog search limit; not AOI quality')
    source_init.add_argument('--max-download-bytes', type=int, default=BYTE_CAP)
    for draft in (init,source_init):
        draft.add_argument('file'); draft.add_argument('--aoi', required=True)
        draft.add_argument('--start', required=True); draft.add_argument('--end', required=True)
        draft.add_argument('--reject-qa-bits', type=int, nargs='+', required=True)
        draft.add_argument('--min-valid-fraction', type=float, required=True)
        draft.add_argument('--allow-partial', action='store_true', help='explicitly permit partial AOI coverage; requires review')
        draft.add_argument('--max-uncertainty-kelvin',type=float,help='optional scientific cutoff; omitted means no automatic uncertainty exclusion')
    search = subs.add_parser('discover', help='metadata-only source alternatives; no approval or pixel processing')
    search.add_argument('file'); search.add_argument('--out', required=True)
    fetch = subs.add_parser('acquire', help='download exactly one explicitly selected proposal and create an unapproved native workflow')
    fetch.add_argument('report'); fetch.add_argument('--item', required=True); fetch.add_argument('--out', required=True)
    fetch.add_argument('--expect-digest', required=True)
    p = subs.add_parser('plan',help='windowed QA/uncertainty preflight and scientific choices; no analysis outputs')
    p.add_argument('file')
    a = subs.add_parser('approve', help='record review of exact intent and input bytes')
    a.add_argument('file'); a.add_argument('--out', required=True); a.add_argument('--reviewer', required=True)
    a.add_argument('--expect-digest', required=True)
    a.add_argument('--review-kind',choices=['engineering-self-review','declared-scientific-review'],default='engineering-self-review',
                   help='self-declared provenance only; reviewer identity is not authenticated')
    r = subs.add_parser('run', help='execute, verify and publish a new run directory')
    r.add_argument('approval'); r.add_argument('--out', required=True)
    v = subs.add_parser('verify', help='recheck every pixel against original approved inputs')
    v.add_argument('approval'); v.add_argument('directory')
    repair_parser = subs.add_parser('repair', help='one regeneration into a new directory, preserving old evidence')
    repair_parser.add_argument('approval'); repair_parser.add_argument('directory'); repair_parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    if args.action in ('init','source-init'):
        if Path(args.file).exists():
            raise ValueError('template output already exists')
        document = {'schema': SCHEMA if args.action == 'init' else REQUEST, 'id': 'local-land-surface-temperature',
                    'intent': {'quantity': 'land-surface-temperature', 'unit': 'degree_Celsius',
                               'aoi': str(Path(args.aoi).resolve()), 'acquired_between': [args.start, args.end],
                               'reject_qa_bits': args.reject_qa_bits, 'min_valid_fraction': args.min_valid_fraction,
                               'scene_coverage': 'allow-partial' if args.allow_partial else 'full-aoi'}}
        if args.max_uncertainty_kelvin is not None:
            document['intent']['max_uncertainty_kelvin'] = args.max_uncertainty_kelvin
        if args.action == 'init':
            document['source'] = {'metadata': str(Path(args.metadata).resolve()), 'representation': 'usgs-native-dn'}
        else:
            document['search'] = {'max_scene_cloud':args.max_scene_cloud,'max_download_bytes':args.max_download_bytes}
        write(args.file, document)
        result = {'status': 'draft', 'file': str(Path(args.file).resolve()), 'approved': False}
    elif args.action == 'plan':
        result = plan(args.file)
    elif args.action == 'discover':
        result = discover(args.file,args.out)
    elif args.action == 'acquire':
        result = acquire(args.report,args.item,args.out,expected_digest=args.expect_digest)
    elif args.action == 'approve':
        result = approve(args.file,args.out,reviewer=args.reviewer,expected_digest=args.expect_digest,review_kind=args.review_kind)
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
