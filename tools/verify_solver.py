#!/usr/bin/env python3
"""
Regression checks for the CP-SAT scheduler, run headless against the real JSON data.

    python3 tools/verify_solver.py

Checks the properties the old AC-3 solver got wrong:
  * no two courses in a schedule overlap in time (including partial overlaps)
  * no subject appears twice
  * every requirement slot is filled in a complete schedule
  * no two schedules are permutations of the same set of sections
  * results do not depend on the order the variables are declared in
"""

import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import CourseDataLoader, MAX_SCHEDULES  # noqa: E402
from cpsat_solver import ScheduleSolver, parse_slot  # noqa: E402

PROGRAM = 'BSCS - 7'
DATA = ['program_core.json', 'electives.json', 'ns_electives.json']
REQUIREMENTS = {'Elective': 2, 'NS-Elective': 1}

failures = []


def check(label, ok, detail=''):
    print('%-4s %s%s' % ('ok' if ok else 'FAIL', label, (' - ' + detail) if detail else ''))
    if not ok:
        failures.append(label)


def build_domains(reverse=False):
    loader = CourseDataLoader(DATA)
    mapping = loader.get_course_id_constraint_mapping()

    domains = {}
    pool_slots = defaultdict(list)

    core = defaultdict(set)
    for c in loader.load_courses_by_program(PROGRAM):
        core[c.name].add(c.id)
    for name, ids in core.items():
        domains[name] = sorted(ids)

    for pool, count in REQUIREMENTS.items():
        ids = sorted({c.id for c in loader.load_courses_by_program(pool)})
        for i in range(1, count + 1):
            var = '%s %d' % (pool, i)
            domains[var] = list(ids)
            pool_slots[pool].append(var)

    if reverse:
        domains = dict(reversed(list(domains.items())))
    return domains, dict(pool_slots), mapping


def overlaps(a, b):
    pa, pb = parse_slot(a), parse_slot(b)
    if not pa or not pb or pa[0] != pb[0]:
        return False
    return pa[1] < pb[2] and pb[1] < pa[2]


def audit(solutions, mapping, expected_size=None):
    bad_overlap = bad_dupe = bad_size = 0
    signatures = set()
    duplicate_sets = 0

    for sol in solutions:
        slots = []
        names = []
        for cid in sol.values():
            info = mapping[cid]
            slots += info['constraints']
            names.append(info['course_name'])

        for i in range(len(slots)):
            for j in range(i + 1, len(slots)):
                if overlaps(slots[i], slots[j]):
                    bad_overlap += 1
        if len(set(names)) != len(names):
            bad_dupe += 1
        if expected_size is not None and len(sol) != expected_size:
            bad_size += 1

        sig = frozenset(sol.values())
        if sig in signatures:
            duplicate_sets += 1
        signatures.add(sig)

    return bad_overlap, bad_dupe, bad_size, duplicate_sets


def main():
    domains, pool_slots, mapping = build_domains()
    print('BSCS - 7 domains: %s\n'
          % ', '.join('%s(%d)' % (v, len(d)) for v, d in domains.items()))

    # --- unconstrained: exercises the cap ------------------------------------
    solver = ScheduleSolver(domains, mapping, pool_slots=pool_slots,
                            max_solutions=MAX_SCHEDULES, time_limit=15.0)
    solutions = solver.solve()
    bad_overlap, bad_dupe, bad_size, dupes = audit(solutions, mapping, len(domains))

    check('produced schedules', len(solutions) > 0, '%d found' % len(solutions))
    check('respects the %d-schedule cap' % MAX_SCHEDULES, len(solutions) <= MAX_SCHEDULES)
    check('reports hitting the cap', solver.limit_reached)
    check('no time overlaps', bad_overlap == 0, '%d overlapping pairs' % bad_overlap)
    check('no repeated subjects', bad_dupe == 0, '%d schedules' % bad_dupe)
    check('every slot filled', bad_size == 0, '%d wrong-size schedules' % bad_size)
    check('no permutation duplicates', dupes == 0, '%d duplicate course sets' % dupes)

    # --- locked core section, so the search finishes -------------------------
    hci_ids = sorted(domains['Human Computer Interaction'])
    narrowed = dict(domains)
    narrowed['Human Computer Interaction'] = [hci_ids[0]]
    narrowed['NS-Elective 1'] = domains['NS-Elective 1'][:6]

    a = ScheduleSolver(narrowed, mapping, pool_slots=pool_slots,
                       locked_vars={'Human Computer Interaction'},
                       max_solutions=100000, time_limit=30.0).solve()
    reversed_domains = dict(reversed(list(narrowed.items())))
    b = ScheduleSolver(reversed_domains, mapping, pool_slots=pool_slots,
                       locked_vars={'Human Computer Interaction'},
                       max_solutions=100000, time_limit=30.0).solve()

    norm = lambda sols: {tuple(sorted(s.items())) for s in sols}  # noqa: E731
    check('exhaustive run stayed under the cap', len(a) < 100000, '%d schedules' % len(a))
    check('order independent', norm(a) == norm(b),
          '%d vs %d schedules' % (len(a), len(b)))

    bad_overlap, bad_dupe, bad_size, dupes = audit(a, mapping, len(narrowed))
    check('narrowed run: no overlaps', bad_overlap == 0)
    check('narrowed run: no permutation duplicates', dupes == 0)

    # --- partial mode --------------------------------------------------------
    impossible = {
        'Human Computer Interaction': [hci_ids[0]],
        'Elective 1': domains['Elective 1'],
        'Elective 2': domains['Elective 2'],
        'NS-Elective 1': domains['NS-Elective 1'],
    }
    # Force a clash: every elective slot restricted to sections that collide with core.
    core_slots = set(mapping[hci_ids[0]]['constraints'])
    clashing = [cid for cid in domains['Elective 1']
                if any(overlaps(s, c) for s in mapping[cid]['constraints']
                       for c in core_slots)]
    if clashing:
        impossible['Elective 1'] = clashing[:1]
        impossible['Elective 2'] = clashing[:1]
        impossible['NS-Elective 1'] = domains['NS-Elective 1'][:3]

        strict = ScheduleSolver(impossible, mapping, pool_slots=pool_slots,
                                time_limit=10.0).solve()
        partial = ScheduleSolver(impossible, mapping, pool_slots=pool_slots,
                                 allow_partial=True, time_limit=10.0).solve()
        sizes = {len(s) for s in partial}
        check('strict mode finds nothing when courses clash', strict == [])
        check('partial mode still returns schedules', len(partial) > 0,
              '%d found' % len(partial))
        check('partial schedules are all maximal', len(sizes) <= 1, 'sizes %s' % sorted(sizes))
        bad_overlap, _, _, dupes = audit(partial, mapping)
        check('partial run: no overlaps', bad_overlap == 0)
    else:
        print('skip  partial-mode check (no clashing elective found)')

    print()
    if failures:
        print('%d CHECK(S) FAILED: %s' % (len(failures), ', '.join(failures)))
        return 1
    print('all checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
