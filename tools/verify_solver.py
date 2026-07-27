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
from itertools import permutations

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


def sections_by_name(names):
    """{course name: [section id, ...]} for the given titles, across all pools."""
    loader = CourseDataLoader(DATA)
    found = defaultdict(set)
    for course in loader.load_courses():
        if course.name in names:
            found[course.name].add(course.id)
    return {name: sorted(ids) for name, ids in found.items()}


def pick_sections(mapping, wanted):
    """Resolve {course name: [start-end, ...]} to {course name: [section id, ...]}.

    Sections are chosen by meeting time rather than by id, so the tests keep testing
    the same timetable shape after the data is regenerated and ids shift.
    """
    available = sections_by_name(set(wanted))
    picked = {}
    for name, times in wanted.items():
        ids = []
        for time in times:
            for cid in available.get(name, []):
                if cid in ids:
                    continue
                if any(slot.endswith(time) for slot in mapping[cid]['constraints']):
                    ids.append(cid)
                    break
        if len(ids) != len(times):
            return None
        picked[name] = ids
    return picked


def check_shortlist(mapping):
    """Picking more electives than there are slots must widen the search, not narrow it.

    Reproduces the bug report: three CS electives shortlisted for two slots, two core
    sections, one general elective. The three electives sit at 08:30, 13:00 and 14:30
    on Mon/Wed so every pair fits, giving C(3,2) x 2 core sections = 6 schedules.
    """
    picked = pick_sections(mapping, {
        'Compiler Construction': ['08:30-09:45'],
        'Parallel and Scalable Architectures': ['13:00-14:15'],
        'Computer Security': ['14:30-15:45'],
        'Human Computer Interaction': ['11:30-12:45', '16:00-17:15'],
        'Multivariable Calculus': ['10:00-11:15'],
    })
    if not picked:
        print('skip  shortlist check (expected sections not in the data)')
        return

    cs = {name: picked[name] for name in ('Compiler Construction',
                                          'Parallel and Scalable Architectures',
                                          'Computer Security')}
    shortlist = [ids[0] for ids in cs.values()]
    hci = picked['Human Computer Interaction']
    general = picked['Multivariable Calculus']

    def run(order):
        domains = {'Human Computer Interaction': list(hci),
                   'Elective 1': list(order),
                   'Elective 2': list(order),
                   'NS-Elective 1': list(general)}
        return ScheduleSolver(domains, mapping,
                              pool_slots={'Elective': ['Elective 1', 'Elective 2']},
                              max_solutions=1000, time_limit=20.0).solve()

    solutions = run(shortlist)
    check('shortlist of 3 for 2 slots gives every pair', len(solutions) == 6,
          '%d schedules, expected 6' % len(solutions))

    used = {mapping[cid]['course_name'] for s in solutions for cid in s.values()}
    check('every shortlisted elective is reachable', set(cs).issubset(used),
          'missing %s' % sorted(set(cs) - used))

    sizes = {len(s) for s in solutions}
    check('shortlist schedules are complete', sizes == {4}, 'sizes %s' % sorted(sizes))

    signatures = {frozenset(s.values()) for s in solutions}
    check('shortlist has no duplicate schedules', len(signatures) == len(solutions))

    # The failing property: results must not depend on the order the user clicked.
    baseline = {tuple(sorted(s.items())) for s in solutions}
    stable = all({tuple(sorted(s.items())) for s in run(list(perm))} == baseline
                 for perm in permutations(shortlist))
    check('shortlist is click-order independent', stable)

    # Fewer picks than slots: the pick is a requirement, the other slot stays open.
    loader = CourseDataLoader(DATA)
    pool = sorted({c.id for c in loader.load_courses_by_program('Elective')})
    one = shortlist[:1]
    domains = {'Human Computer Interaction': hci[:1],
               'Elective 1': list(one),
               'Elective 2': [p for p in pool if p not in one],
               'NS-Elective 1': list(general)}
    under = ScheduleSolver(domains, mapping,
                           pool_slots={'Elective': ['Elective 1', 'Elective 2']},
                           locked_vars={'Elective 1'},
                           max_solutions=1000, time_limit=20.0).solve()
    check('under-picking keeps the pick in every schedule',
          bool(under) and all(one[0] in s.values() for s in under),
          '%d schedules' % len(under))
    check('under-picking still varies the free slot',
          len({s['Elective 2'] for s in under}) > 1)


def check_gaps(mapping):
    """A back-to-back day has no gaps; the 15-minute changeover is not free time."""
    import app

    picked = pick_sections(mapping, {
        'Multivariable Calculus': ['10:00-11:15'],
        'Human Computer Interaction': ['11:30-12:45'],
        'Parallel and Scalable Architectures': ['13:00-14:15'],
        'Computer Security': ['14:30-15:45'],
    })
    if not picked:
        print('skip  gap check (expected sections not in the data)')
        return

    # 10:00, 11:30, 13:00, 14:30 on Mon+Wed - four consecutive blocks, no free period.
    back_to_back = {name: ids[0] for name, ids in picked.items()}
    # Dropping the 11:30 class leaves exactly one free block per day.
    with_hole = {name: cid for name, cid in back_to_back.items()
                 if name != 'Human Computer Interaction'}

    with app.app.test_request_context('/generated_schedules'):
        data, _, _, day_counts = app.get_processed_schedules(
            [back_to_back, with_hole], 'BSCS - 7', {})

    by_size = {len(s['flat_courses']): s for s in data}
    solid = by_size[max(by_size)]
    holed = by_size[min(by_size)]
    check('back-to-back schedule reports no gaps',
          solid['free_blocks'] == 0 and solid['total_gaps'] == 0,
          '%d blocks / %d min' % (solid['free_blocks'], solid['total_gaps']))
    check('a free period is counted once per day', holed['free_blocks'] == 2,
          '%d blocks' % holed['free_blocks'])
    check('day counts are offered for the filter', day_counts.get(2) == 2,
          'day_counts=%s' % day_counts)


def check_ranking(mapping):
    """Instructor priorities outrank the Sort By choice, and the order is stable."""
    import app

    picked = pick_sections(mapping, {
        'Compiler Construction': ['08:30-09:45'],
        'Parallel and Scalable Architectures': ['13:00-14:15'],
        'Computer Security': ['14:30-15:45'],
        'Human Computer Interaction': ['11:30-12:45', '16:00-17:15'],
        'Multivariable Calculus': ['10:00-11:15'],
    })
    if not picked:
        print('skip  ranking check (expected sections not in the data)')
        return

    domains = {'Human Computer Interaction': picked['Human Computer Interaction'],
               'Elective 1': [picked[n][0] for n in ('Compiler Construction',
                                                     'Parallel and Scalable Architectures',
                                                     'Computer Security')],
               'NS-Elective 1': picked['Multivariable Calculus']}
    domains['Elective 2'] = list(domains['Elective 1'])
    solutions = ScheduleSolver(domains, mapping,
                               pool_slots={'Elective': ['Elective 1', 'Elective 2']},
                               max_solutions=1000, time_limit=20.0).solve()

    psa = picked['Parallel and Scalable Architectures'][0]
    comsec = picked['Computer Security'][0]
    zafar = mapping[psa]['instructor']
    iradat = mapping[comsec]['instructor']

    def ranked(**args):
        with app.app.test_request_context('/generated_schedules'):
            data, _, _, _ = app.get_processed_schedules(solutions, 'BSCS - 7', args)
        return data

    for sort_by in ('days', 'gaps'):
        data = ranked(sort_by=sort_by, preferred_instructor_1=zafar,
                      preferred_instructor_2=iradat)
        matches = [tuple(x['priority_matches']) for x in data]
        check('priorities outrank "%s" sort' % sort_by,
              matches == sorted(matches, reverse=True), '%s' % matches)

    # Priority 1 alone must beat priority 2 alone, not merely "some match".
    data = ranked(preferred_instructor_1=zafar, preferred_instructor_2=iradat)
    order = [tuple(x['priority_matches']) for x in data]
    check('priority 1 outranks priority 2', order.index((1, 0)) < order.index((0, 1)),
          '%s' % order)

    # A blank level must not promote the instructor below it.
    blank = ranked(preferred_instructor_1='', preferred_instructor_2=iradat)
    check('a blank priority level does not promote the next one',
          all(x['priority_matches'][0] == 0 for x in blank))

    # Within one priority group the Sort By choice decides, and repeats identically.
    compact = ranked(sort_by='gaps')
    check('compact sort orders by free blocks',
          [x['free_blocks'] for x in compact] == sorted(x['free_blocks'] for x in compact))
    fewest = ranked(sort_by='days')
    check('days sort orders by days on campus',
          [x['num_days'] for x in fewest] == sorted(x['num_days'] for x in fewest))
    check('ranking is repeatable',
          [x['schedule_index'] for x in ranked(sort_by='gaps')] ==
          [x['schedule_index'] for x in compact])


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

    check_shortlist(mapping)
    check_gaps(mapping)
    check_ranking(mapping)

    print()
    if failures:
        print('%d CHECK(S) FAILED: %s' % (len(failures), ', '.join(failures)))
        return 1
    print('all checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
