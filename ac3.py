import copy
from collections import deque

class AC3:
    def __init__(self, courses, cid_constraints, session_constraints=None ,no_class_constraints=None, allow_partial=False, skip_ac3=False, domains=None):
        """
        :courses: List[Course] (must have .id and .name)
        :cid_constraints: dict course_id -> list of timeslot strings
        :session_constraints: List[Course] that the user pre-selected
        """
        self.courses = courses
        self.cid_constraints = cid_constraints
        self.constraints_from_session = session_constraints or []
        self.no_class = no_class_constraints or []
        self.allow_partial = allow_partial
        self.skip_ac3 = skip_ac3
        self.progress = []  # Collecting progress for debugging
        
        # Debug: print cid_constraints when initializing
        print("DEBUG [AC3 - cid_constraints initialized]:")
        for course_id, timeslots in self.cid_constraints.items():
            print(f"  - Course ID {course_id}: {timeslots}")
        
        if domains:
            self.domains = domains
            self.progress.append(f"Domains explicitly provided: {len(self.domains)} variables.")
        else:
            self.domains = {}
            self._init_domains()
            
        self._init_queue()

    def _init_domains(self):
        """
        Initialize domains by iterating over cid_constraints:
          • Honor user picks (unless they conflict with no_class)
          • Then fill in all other IDs, skipping forbidden slots
        """
        raw = {}
        forbidden = {f"{day} {time}" for day, time in self.no_class}

       # 1) Lock in user picks by ID, using cid_constraints to check slots
        skipped_picks = []
        for c in self.constraints_from_session:
            cid = c.id
            info = self.cid_constraints.get(cid)
            if not info:
                continue
            # if any of this CID’s slots conflict, skip entirely
            if all(slot not in forbidden for slot in info['constraints']):
                raw.setdefault(info['course_name'], set()).add(cid)
            else:
                skipped_picks.append(f"{cid}")

        if skipped_picks:
            self.progress.append(
                f"Skipped picked {', '.join(skipped_picks)} due to no-class constraint"
        )


        # 2) Fill in all other IDs from cid_constraints, grouped by course_name
        for cid, info in self.cid_constraints.items():
            name = info['course_name']
            # if user already locked in this variable, skip
            if name in raw:
                continue

            allowed = set()
            pruned = []

            for cid_, detail in self.cid_constraints.items():
                if detail['course_name'] != name:
                    continue
                if all(slot not in forbidden for slot in detail['constraints']):
                    allowed.add(cid_)
                else:
                    pruned.append(cid_)

            if pruned:
                self.progress.append(
                    f"Pruned {', '.join(pruned)} from {name} due to no-class constraint"
                )

            raw[name] = allowed


        # 3) Sort by domain size and convert to lists
        sorted_items = sorted(raw.items(), key=lambda kv: len(kv[1]))
        self.domains = {name: list(ids) for name, ids in sorted_items}

        # DEBUG
        print("DEBUG [AC3 - Domains initialized]:")
        for name, dom in self.domains.items():
            print(f"  - {name}: {dom}")
        self.progress.append(
            "Domains initialized: " +
            ", ".join(f"{n}({len(d)})" for n, d in self.domains.items())
        )

    def _init_queue(self):
        """
        Initialize the queue of arcs to be processed by the AC-3 algorithm.
        """
        vars_ = list(self.domains)
        self.queue = deque((Xi, Xj) for Xi in vars_ for Xj in vars_ if Xi != Xj)
        self.progress.append(f"Queue initialized with {len(self.queue)} arcs")

    def _parse_slot(self, slot_str):
        # slot_str: "Monday 08:30-09:45"
        try:
            parts = slot_str.split(' ')
            day = parts[0]
            time_range = parts[1]
            start_str, end_str = time_range.split('-')
            
            # Convert to minutes from midnight for easier comparison
            def to_minutes(t_str):
                h, m = map(int, t_str.split(':'))
                return h * 60 + m
            
            return day, to_minutes(start_str), to_minutes(end_str)
        except:
            # Fallback for unexpected formats
            return None, 0, 0

    def _no_conflict(self, a, b):
        """
        Checks if two course IDs (a, b) have conflicting timeslots.
        Returns True if there is no conflict, and False if there is a conflict.
        """
        # Global constraint: Cannot take the same course subject twice
        # even if they are different sections (IDs)
        if self.cid_constraints[a]['course_name'] == self.cid_constraints[b]['course_name']:
            # Unless it's the exact same ID (which is handled by AllDiff implicitly, but let's be safe)
            # Actually, if a==b, it's the same value assigned to two variables -> Conflict if we want AllDiff
            # But normally backtracking assigns one var at a time.
            # If two variables (e.g. Elective 1, Elective 2) get same course name -> Conflict.
            self.progress.append(f"Conflict detected (same subject): {a} and {b} are both '{self.cid_constraints[a]['course_name']}'")
            return False

        # Iterate over the timeslots for both courses a and b
        for con in self.cid_constraints[a]['constraints']:
            for con2 in self.cid_constraints[b]['constraints']:
                # Strict string equality first (fast path)
                if con == con2:
                    self.progress.append(f"Conflict detected (exact match): {a} and {b} at {con}")
                    return False
                
                # Check for overlap
                day1, s1, e1 = self._parse_slot(con)
                day2, s2, e2 = self._parse_slot(con2)
                
                if day1 and day2 and day1 == day2:
                    # Overlap logic: Start1 < End2 AND Start2 < End1
                    if s1 < e2 and s2 < e1:
                        self.progress.append(f"Conflict detected (overlap): {a} and {b} at {con} / {con2}")
                        return False

        return True  # No conflict found


    def revise(self, Xi, Xj):
        pruned = False
        newdom = []

        # If allow_partial is True and Xj has no values, we cannot satisfy constraints with Xj.
        # But we shouldn't kill Xi because of it. We just ignore Xj's constraints on Xi.
        if self.allow_partial and not self.domains[Xj]:
             return False
        
        # Debug: print the domains being revised
        print(f"DEBUG [AC3 - Revising] - Revising domain for {Xi} (Current domain: {self.domains[Xi]})")
        
        for vi in self.domains[Xi]:
            # Keep vi if there's some vj in Xj that doesn't conflict
            if any(self._no_conflict(vi, vj) for vj in self.domains[Xj]):
                newdom.append(vi)
            else:
                pruned = True
                self.progress.append(f"Pruned {vi} from {Xi} (no support in {Xj})")
        
        if pruned:
            self.domains[Xi] = newdom
        return pruned


    def run(self):
        """
        Perform the AC-3 algorithm, pruning the domains of the variables.
        """
        self.progress.append("Starting AC-3 constraint propagation...")
        # Debug: before pruning
        self.progress.append(f"DEBUG - Domains before pruning: {self.domains}")

        while self.queue:
            Xi, Xj = self.queue.popleft()
            if self.revise(Xi, Xj):
                # re-enqueue affected arcs
                for Xk in self.domains:
                    if Xk not in (Xi, Xj):
                        self.queue.append((Xk, Xi))

        # Debug: after pruning
        self.progress.append(f"DEBUG - Domains after pruning: {self.domains}")
        self.progress.append("AC-3 done.")
        return self.progress

   

    def _is_consistent(self, assignment, vars_):
        seen = set()
        for var in vars_:
            cid = assignment.get(var)  # Get the course ID corresponding to the course_name
            if cid is None:
                continue
            for slot in self.cid_constraints[cid]["constraints"]:
                if slot in seen:
                    return False
                seen.add(slot)
        return True




    def solve(self):
        """
        Run AC-3, then perform depth-first backtracking to find all valid assignments.
        """
        import time
        start_time = time.time()
        TIME_LIMIT = 5.0 # Seconds

        if not self.allow_partial and not self.skip_ac3:
            self.run()  # Apply AC-3
        elif self.skip_ac3:
            self.progress.append("Skipping AC-3 propagation (Pure Backtracking requested).")
        else:
            self.progress.append("Skipping AC-3 (partial schedules enabled)")

        # If not allowing partial, fail fast on empty domains
        if not self.allow_partial:
            # Remove empty domains
            self.domains = {k: v for k, v in self.domains.items() if v}
            if not self.domains:
                self.progress.append("No valid domains remaining after AC-3.")
                return []
        
        # Ensure we have a consistent list of variables to iterate
        vars_ = list(self.domains.keys())
        solutions = []

        self.progress.append(f"Starting backtracking search over {len(vars_)} variables...")

        def backtrack(assignment, index):
            if time.time() - start_time > TIME_LIMIT:
                return

            # Base case: all variables considered
            if index == len(vars_):
                if assignment:  # Avoid empty solution
                    solutions.append(assignment.copy())
                return

            var = vars_[index]
            
            # Branch 1: Try assigning values from the domain
            # (If domain is empty, this loop just won't run, effectively forcing a skip if partial allowed)
            if var in self.domains:
                for val in self.domains[var]:
                    assignment[var] = val
                    if self._is_consistent(assignment, list(assignment.keys())):
                        backtrack(assignment, index + 1)
                        if time.time() - start_time > TIME_LIMIT: return # Check after return
                    del assignment[var]

            # Branch 2: Skip this variable (Only if allow_partial)
            if self.allow_partial:
                backtrack(assignment, index + 1)
            elif index == len(vars_) - 1 and not assignment and not self.domains.get(var):
                # Edge case for non-partial: if we are at the last var and haven't assigned anything?
                # Actually, standard non-partial logic demands full assignment. 
                # If we skipped branch 1, we just return (fail).
                pass

        # Start recursion
        backtrack({}, 0)
        
        if time.time() - start_time > TIME_LIMIT:
             self.progress.append(f"Search terminated early due to time limit ({TIME_LIMIT}s). Found {len(solutions)} solutions.")

        self.progress.append(f"Backtracking complete. Found {len(solutions)} raw candidate solutions.")

        # Post-processing: Filter for maximal solutions if partial
        if self.allow_partial and solutions:
            # Sort by length descending (largest schedules first)
            solutions.sort(key=len, reverse=True)
            maximal = []
            for s in solutions:
                # Check if s is a subset of any already accepted maximal solution
                # (Since we sorted by size, a subset must be smaller or equal to existing ones)
                s_items = set(s.items())
                is_subset = False
                for m in maximal:
                    if s_items.issubset(set(m.items())):
                        is_subset = True
                        break
                if not is_subset:
                    maximal.append(s)
            self.progress.append(f"Filtered to {len(maximal)} maximal partial schedules.")
            return maximal

        return solutions


       
        
       
      
