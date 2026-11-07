from flask import (Flask, Response, abort, flash, redirect, render_template, request,
                   session, url_for)
from flask_session import Session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import csv
import io
import json
from typing import List, Dict
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import hmac
import zlib
import os
from cpsat_solver import ScheduleSolver, parse_slot

# Pre-selected on the program picker. BSCS-7 is the semester this build targets.
DEFAULT_PROGRAM = "BSCS - 7"

# Caps on the CP-SAT search. These bound memory and response time on Render's free
# tier, where the whole app shares 512MB.
MAX_SCHEDULES = 500
SOLVER_TIME_LIMIT = 8.0

DEFAULT_DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
DEFAULT_SLOTS = ['08:30-09:45', '10:00-11:15', '11:30-12:45', '13:00-14:15',
                 '14:30-15:45', '16:00-17:15', '17:30-18:45', '19:00-20:15']


def load_grid_layout():
    """The days and timetable columns to render, taken from config.json."""
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        days = config.get('days') or DEFAULT_DAYS
        raw_slots = config.get('time_slots', {})
        if isinstance(raw_slots, list):
            slots = list(raw_slots)
        else:
            slots = sorted({s for day_slots in raw_slots.values() for s in day_slots})
        return days, (slots or DEFAULT_SLOTS)
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        return DEFAULT_DAYS, DEFAULT_SLOTS


def slot_minutes(time_str):
    """How long a timetable block lasts, in minutes."""
    block = parse_slot('X %s' % time_str)
    return (block[2] - block[1]) if block else 0


def slot_span(time_str, grid_slots):
    """Grid columns an actual meeting overlaps.

    Real class times do not always line up with the standard blocks - a Friday
    double slot runs 08:30-11:15 and some Saturday classes start at 09:00. Without
    this those classes would simply not appear in the timetable.
    """
    meeting = parse_slot('X %s' % time_str)
    if not meeting:
        return [time_str]
    _, start, end = meeting
    covered = []
    for slot in grid_slots:
        block = parse_slot('X %s' % slot)
        if block and block[1] < end and start < block[2]:
            covered.append(slot)
    return covered or [time_str]

def overlaps_blocked(meetings, no_class):
    """True if any 'Day HH:MM-HH:MM' meeting overlaps one of the blocked (day, slot) cells.

    Compared by time rather than by string, so a 08:30-11:15 double class is ruled
    out when the student blocks 10:00-11:15 on that day.
    """
    blocks = [parse_slot('%s %s' % (d, t)) for d, t in no_class]
    for meeting in meetings:
        m = parse_slot(meeting)
        if not m:
            continue
        for b in blocks:
            if b and b[0] == m[0] and b[1] < m[2] and m[1] < b[2]:
                return True
    return False


def load_program_requirements(program_name):
    """Elective pools a program needs, e.g. {'Elective': 2, 'NS-Elective': 1}."""
    try:
        with open('program_requirements.json', 'r') as f:
            all_requirements = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    reqs = all_requirements.get(program_name) or all_requirements.get(program_name.replace(' ', '')) or {}
    return {k: v for k, v in reqs.items() if isinstance(v, int) and v > 0}


def load_term():
    """Term dates for the calendar export. Edit config.json to match the academic calendar."""
    try:
        with open('config.json', 'r') as f:
            term = json.load(f).get('term', {})
    except (FileNotFoundError, json.JSONDecodeError):
        term = {}
    start = date.fromisoformat(term.get('start', '2026-08-24'))
    end = date.fromisoformat(term.get('end', '2026-12-12'))
    return start, end, float(term.get('utc_offset_hours', 5))


TONES = 8


def course_tone(name):
    """A stable colour index per course name, so a course keeps its colour on every page."""
    return zlib.crc32((name or '').encode('utf-8')) % TONES


def display_name(var):
    """'Elective 2' -> 'Elective'; core course names pass through."""
    head, _, tail = (var or '').rpartition(' ')
    return head if head in ('Elective', 'NS-Elective') and tail.isdigit() else var


app = Flask(__name__)
# Security: Use env var for secret key in production
app.secret_key = os.environ.get("SECRET_KEY", "super_secret_fallback_key_for_dev_only")

# Security: Rate Limiting
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["2000 per day", "500 per hour"],
    storage_uri="memory://"
)

# Configure Server-Side Session
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_PERMANENT"] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size
Session(app)
app.jinja_env.filters['tone'] = course_tone
app.jinja_env.filters['display_name'] = display_name
app.jinja_env.filters['dict_without'] = lambda d, key: {k: v for k, v in d.items() if k != key}

# The data editor rewrites the JSON files the app runs on, so a public deploy only
# exposes it when ADMIN_TOKEN is set: open /admin?token=<value> once per session.
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")


def admin_allowed():
    if not ADMIN_TOKEN:
        return app.debug
    supplied = request.args.get('token', '')
    if supplied and hmac.compare_digest(supplied, ADMIN_TOKEN):
        session['is_admin'] = True
    return session.get('is_admin', False)


@app.route('/')
def home():
    loader = CourseDataLoader(['program_core.json', 'electives.json', 'ns_electives.json'])
    courses = loader.load_courses()
    programs = {c.program for c in courses} - {'Elective', 'NS-Elective'}
    return render_template('home.html',
                           section_count=len({c.id for c in courses}),
                           program_count=len(programs),
                           has_session=bool(session.get('program_name')))


@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if not admin_allowed():
        abort(404)
    message = None
    error = None
    requirements_path = 'program_requirements.json'
    courses_path = 'program_core.json'
    ns_electives_path = 'ns_electives.json'
    electives_path = 'electives.json'
    config_path = 'config.json'

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'upload_data':
            if 'course_file' not in request.files:
                error = 'No file part'
            else:
                file = request.files['course_file']
                if file.filename == '':
                    error = 'No selected file'
                elif file:
                    filename = file.filename.lower()
                    try:
                        if filename.endswith('.json'):
                            file.save(courses_path)
                            message = "Course data (JSON) uploaded successfully."
                        elif filename.endswith('.csv'):
                            # Convert CSV to JSON records, everything as strings.
                            text = io.TextIOWrapper(file.stream, encoding='utf-8-sig')
                            records = [{k: ('' if v is None else str(v))
                                        for k, v in row.items()}
                                       for row in csv.DictReader(text)]
                            with open(courses_path, 'w') as out:
                                json.dump(records, out, indent=4)
                            message = "Course data (CSV) converted and uploaded successfully."
                        else:
                            error = "Invalid file type. Please upload .json or .csv."
                        
                        # Clear cache if new data uploaded
                        CourseDataLoader._cached_courses = None
                        
                    except Exception as e:
                        error = f"Error processing file: {str(e)}"

        elif action == 'save_requirements':
            req_content = request.form.get('requirements_json')
            try:
                # Validate JSON
                json_obj = json.loads(req_content)
                with open(requirements_path, 'w') as f:
                    json.dump(json_obj, f, indent=4)
                message = "Program requirements saved successfully."
            except json.JSONDecodeError as e:
                error = f"Invalid JSON format: {str(e)}"
            except Exception as e:
                error = f"Error saving requirements: {str(e)}"

        elif action == 'save_schedule':
            sched_content = request.form.get('schedule_json')
            try:
                # Validate JSON
                json_obj = json.loads(sched_content)
                with open(courses_path, 'w', encoding='utf-8') as f:
                    json.dump(json_obj, f, indent=4)
                message = "Schedule data saved successfully."
                # Clear cache
                CourseDataLoader._cached_courses = None
            except json.JSONDecodeError as e:
                error = f"Invalid JSON format: {str(e)}"
            except Exception as e:
                error = f"Error saving schedule: {str(e)}"

        elif action == 'save_ns_electives':
            content = request.form.get('ns_electives_json')
            try:
                json_obj = json.loads(content)
                with open(ns_electives_path, 'w', encoding='utf-8') as f:
                    json.dump(json_obj, f, indent=4)
                message = "NS Electives saved successfully."
                CourseDataLoader._cached_courses = None
            except Exception as e:
                error = f"Error saving NS Electives: {str(e)}"

        elif action == 'save_electives':
            content = request.form.get('electives_json')
            try:
                json_obj = json.loads(content)
                with open(electives_path, 'w', encoding='utf-8') as f:
                    json.dump(json_obj, f, indent=4)
                message = "Electives saved successfully."
                CourseDataLoader._cached_courses = None
            except Exception as e:
                error = f"Error saving Electives: {str(e)}"

        elif action == 'save_config':
            config_content = request.form.get('config_json')
            try:
                json_obj = json.loads(config_content)
                with open(config_path, 'w') as f:
                    json.dump(json_obj, f, indent=4)
                message = "Configuration (Days & Slots) saved successfully."
            except json.JSONDecodeError as e:
                error = f"Invalid JSON format: {str(e)}"
            except Exception as e:
                error = f"Error saving configuration: {str(e)}"

    # Load current requirements for display
    try:
        with open(requirements_path, 'r') as f:
            requirements_content = f.read()
    except FileNotFoundError:
        requirements_content = "{}"

    # Load current schedule for display
    try:
        with open(courses_path, 'r', encoding='utf-8') as f:
            schedule_content = f.read()
    except FileNotFoundError:
        schedule_content = "[]"

    # Load NS electives
    try:
        with open(ns_electives_path, 'r', encoding='utf-8') as f:
            ns_electives_content = f.read()
    except FileNotFoundError:
        ns_electives_content = "[]"

    # Load Electives
    try:
        with open(electives_path, 'r', encoding='utf-8') as f:
            electives_content = f.read()
    except FileNotFoundError:
        electives_content = "[]"

    # Load config for display
    try:
        with open(config_path, 'r') as f:
            config_content = f.read()
    except FileNotFoundError:
        config_content = '{\n    "days": [],\n    "time_slots": []\n}'

    return render_template('admin.html',
                           requirements_content=requirements_content, 
                           schedule_content=schedule_content,
                           ns_electives_content=ns_electives_content,
                           electives_content=electives_content,
                           config_content=config_content, 
                           message=message, error=error)


class Course:
    def __init__(self, name, program, instructor, id, room, day, time, comments):
        self.name = name
        self.program = program
        self.instructor = instructor
        self.id = id
        self.room = room
        self.day = day
        self.time = time
        self.comments = comments

    def __str__(self):
        return f"{self.name} - {self.instructor} - {self.id} | {self.time} | {self.day} | Room: {self.room}"

    def to_dict(self):
        return {
            'name': self.name,
            'program': self.program,
            'instructor': self.instructor,
            'id': self.id,
            'room': self.room,
            'day': self.day,
            'time': self.time,
            'comments': self.comments
        }

    @staticmethod
    def from_dict(data):
        return Course(**data)

    def __eq__(self, other):
        return isinstance(other, Course) and self.id == other.id and self.day == other.day and self.time == other.time

    def __hash__(self):
        return hash((self.id, self.day, self.time))

class CourseDataLoader:
    REQUIRED_FIELDS = {
        'name': str,
        'program': str,
        'instructor': str,
        'id': str,
        'room': str,
        'day': str,
        'time': str,
        'comments': str
    }
    
    # Class-level cache to store courses in memory after first load
    _cached_courses = None
    _cached_path = None

    def __init__(self, json_paths):
        if isinstance(json_paths, str):
            self.json_paths = [json_paths]
        else:
            self.json_paths = json_paths

    def load_courses(self) -> List[Course]:
        # Return cached data if available and paths match
        # Naive cache key: tuple of paths
        paths_key = tuple(sorted(self.json_paths))
        if CourseDataLoader._cached_courses is not None and CourseDataLoader._cached_path == paths_key:
            return CourseDataLoader._cached_courses

        courses = []
        for path in self.json_paths:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                continue

            for idx, item in enumerate(data):
                validated = {}
                for field, field_type in self.REQUIRED_FIELDS.items():
                    value = item.get(field, "").strip()
                    if not isinstance(value, field_type):
                        value = field_type(value)
                    if field in ('day', 'time'):
                        value = value.replace(" ", "")
                    validated[field] = value
                
                # --- Data Cleaning Logic for Electives ---
                # User format: Name="Elective", Program="BSCS-X", Instructor="Name - Subject"
                if validated['name'] in ('Elective', 'CS-Elective', 'NS-Elective'):
                    # 1. Hoist to generic Program pool
                    original_name = validated['name']
                    current_program = validated['program']
                    
                    # If program is already set to one of our target pools, respect it.
                    if current_program not in ('NS-Elective', 'Elective'):
                        if original_name == 'NS-Elective':
                            validated['program'] = 'NS-Elective'
                        else:
                            validated['program'] = 'Elective'

                    # 2. Extract Real Subject Name from Instructor field
                    raw_instr = validated['instructor']
                    if '-' in raw_instr:
                        # Try splitting by ' - ' first (safest)
                        parts = raw_instr.split(' - ', 1)
                        if len(parts) < 2:
                            parts = raw_instr.split('-', 1) # Fallback to simple hyphen
                        
                        if len(parts) >= 2:
                            real_instructor = parts[0].strip()
                            real_subject = parts[1].strip()
                            
                            validated['instructor'] = real_instructor
                            validated['name'] = real_subject

                courses.append(Course(**validated))
        
        # Update cache
        CourseDataLoader._cached_courses = courses
        CourseDataLoader._cached_path = paths_key
        
        return courses

    def get_available_programs(self):
        return list({course.program for course in self.load_courses()})

    def load_courses_by_program(self, program_name):
        return [course for course in self.load_courses() if course.program == program_name]

    def get_schedule(self, program_name):
        schedule = defaultdict(lambda: defaultdict(list))
        for course in self.load_courses_by_program(program_name):
            schedule[course.time][course.day].append(course)
        return schedule

    def get_highlighted_course_ids(self):
        course_ids = defaultdict(list)
        for course in self.load_courses():
            course_ids[course.id].append(course)
        colors = ["#f0f8ff", "#faebd7", "#98fb98", "#d3d3d3", "#ffb6c1", "#ffcccb"]
        course_colors = {}
        for i, course_id in enumerate(course_ids):
            course_colors[course_id] = colors[i % len(colors)]
        return course_colors

    def get_course_by_id(self, course_id):
        return [course for course in self.load_courses() if course.id == course_id]

    def get_course_id_mapping(self):
        course_id_mapping = defaultdict(list)
        for course in self.load_courses():
            course_id_mapping[course.id].append(course)
        return course_id_mapping 
    
    def get_course_id_constraint_mapping(self):
        course_id_constraint_mapping = defaultdict(lambda: {'constraints': [], 'course_name': None, 'instructor': None, 'room': None})
        course_id_mapping = self.get_course_id_mapping()

        for course_id, courses in course_id_mapping.items():
            for course in courses:
                if course_id_constraint_mapping[course_id]['course_name'] is None:
                    course_id_constraint_mapping[course_id]['course_name'] = course.name
                
                if not course_id_constraint_mapping[course_id]['room']:
                    course_id_constraint_mapping[course_id]['room'] = course.room

                if course_id_constraint_mapping[course_id]['instructor'] is None:
                    course_id_constraint_mapping[course_id]['instructor'] = course.instructor

                day = normalize(course.day)
                time = normalize(course.time)
                constraint_key = f"{day} {time}"
                # A section can be listed both as its cohort's core course and in the
                # general elective pool, so the same meeting arrives twice.
                if constraint_key not in course_id_constraint_mapping[course_id]['constraints']:
                    course_id_constraint_mapping[course_id]['constraints'].append(constraint_key)

        return course_id_constraint_mapping
    
    def get_course_name_to_ids_mapping(self):
        """
        Returns a dict mapping each course name to a list of course IDs that share that name.
        """
        name_to_ids = defaultdict(list)
        for course in self.load_courses():
            
            name_to_ids[course.name].append(course.id)
        return name_to_ids
    
    def get_course_id_to_time_mapping(self):

        id_to_time  = defaultdict (list)
        for course in self.load_courses():
            day = normalize(course.day)
            time = normalize(course.time)
            time_key = f"{day} {time}"
            id_to_time[course.id].append(time_key)
        return id_to_time


def normalize(s):
        return " ".join(s.strip().split())

def get_constraints_from_session():
    return [Course.from_dict(c) for c in session.get('constraints', [])]


def save_constraints_to_session(courses: List[Course]):
    session['constraints'] = [c.to_dict() for c in courses]
    session.modified = True
   

def get_no_class_constraints_from_session():
    """
    Returns a list of (day, time) tuples stored in session under 'no_class'.
    """
    return [tuple(x) for x in session.get('no_class', [])]

def save_no_class_constraints_to_session(no_class_list):
    """
    Persists the list of (day, time) tuples to session['no_class'].
    """
    session['no_class'] = [list(x) for x in no_class_list]
    session.modified = True



@app.route('/select_program', methods=['GET', 'POST'])
def select_program():
    course_loader = CourseDataLoader(['program_core.json'])
    available_programs = sorted(list(course_loader.get_available_programs()))
    # Offer the default first so it heads the datalist.
    available_programs.sort(key=lambda p: p != DEFAULT_PROGRAM)

    if request.method == 'POST':
        if 'program' in request.form:
            user_input = request.form['program'].strip()
            
            # Normalize and match
            normalized_input = user_input.replace(" ", "").upper()
            matched_program = user_input # Default fallback
            
            for prog in available_programs:
                if prog.replace(" ", "").upper() == normalized_input:
                    matched_program = prog
                    break
            
            if matched_program not in available_programs:
                flash("We don't have a timetable for \"%s\". Pick one from the list, e.g. %s."
                      % (user_input, DEFAULT_PROGRAM), "error")
                return redirect(url_for('select_program'))
            session.clear()
            session['program_name'] = matched_program
            # Redirect to the schedule route after selecting the program
            return redirect(url_for('schedule'))

    default_program = DEFAULT_PROGRAM if DEFAULT_PROGRAM in available_programs else ''
    return render_template('index.html',
                           available_programs=available_programs,
                           default_program=default_program)


STEPS = [
    {'n': 1, 'label': 'Block times', 'files': [], 'pool': None},
    {'n': 2, 'label': 'Core courses', 'files': ['program_core.json'], 'pool': 'core'},
    {'n': 3, 'label': 'Electives', 'files': ['electives.json'], 'pool': 'Elective'},
    {'n': 4, 'label': 'NS electives', 'files': ['ns_electives.json'], 'pool': 'NS-Elective'},
]


DENSE_LIMIT = 40
LIST_LIMIT = 30


@app.route('/schedule', methods=['GET', 'POST'])
def schedule():
    program_name = session.get('program_name', None)
    if not program_name:
        return redirect(url_for('select_program'))

    try:
        current_step = min(max(int(request.args.get('step', 1)), 1), len(STEPS))
    except ValueError:
        current_step = 1
    step = STEPS[current_step - 1]
    target_program = program_name if step['pool'] == 'core' else step['pool']

    course_loader = CourseDataLoader(step['files'])
    all_courses = course_loader.load_courses()
    constraints = get_constraints_from_session()
    no_class_constraints = get_no_class_constraints_from_session()

    if request.method == 'POST':
        if 'course_id' in request.form:
            course_id = request.form['course_id']
            for c in all_courses:
                if c.id == course_id and c not in constraints:
                    constraints.append(c)
            save_constraints_to_session(constraints)

        if 'remove_course_id' in request.form:
            remove_id = request.form['remove_course_id']
            constraints = [c for c in constraints if c.id != remove_id]
            save_constraints_to_session(constraints)

        if 'no_class_day' in request.form and 'no_class_time' in request.form:
            cell = (request.form['no_class_day'], request.form['no_class_time'])
            if cell not in no_class_constraints:
                no_class_constraints.append(cell)
                save_no_class_constraints_to_session(no_class_constraints)

        if 'no_class_day_remove' in request.form and 'no_class_time_remove' in request.form:
            cell = (request.form['no_class_day_remove'], request.form['no_class_time_remove'])
            no_class_constraints = [c for c in no_class_constraints if c != cell]
            save_no_class_constraints_to_session(no_class_constraints)

        if 'toggle_partial' in request.form:
            session['allow_partial'] = not session.get('allow_partial', False)
            session.modified = True

        return redirect(url_for('schedule', step=current_step, q=request.args.get('q') or None))

    days, grid_slots = load_grid_layout()

    # slot -> day -> sections meeting in that block. A meeting that runs across
    # several blocks, or starts off-grid, is listed in every block it overlaps.
    cells = defaultdict(lambda: defaultdict(list))
    unavailable_ids = set()
    # course name -> section id -> its meetings, for the list view under the calendar
    sections = defaultdict(lambda: defaultdict(list))
    if target_program:
        mapping = course_loader.get_course_id_constraint_mapping()
        for course in course_loader.load_courses_by_program(target_program):
            for column in slot_span(normalize(course.time), grid_slots):
                cells[column][normalize(course.day)].append(course)
            sections[course.name][course.id].append(course)
            if overlaps_blocked(mapping[course.id]['constraints'], no_class_constraints):
                unavailable_ids.add(course.id)

    picked_ids = {c.id for c in constraints}
    requirements = load_program_requirements(program_name)
    core_names = sorted({c.name for c in CourseDataLoader(['program_core.json'])
                         .load_courses_by_program(program_name)})

    # Picks that meet at the same time as another pick can never share a schedule.
    clashes = []
    picks = {}
    for c in constraints:
        picks.setdefault(c.id, c)
    meetings = {cid: ['%s %s' % (normalize(c.day), normalize(c.time)) for c in constraints if c.id == cid]
                for cid in picks}
    ids = sorted(picks)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if picks[a].name == picks[b].name:
                continue
            pa = [parse_slot(m) for m in meetings[a]]
            pb = [parse_slot(m) for m in meetings[b]]
            if any(x and y and x[0] == y[0] and x[1] < y[2] and y[1] < x[2] for x in pa for y in pb):
                clashes.append((picks[a], picks[b]))

    # Big pools (the NS-elective list has hundreds of courses) are too many to
    # draw as chips, so the grid shows counts and the list is searched instead.
    dense = len(sections) > DENSE_LIMIT
    query = request.args.get('q', '').strip()
    listed = sorted(sections.items())
    if dense:
        if query:
            needle = query.lower()
            listed = [(name, by_id) for name, by_id in listed
                      if needle in name.lower()
                      or any(needle in m[0].instructor.lower() for m in by_id.values())]
        # Always list picked courses, then the first matches.
        picked_names = {c.name for c in constraints}
        listed.sort(key=lambda item: item[0] not in picked_names)
    match_count = len(listed)
    if dense:
        listed = listed[:LIST_LIMIT]

    return render_template(
        'schedule.html',
        dense=dense,
        query=query,
        match_count=match_count,
        program_name=program_name,
        steps=STEPS,
        step=step,
        current_step=current_step,
        total_steps=len(STEPS),
        days=days,
        grid_slots=grid_slots,
        cells=cells,
        picked_ids=picked_ids,
        unavailable_ids=unavailable_ids,
        picks=list(picks.values()),
        no_class_constraints=no_class_constraints,
        blocked={'%s|%s' % c for c in no_class_constraints},
        allow_partial=session.get('allow_partial', False),
        requirements=requirements,
        core_names=core_names,
        clashes=clashes,
        sections={name: dict(by_id) for name, by_id in listed},
        section_total=len(sections),
    )


@app.route('/clear_constraints', methods=['POST'])
def clear_constraints():
    save_constraints_to_session([])
    return redirect(url_for('schedule', step=request.form.get('step', 2)))

@app.route('/clear_no_class_constraints', methods=['POST'])
def clear_no_class_constraints():
    save_no_class_constraints_to_session([])
    return redirect(url_for('schedule', step=request.form.get('step', 1)))



@app.route('/ac3_schedule', methods=['GET','POST'])
def ac3_schedule():
    program_name = session.get('program_name')
    if not program_name:
        return redirect(url_for('select_program'))

    course_loader = CourseDataLoader(['program_core.json', 'electives.json', 'ns_electives.json'])
    session_course_constraints = get_constraints_from_session() 
    session_no_class = get_no_class_constraints_from_session()
    
    allow_partial = session.get('allow_partial', False)
    program_reqs = load_program_requirements(program_name)

    app.logger.debug(f"Program Requirements for {program_name}: {program_reqs}")

    # 2. Build Domains and Constraint Map
    domains = {}
    full_mapping = course_loader.get_course_id_constraint_mapping()
    active_cid_constraints = {} # Map for AC3 (ID -> Constraints)
    
    # A section is ruled out when any of its meetings overlaps a blocked cell.
    def is_id_valid(cid):
        return not overlaps_blocked(full_mapping[cid]['constraints'], session_no_class)

    pool_slots = defaultdict(list)   # pool -> its slot variables, in order
    locked_vars = set()              # variables pinned to a single user-picked section

    # A. Core Courses
    program_courses = course_loader.load_courses_by_program(program_name)
    app.logger.debug(f"Found {len(program_courses)} raw core courses for {program_name}")
    
    # Group core by name to build domains. Every course the program requires becomes a
    # variable even if the user has blocked all of its sections - the domain is then
    # empty, which turns the run partial instead of quietly dropping the course.
    core_grouped = defaultdict(set) # Use set to prevent duplicates
    for c in program_courses:
        core_grouped[c.name].add(c.id)

    for name, ids in core_grouped.items():
        valid_ids = {cid for cid in ids if is_id_valid(cid)}
        for cid in valid_ids:
            active_cid_constraints[cid] = full_mapping[cid]

        # Check if user picked specific sections (session_constraints)
        picked_ids = {sc.id for sc in session_course_constraints if sc.name == name}
        if picked_ids:
            domains[name] = sorted(picked_ids & valid_ids)
            if domains[name]:
                locked_vars.add(name)
        else:
            domains[name] = sorted(valid_ids)
            
    app.logger.debug(f"Constructed Core Domains: {list(domains.keys())}")

    # B. Elective Slots
    for pool_name, count in program_reqs.items():
        pool_courses = course_loader.load_courses_by_program(pool_name)
        app.logger.debug(f"Found {len(pool_courses)} courses for pool '{pool_name}'")
        if not pool_courses:
            continue
            
        # Filter pool IDs (use set to distinct)
        pool_ids = list({c.id for c in pool_courses if is_id_valid(c.id)})
        app.logger.debug(f"Valid IDs for '{pool_name}': {len(pool_ids)}")
        
        # Add to active constraint map
        for cid in pool_ids:
            active_cid_constraints[cid] = full_mapping[cid]

        # Identify user picks for this pool
        picked_for_pool = []
        seen_picked = set()
        for sc in session_course_constraints:
            if sc.program == pool_name:
                 if is_id_valid(sc.id) and sc.id not in seen_picked:
                     picked_for_pool.append(sc.id)
                     seen_picked.add(sc.id)
            
        # Create N slots.
        #
        # Picking at least as many courses as there are slots is a SHORTLIST: every
        # slot draws from the whole shortlist and the solver works out which
        # combination of `count` actually fits together. Handing one pick to each
        # slot instead would throw away every pick past the count, and would make the
        # result depend on the order the user happened to click.
        shortlisted = len(picked_for_pool) >= count
        for i in range(1, count + 1):
            var_name = f"{pool_name} {i}"
            pool_slots[pool_name].append(var_name)

            if shortlisted:
                # Identical domains, nothing locked, so the solver's symmetry
                # breaking reports each combination once instead of count! times.
                domains[var_name] = list(picked_for_pool)
            elif i <= len(picked_for_pool):
                # Fewer picks than slots: those picks are requirements, and the
                # remaining slots are filled from the rest of the pool.
                domains[var_name] = [picked_for_pool[i-1]]
                locked_vars.add(var_name)
            else:
                # IMPORTANT: Remove already picked items from the general pool
                # to prevent "same subject" conflicts if the user didn't pick enough
                remaining_ids = [pid for pid in pool_ids if pid not in seen_picked]
                domains[var_name] = remaining_ids

    app.logger.debug(f"Final Domains Keys: {list(domains.keys())}")

    def run_solver(partial):
        # A fresh model every time. The old solver reused a domains dict its first
        # pass had already pruned in place, so the fallback searched a broken space.
        return ScheduleSolver(
            domains=domains,
            cid_constraints=active_cid_constraints,
            allow_partial=partial,
            pool_slots=pool_slots,
            locked_vars=locked_vars,
            max_solutions=MAX_SCHEDULES,
            time_limit=SOLVER_TIME_LIMIT,
        )

    solver = run_solver(allow_partial)
    solutions = solver.solve()

    # Nothing fits perfectly - fall back to the best partial schedules we can build.
    if not solutions and not allow_partial:
        app.logger.debug("No complete schedules found. Retrying with partial schedules enabled.")
        solver = run_solver(True)
        solutions = solver.solve()
        session['auto_partial_fallback'] = True
    else:
        session.pop('auto_partial_fallback', None)

    session['ac3_solutions'] = solutions
    session['ac3_progress'] = solver.progress
    session['solver_limit_reached'] = solver.limit_reached
    # Every requirement slot, core and elective. A schedule holding fewer than this
    # is partial - the old count looked only at core courses, so any schedule with
    # electives was reported as complete even when a course was missing.
    session['total_slots'] = len(domains)
    session['required_vars'] = list(domains.keys())

    return redirect(url_for('generated_schedules'))


DAY_ORDER = {'Monday': 1, 'Tuesday': 2, 'Wednesday': 3, 'Thursday': 4, 'Friday': 5,
             'Saturday': 6, 'Sunday': 7}


def read_priorities(args, max_levels=20):
    """Instructor priorities in slot order, keeping blank levels in place.

    Dropping the blanks would renumber the list, silently promoting the instructor in
    slot 2 to top priority when slot 1 is left as "-- None --".
    """
    values = [args.get(f'preferred_instructor_{i}', '').strip()
              for i in range(1, max_levels + 1)]
    while values and not values[-1]:
        values.pop()
    return values


def get_processed_schedules(solutions, program_name, args):
    # Filter/Sort Parameters
    sort_by = args.get('sort_by', 'count')
    filter_days = args.get('filter_days', '')

    # Retrieve dynamic priorities (Max 20 to prevent abuse)
    priority_instructors = read_priorities(args)

    course_loader = CourseDataLoader(['program_core.json', 'electives.json', 'ns_electives.json'])
    course_id_mapping = course_loader.get_course_id_constraint_mapping()
    
    # How many courses a complete schedule holds: one per requirement slot.
    total_program_courses = session.get('total_slots', 0)
    if not total_program_courses and program_name:
        program_courses = course_loader.load_courses_by_program(program_name)
        unique_names = {c.name for c in program_courses}
        total_program_courses = len(unique_names)

    grid_days, grid_slots = load_grid_layout()
    required_vars = session.get('required_vars', [])

    schedule_data = []
    all_instructors = set()
    # How many schedules run over 1 day, 2 days, ... Counted before the day filter is
    # applied, so the dropdown can only ever offer values that return something.
    day_counts = defaultdict(int)

    # Process all solutions
    for idx, sol in enumerate(solutions):
        grid = defaultdict(lambda: defaultdict(list))
        flat_courses = [] # For CSV export and sorting within schedule
        count = 0
        days_with_classes = set()
        instructors_in_schedule = set()
        
        # Which timetable columns each day is busy in, for the gap calculation.
        busy_columns = defaultdict(set)

        for var, cid in sol.items():
            count += 1
            course_info = course_id_mapping.get(cid)
            if course_info:
                name = course_info['course_name']
                instructor = course_info.get('instructor', '')
                room = course_info.get('room') or ''
                if instructor:
                    all_instructors.add(instructor)
                    instructors_in_schedule.add(instructor)
                
                for slot in course_info['constraints']:
                    parts = slot.split(' ')
                    if len(parts) >= 2:
                        day = parts[0]
                        time = parts[1]

                        # Store for grid. A class spanning several blocks (or starting
                        # off-grid) is drawn in every column it overlaps.
                        for column in slot_span(time, grid_slots):
                            grid[column][day].append({'id': cid, 'name': name,
                                                      'instructor': instructor,
                                                      'room': room,
                                                      'time': time})
                            if column in grid_slots:
                                busy_columns[day].add(grid_slots.index(column))

                        # Store for flat list
                        flat_courses.append({
                            'id': cid, 
                            'name': name, 
                            'instructor': instructor,
                            'room': room,
                            'day': day,
                            'time': time
                        })
                        days_with_classes.add(day)
        
        # Gaps are the free timetable blocks between the first and last class of a
        # day. Measuring the raw minutes between consecutive classes instead counts
        # the 15-minute changeover between adjacent blocks, so a back-to-back day
        # would report 45 minutes of "gaps" the student cannot actually use.
        free_blocks = 0
        total_gaps_minutes = 0
        for day, columns in busy_columns.items():
            for index in range(min(columns), max(columns) + 1):
                if index in columns:
                    continue
                free_blocks += 1
                total_gaps_minutes += slot_minutes(grid_slots[index])

        num_days = len(days_with_classes)
        day_counts[num_days] += 1

        if filter_days and str(num_days) != filter_days:
            continue

        # Calculate matches for 5 priorities
        priority_matches = []
        for p_inst in priority_instructors:
            if p_inst and p_inst in instructors_in_schedule:
                priority_matches.append(1)
            else:
                priority_matches.append(0)

        flat_courses.sort(key=lambda c: (DAY_ORDER.get(c['day'], 99), c['time']))
        filled = set(sol.keys())
        missing = [display_name(v) for v in required_vars if v not in filled]

        schedule_data.append({
            'schedule_index': idx + 1,  # position in the solver output, stable across sorts
            'missing': missing,
            'grid': grid,
            'flat_courses': flat_courses,
            'count': count,
            'is_partial': count < total_program_courses,
            'num_days': num_days,
            'total_gaps': total_gaps_minutes,
            'free_blocks': free_blocks,
            'priority_matches': priority_matches
        })

    # Ranking, strongest criterion first. Every component below reads
    # "smaller is better", so this is a plain ascending sort - the old version
    # sorted descending and had to flip signs, which is what made it hard to
    # reason about.
    #
    #   1. Days per week    - not here; it is a filter, applied above.
    #   2. Most courses     - a schedule missing a course loses to one that is
    #                         complete, whatever else it has going for it.
    #   3. Instructor       - compared level by level, so priority 1 outranks
    #      priorities         priority 2 outranks priority 3, and matching only
    #                         priority 1 beats matching only priority 2.
    #   4. The "Sort By"    - fewest days, or most compact.
    #      choice
    #   5. Schedule number  - so equally good schedules keep a stable order
    #                         instead of drifting between page loads.
    def sort_key(x):
        most_courses = -x['count']
        # 0 sorts before 1, so negate: a matched priority must rank first.
        priorities = tuple(-matched for matched in x['priority_matches'])
        fewest_days = x['num_days']
        most_compact = (x['free_blocks'], x['total_gaps'])

        if sort_by == 'gaps':
            chosen = (most_compact, fewest_days)
        else:  # 'days', and the legacy 'count' default
            chosen = (fewest_days, most_compact)

        return (most_courses, priorities) + chosen + (x['schedule_index'],)

    schedule_data.sort(key=sort_key)

    return (schedule_data, total_program_courses, sorted(list(all_instructors)),
            dict(sorted(day_counts.items())))


@app.route('/generated_schedules', methods=['GET'])
def generated_schedules():
    solutions = session.get('ac3_solutions', [])
    progress = session.get('ac3_progress', [])
    program_name = session.get('program_name', '')
    if not program_name:
        return redirect(url_for('select_program'))

    schedule_data, total_program_courses, all_instructors, day_counts = get_processed_schedules(
        solutions, program_name, request.args)

    limit_reached = session.get('solver_limit_reached', False)
    if len(schedule_data) > MAX_SCHEDULES:
        schedule_data = schedule_data[:MAX_SCHEDULES]
        limit_reached = True

    # One schedule is drawn at a time; ?page=N picks which one of the ranked list.
    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
    page = min(max(page, 1), max(len(schedule_data), 1))
    current = schedule_data[page - 1] if schedule_data else None

    # Query string for links that keep the current filters but change the page.
    keep = {k: v for k, v in request.args.items() if k != 'page' and v}

    grid_days, grid_slots = load_grid_layout()

    return render_template('generated_schedules.html',
                           program_name=program_name,
                           schedule_data=schedule_data,
                           current=current,
                           page=page,
                           keep=keep,
                           progress=progress,
                           total_courses=total_program_courses,
                           auto_partial_fallback=session.get('auto_partial_fallback', False),
                           current_sort=request.args.get('sort_by', 'days'),
                           current_filter_days=request.args.get('filter_days', ''),
                           current_priorities=read_priorities(request.args),
                           all_instructors=all_instructors,
                           solved=bool(session.get('required_vars')),
                           filter_empty=(not schedule_data and bool(solutions)),
                           limit_reached=limit_reached,
                           max_schedules=MAX_SCHEDULES,
                           grid_days=grid_days,
                           grid_slots=grid_slots,
                           day_counts=day_counts)


def pick_schedules(args):
    """Ranked schedules for an export; ?schedule=N limits it to one of them."""
    schedule_data, _, _, _ = get_processed_schedules(
        session.get('ac3_solutions', []), session.get('program_name', ''), args)
    wanted = args.get('schedule', '')
    if wanted.isdigit():
        schedule_data = [x for x in schedule_data if x['schedule_index'] == int(wanted)]
    return schedule_data


@app.route('/export_schedules', methods=['GET'])
def export_schedules():
    if not session.get('ac3_solutions'):
        return redirect(url_for('generated_schedules'))

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['Rank', 'Schedule', 'Day', 'Time', 'Course', 'Instructor', 'Room', 'Section ID'])
    for rank, item in enumerate(pick_schedules(request.args), start=1):
        for c in item['flat_courses']:
            writer.writerow([rank, item['schedule_index'], c['day'], c['time'], c['name'],
                             c['instructor'], c['room'], c['id']])

    return Response(out.getvalue(), mimetype='text/csv',
                    headers={"Content-Disposition": "attachment; filename=schedules.csv"})


def ics_escape(text):
    return (str(text or '').replace('\\', '\\\\').replace(';', '\\;')
            .replace(',', '\\,').replace('\n', '\\n'))


@app.route('/export_ics', methods=['GET'])
def export_ics():
    """One schedule as weekly calendar events for Google Calendar, Outlook or Apple Calendar."""
    picked = pick_schedules(request.args)
    if not request.args.get('schedule', '').isdigit() or not picked:
        abort(404)
    item = picked[0]

    term_start, term_end, offset_hours = load_term()
    local = timezone(timedelta(hours=offset_hours))
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    until = datetime.combine(term_end, datetime.max.time().replace(microsecond=0), local)
    until = until.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')

    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//IBA Course Planner//EN',
             'CALSCALE:GREGORIAN', 'METHOD:PUBLISH']
    for n, c in enumerate(item['flat_courses']):
        parsed = parse_slot('%s %s' % (c['day'], c['time']))
        if not parsed:
            continue
        _, start_min, end_min = parsed
        weekday = DAY_ORDER.get(c['day'], 1) - 1
        first = term_start + timedelta(days=(weekday - term_start.weekday()) % 7)
        begin = datetime.combine(first, datetime.min.time(), local) + timedelta(minutes=start_min)
        finish = datetime.combine(first, datetime.min.time(), local) + timedelta(minutes=end_min)
        fmt = lambda d: d.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        lines += ['BEGIN:VEVENT',
                  'UID:%s-%d-%d@course-planner' % (c['id'], item['schedule_index'], n),
                  'DTSTAMP:' + stamp,
                  'DTSTART:' + fmt(begin),
                  'DTEND:' + fmt(finish),
                  'RRULE:FREQ=WEEKLY;UNTIL=' + until,
                  'SUMMARY:' + ics_escape(c['name']),
                  'LOCATION:' + ics_escape(c['room']),
                  'DESCRIPTION:' + ics_escape('%s - section %s' % (c['instructor'], c['id'])),
                  'END:VEVENT']
    lines.append('END:VCALENDAR')

    return Response('\r\n'.join(lines) + '\r\n', mimetype='text/calendar',
                    headers={"Content-Disposition":
                             "attachment; filename=schedule-%d.ics" % item['schedule_index']})


if __name__ == '__main__':
    debug_mode = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
    app.run(debug=debug_mode)
