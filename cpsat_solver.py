"""
Timetable solver built on Google OR-Tools CP-SAT.

Replaces the hand-rolled AC-3 + DFS solver. Three things it fixes:

  * Order independence. `enumerate_all_solutions` yields every distinct assignment
    exactly once, whatever order the variables happen to be in. The old backtracker
    walked `list(domains.keys())` and its results depended on that order.

  * Real overlap detection. Every meeting is projected onto 5-minute buckets and each
    bucket gets an AtMostOne. A Friday 08:30-11:15 double slot therefore conflicts with
    a Friday 10:00-11:15 class. The old search only compared timeslot strings for
    equality, so partial overlaps slipped through.

  * No permutation duplicates. "Elective 1" and "Elective 2" range over the same pool,
    so each real schedule used to be emitted 2! times. Interchangeable slots are now
    ordered by a symmetry-breaking constraint.

The public surface matches what app.py already passed to AC3: a dict of
`variable -> [course_id]` domains plus the course-id constraint map, and `solve()`
returns a list of `{variable: course_id}` assignments.
"""

import re
import time

from ortools.sat.python import cp_model

BUCKET_MINUTES = 5

_SLOT_RE = re.compile(r'^\s*(\S+)\s+(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$')


def parse_slot(slot):
    """'Monday 08:30-09:45' -> ('Monday', 510, 585). Returns None if unparseable."""
    m = _SLOT_RE.match(slot or '')
    if not m:
        return None
    day, h1, m1, h2, m2 = m.groups()
    start = int(h1) * 60 + int(m1)
    end = int(h2) * 60 + int(m2)
    if end <= start:
        return None
    return day, start, end


def slot_buckets(slot):
    """The (day, bucket) cells a meeting occupies."""
    parsed = parse_slot(slot)
    if not parsed:
        return []
    day, start, end = parsed
    first = start // BUCKET_MINUTES
    last = (end - 1) // BUCKET_MINUTES
    return [(day, b) for b in range(first, last + 1)]


class _Collector(cp_model.CpSolverSolutionCallback):
    """Collects assignments and stops the search once the cap is hit."""

    def __init__(self, literals, limit):
        super().__init__()
        self._literals = literals          # var -> [(cid, BoolVar), ...]
        self._limit = limit
        self.solutions = []
        self.hit_limit = False

    def on_solution_callback(self):
        assignment = {}
        for var, pairs in self._literals.items():
            for cid, lit in pairs:
                if self.Value(lit):
                    assignment[var] = cid
                    break
        if assignment:
            self.solutions.append(assignment)
        if len(self.solutions) >= self._limit:
            self.hit_limit = True
            self.StopSearch()


class ScheduleSolver:
    def __init__(self, domains, cid_constraints, allow_partial=False,
                 pool_slots=None, locked_vars=None,
                 max_solutions=500, time_limit=8.0):
        """
        :param domains: {variable_name: [course_id, ...]}
        :param cid_constraints: {course_id: {'constraints': ['Day HH:MM-HH:MM', ...],
                                             'course_name': str, 'instructor': str}}
        :param allow_partial: leave variables unassigned when no complete schedule fits
        :param pool_slots: {pool_name: [var, ...]} - interchangeable slots, in order
        :param locked_vars: variables pinned by a user pick (excluded from symmetry breaking)
        :param max_solutions: hard cap on enumerated schedules
        :param time_limit: wall-clock budget in seconds for each solve phase
        """
        self.domains = {v: list(ids) for v, ids in (domains or {}).items()}
        self.cid_constraints = cid_constraints or {}
        self.allow_partial = allow_partial
        self.pool_slots = pool_slots or {}
        self.locked_vars = set(locked_vars or ())
        self.max_solutions = max_solutions
        self.time_limit = time_limit

        self.progress = []
        self.limit_reached = False
        self.status_name = ''

    # ------------------------------------------------------------------ model

    def _build(self):
        """Returns (model, literals, assigned, total) for the current domains."""
        model = cp_model.CpModel()
        literals = {}
        assigned = {}
        bucket_users = {}
        name_users = {}

        for var, cids in self.domains.items():
            pairs = []
            for cid in cids:
                if cid not in self.cid_constraints:
                    continue
                lit = model.NewBoolVar('x_%s_%s' % (var, cid))
                pairs.append((cid, lit))

                info = self.cid_constraints[cid]
                for slot in info.get('constraints', []):
                    for cell in slot_buckets(slot):
                        bucket_users.setdefault(cell, []).append(lit)
                name_users.setdefault(info.get('course_name', cid), []).append(lit)

            literals[var] = pairs
            flag = model.NewBoolVar('assigned_%s' % var)
            model.Add(sum(lit for _, lit in pairs) == flag)
            if not self.allow_partial:
                model.Add(flag == 1)
            assigned[var] = flag

        # No two selected sections may overlap in time.
        for lits in bucket_users.values():
            if len(lits) > 1:
                model.AddAtMostOne(lits)

        # The same subject may not be taken twice, whatever the section.
        for lits in name_users.values():
            if len(lits) > 1:
                model.AddAtMostOne(lits)

        self._break_symmetry(model, literals, assigned)

        total = sum(assigned.values())
        return model, literals, assigned, total

    def _break_symmetry(self, model, literals, assigned):
        """Order interchangeable slots of a pool so permutations collapse to one."""
        for pool, slots in self.pool_slots.items():
            free = [v for v in slots
                    if v in self.domains and v not in self.locked_vars]
            if len(free) < 2:
                continue

            order = {}
            for var in free:
                for cid in self.domains[var]:
                    order.setdefault(cid, None)
            for rank, cid in enumerate(sorted(order)):
                order[cid] = rank

            index = {}
            for var in free:
                pairs = literals.get(var, [])
                iv = model.NewIntVar(0, max(len(order) - 1, 0), 'idx_%s' % var)
                model.Add(iv == sum(order[cid] * lit for cid, lit in pairs))
                index[var] = iv

            for earlier, later in zip(free, free[1:]):
                model.Add(index[earlier] < index[later]).OnlyEnforceIf(
                    [assigned[earlier], assigned[later]])
                # Fill lower-numbered slots first so partial schedules do not repeat.
                model.Add(assigned[earlier] >= assigned[later])
            self.progress.append(
                "Symmetry broken across %d interchangeable '%s' slots" % (len(free), pool))

    # ------------------------------------------------------------------ solve

    def _configure(self, solver, enumerate_all, deadline):
        solver.parameters.max_time_in_seconds = max(deadline, 0.1)
        solver.parameters.num_search_workers = 1  # required to enumerate solutions
        solver.parameters.enumerate_all_solutions = enumerate_all
        solver.parameters.cp_model_presolve = True

    def _enumerate(self, extra_total=None, deadline=None):
        """Enumerate up to max_solutions assignments, optionally fixing the total."""
        model, literals, _assigned, total = self._build()
        if extra_total is not None:
            model.Add(total == extra_total)

        solver = cp_model.CpSolver()
        self._configure(solver, True, deadline if deadline is not None else self.time_limit)
        collector = _Collector(literals, self.max_solutions)
        status = solver.Solve(model, collector)

        self.status_name = solver.StatusName(status)
        if collector.hit_limit:
            self.limit_reached = True
            self.progress.append(
                'Stopped at the %d-schedule cap; add constraints to narrow the search.'
                % self.max_solutions)
        elif status == cp_model.UNKNOWN:
            self.limit_reached = True
            self.progress.append(
                'Search hit the %.0fs time budget; showing the schedules found so far.'
                % self.time_limit)
        return collector.solutions

    def _best_count(self, deadline):
        """Largest number of variables that can be assigned at once."""
        model, _literals, _assigned, total = self._build()
        model.Maximize(total)
        solver = cp_model.CpSolver()
        self._configure(solver, False, deadline)
        status = solver.Solve(model)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return int(round(solver.ObjectiveValue()))
        return 0

    def solve(self):
        started = time.time()
        self.progress.append(
            'CP-SAT model: %d variables, domains %s'
            % (len(self.domains),
               ', '.join('%s(%d)' % (v, len(d)) for v, d in self.domains.items())))

        empty = [v for v, d in self.domains.items() if not d]
        if empty:
            self.progress.append(
                'No sections available for: %s' % ', '.join(sorted(empty)))
            if not self.allow_partial:
                self.progress.append(
                    'Cannot build a complete schedule while those are empty.')
                return []

        if not self.allow_partial:
            solutions = self._enumerate()
            self.progress.append(
                'Solver status %s: %d complete schedules.'
                % (self.status_name, len(solutions)))
            return solutions

        best = self._best_count(self.time_limit / 2.0)
        if best <= 0:
            self.progress.append('No course could be scheduled at all.')
            return []
        self.progress.append(
            'Best achievable schedule holds %d of %d courses.' % (best, len(self.domains)))

        remaining = self.time_limit - (time.time() - started)
        solutions = self._enumerate(extra_total=best, deadline=remaining)
        self.progress.append(
            'Solver status %s: %d maximal partial schedules.'
            % (self.status_name, len(solutions)))
        return solutions
