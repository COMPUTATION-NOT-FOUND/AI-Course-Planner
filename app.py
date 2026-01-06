from flask import Flask, render_template, request, session, redirect, url_for
<<<<<<< HEAD
=======
from flask_session import Session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
>>>>>>> deployment
import json
import pandas as pd
from typing import List, Dict
from collections import defaultdict
from datetime import datetime
import ast
<<<<<<< HEAD
from ac3 import AC3 
from pso import BinaryPSO



app = Flask(__name__)
app.secret_key = "super secret key"  # Required for using sessions



=======
import os
from ac3 import AC3 

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
Session(app)


@app.route('/', methods=['GET', 'POST'])
def root():
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
                            # Convert CSV to JSON
                            df = pd.read_csv(file)
                            # Basic cleanup: ensure string types
                            df = df.astype(str)
                            # Save as JSON records
                            df.to_json(courses_path, orient='records', indent=4)
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

    return render_template('landing.html', 
                           requirements_content=requirements_content, 
                           schedule_content=schedule_content,
                           ns_electives_content=ns_electives_content,
                           electives_content=electives_content,
                           config_content=config_content, 
                           message=message, error=error)
>>>>>>> deployment


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
<<<<<<< HEAD

    def __init__(self, json_path):
        self.json_path = json_path

    def load_courses(self) -> List[Course]:
        with open(self.json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        courses = []
        for idx, item in enumerate(data):
            validated = {}
            for field, field_type in self.REQUIRED_FIELDS.items():
                value = item.get(field, "").strip()
                if not isinstance(value, field_type):
                    value = field_type(value)
                if field in ('day', 'time'):
                    value = value.replace(" ", "")
                validated[field] = value
            courses.append(Course(**validated))
=======
    
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
        
>>>>>>> deployment
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
        from collections import defaultdict


<<<<<<< HEAD
        course_id_constraint_mapping = defaultdict(lambda: {'constraints': [], 'course_name': None})
=======
        course_id_constraint_mapping = defaultdict(lambda: {'constraints': [], 'course_name': None, 'instructor': None})
>>>>>>> deployment
        course_id_mapping = self.get_course_id_mapping()

        for course_id, courses in course_id_mapping.items():
            for course in courses:
                if course_id_constraint_mapping[course_id]['course_name'] is None:
                    course_id_constraint_mapping[course_id]['course_name'] = course.name
<<<<<<< HEAD
=======
                
                if course_id_constraint_mapping[course_id]['instructor'] is None:
                    course_id_constraint_mapping[course_id]['instructor'] = course.instructor
>>>>>>> deployment

                day = normalize(course.day)
                time = normalize(course.time)
                constraint_key = f"{day} {time}"
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
    return session.get('no_class', [])

def save_no_class_constraints_to_session(no_class_list):
    """
    Persists the list of (day, time) tuples to session['no_class'].
    """
    session['no_class'] = no_class_list
    session.modified = True


from datetime import datetime

def parse_time_slot(time_input):
    """
    Accept either:
      - A string "Day HH-HH" or "Day HH–HH"
      - A list/tuple [Day, start_hour, end_hour]
    Returns (day, start_datetime, end_datetime).
    """
    # Case 1: already a Day/HH-HH string
    if isinstance(time_input, str):
        day, time_range = time_input.strip().split()
        start_str, end_str = time_range.replace('–', '-').split('-')
        start = datetime.strptime(start_str.strip(), '%H')
        end = datetime.strptime(end_str.strip(), '%H')

    # Case 2: list/tuple [Day, start, end]
    elif isinstance(time_input, (list, tuple)) and len(time_input) == 3:
        day = str(time_input[0]).strip()
        start = datetime.strptime(str(time_input[1]).strip(), '%H')
        end   = datetime.strptime(str(time_input[2]).strip(), '%H')

    else:
        raise ValueError(f"Invalid time slot format: {time_input!r}")

    return day, start, end


def check_time_conflict(times1, times2):
    """
    Given two lists of time slots (each slot either a string or [day, start, end]),
    returns True if any slot in times1 overlaps any in times2 on the same day.
    """
    # Parse into canonical (day, start, end) tuples
    slots1 = [parse_time_slot(t) for t in times1]
    slots2 = [parse_time_slot(t) for t in times2]

    # Check pairwise overlap
    for day1, s1, e1 in slots1:
        for day2, s2, e2 in slots2:
            if day1 == day2 and (s1 < e2 and s2 < e1):
                return True

    return False

<<<<<<< HEAD
@app.route('/', methods=['GET', 'POST'])
def index():
    session.clear()
    course_loader = CourseDataLoader('courses.json')
    available_programs = course_loader.get_available_programs()

    if request.method == 'POST':
        if 'program' in request.form:
            program_name = request.form['program']
            session['program_name'] = program_name
=======
@app.route('/select_program', methods=['GET', 'POST'])
def select_program():
    session.clear()
    course_loader = CourseDataLoader(['program_core.json'])
    available_programs = sorted(list(course_loader.get_available_programs()))

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
            
            session['program_name'] = matched_program
>>>>>>> deployment
            # Redirect to the schedule route after selecting the program
            return redirect(url_for('schedule'))

    return render_template('index.html', available_programs=available_programs)


@app.route('/schedule', methods=['GET', 'POST'])
def schedule():
    program_name = session.get('program_name', None)
    if not program_name:
<<<<<<< HEAD
        # If no program is selected, redirect back to the index page
        return redirect(url_for('index'))

    course_loader = CourseDataLoader('courses.json')
    highlighted_course_ids = course_loader.get_highlighted_course_ids()
    all_courses = course_loader.load_courses()
    # cid_constraints=course_loader.get_course_id_constraint_mapping()
    
=======
        return redirect(url_for('select_program'))

    # Determine current step
    try:
        current_step = int(request.args.get('step', 1))
    except ValueError:
        current_step = 1
    
    total_steps = 4
    
    # Determine files and target program based on step
    files_to_load = []
    target_program = None
    step_title = ""

    if current_step == 1:
        files_to_load = [] # No courses, just time slots
        target_program = None
        step_title = "Step 1: Define No-Class Constraints"
    elif current_step == 2:
        files_to_load = ['program_core.json']
        target_program = program_name
        step_title = "Step 2: Select Core Courses"
    elif current_step == 3:
        files_to_load = ['electives.json']
        target_program = 'Elective'
        step_title = "Step 3: Select Electives"
    elif current_step == 4:
        files_to_load = ['ns_electives.json']
        target_program = 'NS-Elective'
        step_title = "Step 4: Select NS Electives"

    course_loader = CourseDataLoader(files_to_load)
    # Highlighted IDs might need to be loaded from all files or just current? 
    # Let's load from current to be safe, or we can load global if we want consistent colors.
    # For simplicity, load from current.
    highlighted_course_ids = course_loader.get_highlighted_course_ids()
    
    # We need all_courses for the POST constraint addition to work.
    # If we only load current step files, we can only add constraints from current step.
    # This is correct for the wizard flow.
    all_courses = course_loader.load_courses()
>>>>>>> deployment

    constraints = get_constraints_from_session()
    no_class_constraints = get_no_class_constraints_from_session()

<<<<<<< HEAD
    # Load the schedule for the selected program
    schedule = course_loader.get_schedule(program_name)

    if request.method == 'POST':
        if 'course_id' in request.form:
            course_id = request.form['course_id']
=======
    # Load schedule for the target program of this step
    schedule = defaultdict(lambda: defaultdict(list))
    if target_program:
        schedule = course_loader.get_schedule(target_program)

    if request.method == 'POST':
        # Handle Constraint Addition (Add to Session)
        if 'course_id' in request.form:
            course_id = request.form['course_id']
            # We need to find the course object. 
            # If it's not in `all_courses` (current step), we can't add it.
            # But wait, if I'm in Step 3 and I remove a Step 2 constraint, 
            # I need `constraints` list to handle it.
            # The removal logic uses `constraints` list which is loaded from session.
            # So removal works fine.
            # Addition only happens from the displayed options (which are in `all_courses`).
>>>>>>> deployment
            for c in all_courses:
                if c.id == course_id and c not in constraints:
                    constraints.append(c)
            save_constraints_to_session(constraints)

        if 'remove_course_id' in request.form:
            remove_id = request.form['remove_course_id']
            constraints = [c for c in constraints if c.id != remove_id]
            save_constraints_to_session(constraints)

        if 'no_class_day' in request.form and 'no_class_time' in request.form:
            day = request.form['no_class_day']
            time = request.form['no_class_time']
            if (day, time) not in no_class_constraints:
                no_class_constraints.append((day, time))
                save_no_class_constraints_to_session(no_class_constraints)

        if 'no_class_day_remove' in request.form and 'no_class_time_remove' in request.form:
            rd, rt = request.form['no_class_day_remove'], request.form['no_class_time_remove']
            no_class_constraints = [(d, t) for (d, t) in no_class_constraints if not (d == rd and t == rt)]
            save_no_class_constraints_to_session(no_class_constraints)

<<<<<<< HEAD
      
=======
        if 'toggle_partial' in request.form:
            session['allow_partial'] = not session.get('allow_partial', False)
            session.modified = True
            
        # Redirect to same step after POST
        return redirect(url_for('schedule', step=current_step))
    
    # Load Configuration (Time Slots and Days)
    time_slots = {}
    days = []
    all_unique_slots = []
    
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
            days = config.get('days', [])
            raw_slots = config.get('time_slots', {})
            
            if isinstance(raw_slots, list):
                for d in days:
                    time_slots[d] = raw_slots
                all_unique_slots = sorted(list(set(raw_slots)))
            else:
                time_slots = raw_slots
                unique = set()
                for d_slots in time_slots.values():
                    unique.update(d_slots)
                all_unique_slots = sorted(list(unique))
                
    except (FileNotFoundError, json.JSONDecodeError):
        default_slots = ['08:30-09:45','10:00-11:15','11:30-12:45','13:00-14:15','14:30-15:45','16:00-17:15','17:30-18:45']
        days = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday']
        all_unique_slots = default_slots
        for d in days:
            time_slots[d] = default_slots

>>>>>>> deployment
    return render_template(
        'schedule.html',
        program_name=program_name,
        schedule=schedule,
        highlighted_course_ids=highlighted_course_ids,
        constraints=constraints,
<<<<<<< HEAD
        no_class_constraints=no_class_constraints
=======
        no_class_constraints=no_class_constraints,
        allow_partial=session.get('allow_partial', False),
        time_slots=time_slots,
        all_unique_slots=all_unique_slots,
        days=days,
        current_step=current_step,
        total_steps=total_steps,
        step_title=step_title
>>>>>>> deployment
    )


@app.route('/clear_constraints', methods=['POST'])
def clear_constraints():
    save_constraints_to_session([])
    return redirect(url_for('schedule'))

@app.route('/clear_no_class_constraints', methods=['POST'])
def clear_no_class_constraints():
    save_no_class_constraints_to_session([])
    return redirect(url_for('schedule'))



<<<<<<< HEAD
@app.route('/make_schedule', methods=['GET', 'POST'])
def make_schedule():
    # Here you can render a form to choose the constraint satisfaction algorithm
    if request.method == 'POST':
        # handle algorithm selection and perform scheduling
        algorithm = request.form.get('algorithm')
        # implement scheduling logic with the selected algorithm
        return redirect(url_for('schedule'))
    
    return render_template('make_schedule.html')

@app.route('/ac3_schedule', methods=['GET','POST'])
def ac3_schedule():
    # Load courses and both kinds of constraints
    course_loader = CourseDataLoader('courses.json')
    session_course_constraints = get_constraints_from_session() 
    session_no_class = get_no_class_constraints_from_session()

    # Initialize AC-3 with no-class constraints, too
    ac3_algo = AC3(
        courses=course_loader.load_courses(),
        cid_constraints=course_loader.get_course_id_constraint_mapping(),
        session_constraints=session_course_constraints,
        no_class_constraints=session_no_class
=======
@app.route('/quick_schedule_no_constraints', methods=['POST'])
def quick_schedule_no_constraints():
    save_constraints_to_session([])
    save_no_class_constraints_to_session([])
    return redirect(url_for('ac3_schedule'))


@app.route('/ac3_schedule', methods=['GET','POST'])
def ac3_schedule():
    program_name = session.get('program_name')
    if not program_name:
        return redirect(url_for('select_program'))

    course_loader = CourseDataLoader(['program_core.json', 'electives.json', 'ns_electives.json'])
    session_course_constraints = get_constraints_from_session() 
    session_no_class = get_no_class_constraints_from_session()
    allow_partial = session.get('allow_partial', False)

    # 1. Load Program Requirements
    try:
        with open('program_requirements.json', 'r') as f:
            all_requirements = json.load(f)
            program_reqs = all_requirements.get(program_name, {})
            if not program_reqs:
                program_reqs = all_requirements.get(program_name.replace(" ", ""), {})
    except FileNotFoundError:
        program_reqs = {}
    
    print(f"DEBUG: Program Requirements for {program_name}: {program_reqs}")

    # 2. Build Domains and Constraint Map
    domains = {}
    full_mapping = course_loader.get_course_id_constraint_mapping()
    active_cid_constraints = {} # Map for AC3 (ID -> Constraints)
    
    # Prepare forbidden set for O(1) lookup
    forbidden_slots = {f"{d} {t}" for d, t in session_no_class}

    # Helper to check if a course ID is valid (no conflict with forbidden slots)
    def is_id_valid(cid):
        constraints = full_mapping[cid]['constraints']
        # If ANY slot matches forbidden, it's invalid
        for slot in constraints:
            if slot in forbidden_slots:
                return False
        return True

    # A. Core Courses
    program_courses = course_loader.load_courses_by_program(program_name)
    print(f"DEBUG: Found {len(program_courses)} raw core courses for {program_name}")
    
    # Group core by name to build domains
    core_grouped = defaultdict(set) # Use set to prevent duplicates
    for c in program_courses:
        # Only consider valid IDs
        if is_id_valid(c.id):
            core_grouped[c.name].add(c.id)
            active_cid_constraints[c.id] = full_mapping[c.id]
        
    for name, ids in core_grouped.items():
        # Check if user picked specific sections (session_constraints)
        picked_ids = [sc.id for sc in session_course_constraints if sc.name == name]
        if picked_ids:
            # Let's filter picked IDs too to be safe/consistent.
            valid_picked = [pid for pid in picked_ids if is_id_valid(pid)]
            if valid_picked:
                 domains[name] = list(set(valid_picked)) # Ensure unique
            else:
                 domains[name] = [] 
        else:
            domains[name] = list(ids) # Convert set to list
            
    print(f"DEBUG: Constructed Core Domains: {list(domains.keys())}")

    # B. Elective Slots
    for pool_name, count in program_reqs.items():
        pool_courses = course_loader.load_courses_by_program(pool_name)
        print(f"DEBUG: Found {len(pool_courses)} courses for pool '{pool_name}'")
        if not pool_courses:
            continue
            
        # Filter pool IDs (use set to distinct)
        pool_ids = list({c.id for c in pool_courses if is_id_valid(c.id)})
        print(f"DEBUG: Valid IDs for '{pool_name}': {len(pool_ids)}")
        
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
            
        # Create N slots
        for i in range(1, count + 1):
            var_name = f"{pool_name} {i}"
            
            # If we have a user pick for this slot index
            if i <= len(picked_for_pool):
                domains[var_name] = [picked_for_pool[i-1]]
            else:
                # IMPORTANT: Remove already picked items from the general pool 
                # to prevent "same subject" conflicts if the user didn't pick enough
                remaining_ids = [pid for pid in pool_ids if pid not in seen_picked]
                domains[var_name] = remaining_ids
    
    print(f"DEBUG: Final Domains Keys: {list(domains.keys())}")

    # Determine skip_ac3
    skip_ac3 = (not session_course_constraints and not session_no_class)

    # Initialize AC-3
    ac3_algo = AC3(
        courses=[], # Not used when domains/constraints provided explicitly
        cid_constraints=active_cid_constraints,
        session_constraints=session_course_constraints,
        no_class_constraints=session_no_class,
        allow_partial=allow_partial,
        skip_ac3=skip_ac3,
        domains=domains
>>>>>>> deployment
    )

    # Run and store
    solutions = ac3_algo.solve()
<<<<<<< HEAD
=======
    
    # Fallback logic remains same...
    if not solutions and not allow_partial:
        print("DEBUG: No complete schedules found. Retrying with partial schedules enabled.")
        ac3_algo_partial = AC3(
            courses=[],
            cid_constraints=active_cid_constraints, # Use the same expanded map
            session_constraints=session_course_constraints,
            no_class_constraints=session_no_class,
            allow_partial=True,
            domains=domains # Pass the same domains
        )
        solutions = ac3_algo_partial.solve()
        session['auto_partial_fallback'] = True
    else:
        session.pop('auto_partial_fallback', None)

>>>>>>> deployment
    session['ac3_solutions'] = solutions
    session['ac3_progress'] = ac3_algo.progress

    return redirect(url_for('generated_schedules'))


<<<<<<< HEAD
=======
def get_processed_schedules(solutions, program_name, args):
    # Filter/Sort Parameters
    sort_by = args.get('sort_by', 'count') 
    filter_days = args.get('filter_days', '')
    
    # Retrieve dynamic priorities (Max 20 to prevent abuse)
    priority_instructors = []
    for i in range(1, 21):
        val = args.get(f'preferred_instructor_{i}', '').strip()
        if val:
            priority_instructors.append(val)

    course_loader = CourseDataLoader(['program_core.json', 'electives.json', 'ns_electives.json'])
    course_id_mapping = course_loader.get_course_id_constraint_mapping()
    
    # Get total courses count
    total_program_courses = 0
    if program_name:
        program_courses = course_loader.load_courses_by_program(program_name)
        unique_names = {c.name for c in program_courses}
        total_program_courses = len(unique_names)

    schedule_data = []
    all_instructors = set()

    # Process all solutions
    for idx, sol in enumerate(solutions):
        grid = defaultdict(lambda: defaultdict(list))
        flat_courses = [] # For CSV export and sorting within schedule
        count = 0
        days_with_classes = set()
        instructors_in_schedule = set()
        
        # Helper to parse time to minutes
        def to_minutes(t_str):
            h, m = map(int, t_str.split(':'))
            return h * 60 + m

        day_intervals = defaultdict(list)

        for var, cid in sol.items():
            count += 1
            course_info = course_id_mapping.get(cid)
            if course_info:
                name = course_info['course_name']
                instructor = course_info.get('instructor', '')
                if instructor:
                    all_instructors.add(instructor)
                    instructors_in_schedule.add(instructor)
                
                for slot in course_info['constraints']:
                    parts = slot.split(' ')
                    if len(parts) >= 2:
                        day = parts[0]
                        time = parts[1]
                        
                        # Store for grid
                        grid[time][day].append({'id': cid, 'name': name, 'instructor': instructor})
                        
                        # Store for gap calculation
                        start_str, end_str = time.split('-')
                        day_intervals[day].append((to_minutes(start_str), to_minutes(end_str)))

                        # Store for flat list
                        flat_courses.append({
                            'id': cid, 
                            'name': name, 
                            'instructor': instructor, 
                            'day': day, 
                            'time': time
                        })
                        days_with_classes.add(day)
        
        # Calculate Total Gaps
        total_gaps_minutes = 0
        for day, intervals in day_intervals.items():
            intervals.sort() # Sort by start time
            for i in range(1, len(intervals)):
                prev_end = intervals[i-1][1]
                curr_start = intervals[i][0]
                gap = curr_start - prev_end
                if gap > 0:
                    total_gaps_minutes += gap

        num_days = len(days_with_classes)
        
        if filter_days and str(num_days) != filter_days:
            continue

        # Calculate matches for 5 priorities
        priority_matches = []
        for p_inst in priority_instructors:
            if p_inst and p_inst in instructors_in_schedule:
                priority_matches.append(1)
            else:
                priority_matches.append(0)

        schedule_data.append({
            'schedule_index': idx + 1, # Original index
            'grid': grid,
            'flat_courses': flat_courses,
            'count': count,
            'is_partial': count < total_program_courses,
            'num_days': num_days,
            'total_gaps': total_gaps_minutes,
            'priority_matches': priority_matches
        })

    # Sorting Logic
    def sort_key(x):
        matches_tuple = tuple(x['priority_matches'])
        if sort_by == 'days':
            return matches_tuple + (-x['num_days'], x['count'], -x['total_gaps'])
        elif sort_by == 'gaps':
            # Fewest Gaps (-total_gaps -> wait, we want Smallest gaps. Ascending.)
            # But we are using reverse=True (Descending).
            # So negate gap: -10 gaps > -100 gaps. (Fewest is "biggest" negative number).
            return matches_tuple + (-x['total_gaps'], x['count'], -x['num_days'])
        else: # 'count'
            return matches_tuple + (x['count'], -x['num_days'], -x['total_gaps'])

    schedule_data.sort(key=sort_key, reverse=True)
    
    return schedule_data, total_program_courses, sorted(list(all_instructors))


>>>>>>> deployment
@app.route('/generated_schedules', methods=['GET'])
def generated_schedules():
    solutions = session.get('ac3_solutions', [])
    progress = session.get('ac3_progress', [])
<<<<<<< HEAD
    all_rows = [] 

    course_loader = CourseDataLoader('courses.json')
    course_id_mapping = course_loader.get_course_id_constraint_mapping()
    idx=0
    schedule_tables = []
    for sol in solutions:
        
        rows = []
        for var, cid in sol.items():
            course_info = course_id_mapping.get(cid)
            if course_info:
                course_name = course_info['course_name']
                constraints = course_info['constraints']
                row = {
                    'id': cid,
                    'name': course_name,
                    'constraints': constraints  # List of "Day Time" strings
                }
                rows.append(row)
        schedule_tables.append(rows)
        # Add to master list for CSV, with a header row for each solution
    #     df = pd.DataFrame(rows)
    #     df.insert(0, 'Solution', f'Solution #{idx + 1}')
    #     all_rows.append(df)

    #     # Add a blank row (gap) between solutions
    #     all_rows.append(pd.DataFrame([[""] * len(df.columns)], columns=df.columns))
    #     idx+=1

    # # Concatenate all into a single DataFrame and save to CSV
    # final_df = pd.concat(all_rows, ignore_index=True)
    # final_df.to_csv("generated_schedules.csv", index=False)

    return render_template('generated_schedules.html',
                           schedule_tables=schedule_tables,
                           progress=progress)
=======
    program_name = session.get('program_name', '')
    
    # Use helper to process schedules
    schedule_data, total_program_courses, all_instructors = get_processed_schedules(solutions, program_name, request.args)
    
    # Get params for template
    sort_by = request.args.get('sort_by', 'count') 
    filter_days = request.args.get('filter_days', '')
    
    # Reconstruct the list of priorities to repopulate the UI
    priority_instructors = []
    for i in range(1, 21):
        val = request.args.get(f'preferred_instructor_{i}', '').strip()
        if val:
            priority_instructors.append(val)
            
    course_loader = CourseDataLoader(['program_core.json', 'electives.json', 'ns_electives.json'])
    highlighted_course_ids = course_loader.get_highlighted_course_ids()

    # Check if filtering resulted in empty set
    filter_empty = (len(schedule_data) == 0 and len(solutions) > 0)

    return render_template('generated_schedules.html',
                           schedule_data=schedule_data,
                           progress=progress,
                           highlighted_course_ids=highlighted_course_ids,
                           total_courses=total_program_courses,
                           auto_partial_fallback=session.get('auto_partial_fallback', False),
                           current_sort=sort_by,
                           current_filter_days=filter_days,
                           current_priorities=priority_instructors,
                           all_instructors=all_instructors,
                           filter_empty=filter_empty)


@app.route('/export_schedules', methods=['GET'])
def export_schedules():
    solutions = session.get('ac3_solutions', [])
    if not solutions:
        return redirect(url_for('generated_schedules'))

    program_name = session.get('program_name', '')
    
    # Reuse the same processing logic to get filtered & sorted schedules
    schedule_data, _, _ = get_processed_schedules(solutions, program_name, request.args)
    
    csv_rows = []
    
    # Helper for sorting days
    days_order = {'Monday': 1, 'Tuesday': 2, 'Wednesday': 3, 'Thursday': 4, 'Friday': 5, 'Saturday': 6, 'Sunday': 7}
    
    for idx, item in enumerate(schedule_data):
        # Summary Header for each schedule
        csv_rows.append([f"Schedule #{idx + 1}"])
        csv_rows.append([f"Courses: {item['count']}", f"Days: {item['num_days']}"])
        
        # Column Headers
        csv_rows.append(["Day", "Time", "Course Name", "Instructor", "Course ID"])
        
        # Sort courses: Day first, then Time
        courses = item['flat_courses']
        courses.sort(key=lambda c: (days_order.get(c['day'], 99), c['time']))
        
        for c in courses:
            csv_rows.append([c['day'], c['time'], c['name'], c['instructor'], c['id']])
            
        # Blank row separation
        csv_rows.append([])
        csv_rows.append([])

    # Convert to CSV string
    def generate():
        for row in csv_rows:
            # Simple CSV formatting: quote fields, comma separated
            yield ','.join(f'"{str(x)}"' for x in row) + '\n'

    from flask import Response
    return Response(generate(), mimetype='text/csv', headers={"Content-Disposition": "attachment;filename=generated_schedules.csv"})

>>>>>>> deployment





# @app.route('/generated_schedules', methods=['GET'])
# def generated_schedules():
#     solutions = session.get('ac3_solutions', [])
#     progress = session.get('ac3_progress', [])

#     course_loader = CourseDataLoader('courses.json')
#     course_id_mapping = course_loader.get_course_id_constraint_mapping()

#     schedule_tables = []
#     all_rows = []  # To collect rows for CSV

#     for idx, sol in enumerate(solutions):
#         rows = []
#         for var, cid in sol.items():
#             course_info = course_id_mapping.get(cid)
#             if course_info:
#                 course_name = course_info['course_name']
#                 constraints = course_info['constraints']  # List of "Day Time" strings
#                 row = {
#                     'ID': cid,
#                     'Name': course_name,
#                     'Constraints': ", ".join(constraints)
#                 }
#                 rows.append(row)
#         schedule_tables.append(rows)

#         # Add to master list for CSV, with a header row for each solution
#         df = pd.DataFrame(rows)
#         df.insert(0, 'Solution', f'Solution #{idx + 1}')
#         all_rows.append(df)

#         # Add a blank row (gap) between solutions
#         all_rows.append(pd.DataFrame([[""] * len(df.columns)], columns=df.columns))

#     # Concatenate all into a single DataFrame and save to CSV
#     final_df = pd.concat(all_rows, ignore_index=True)
#     final_df.to_csv("generated_schedules.csv", index=False)

#     return render_template('generated_schedules.html',
#                            schedule_tables=schedule_tables,
#                            progress=progress)


<<<<<<< HEAD
@app.route('/pso_schedule', methods=['GET', 'POST'])
def pso_schedule():
    if request.method == 'POST':
        try:
            # 1) Parse numeric and weight inputs
            num_students          = int(request.form['num_students'])
            num_courses           = int(request.form['num_courses'])
            num_particles         = int(request.form['num_particles'])
            max_iterations        = int(request.form['max_iterations'])
            inertia_weight        = float(request.form['inertia_weight'])
            cognitive_coefficient = float(request.form['cognitive_coefficient'])
            social_coefficient    = float(request.form['social_coefficient'])
            preference_weight     = float(request.form['preference_weight'])
            time_weight           = float(request.form['time_weight'])
            label_weight          = float(request.form['label_weight'])
            capacity_weight       = float(request.form['capacity_weight'])
            course_load_weight    = float(request.form['course_load_weight'])
            seed                 =int(request.form['seed'])

            # 2) Parse list‐like inputs
            student_preferences = ast.literal_eval(request.form['student_preferences'])
            course_times         = ast.literal_eval(request.form['course_times'])
            course_caps          = ast.literal_eval(request.form['course_caps'])

            # 3) Robustly parse course labels
            raw_labels = request.form.getlist('course_labels')
            if len(raw_labels) == 1:
                try:
                    parsed = ast.literal_eval(raw_labels[0])
                    course_labels = [str(l).strip() for l in parsed] if isinstance(parsed, list) \
                                    else [l.strip() for l in raw_labels[0].split(',')]
                except:
                    course_labels = [l.strip() for l in raw_labels[0].split(',')]
            else:
                course_labels = [str(l).strip() for l in raw_labels]

            # 4) Validate lengths
            if len(course_labels) != num_courses:
                return render_template('pso_schedule.html', error="Number of course labels must match number of courses.")
            if len(course_caps) != num_courses:
                return render_template('pso_schedule.html', error="Number of course capacities must match number of courses.")
            if len(student_preferences) != num_students:
                return render_template('pso_schedule.html', error="Number of student preference lists must match number of students.")
            if len(course_times) != num_courses:
                return render_template('pso_schedule.html', error="Number of course times must match number of courses.")

            # 5) Run PSO
            pso = BinaryPSO(
                num_students, num_courses, num_particles, max_iterations,
                inertia_weight, cognitive_coefficient, social_coefficient,
                student_preferences, course_times, course_labels, course_caps,
                preference_weight, time_weight, label_weight, capacity_weight,
                course_load_weight, seed
            )
            best_solution, best_fitness = pso.run()
            enrollment_matrix = best_solution.tolist()
            course_names      = [f"Course {i+1}" for i in range(num_courses)]
            student_names     = [f"Student {i+1}" for i in range(num_students)]

            # 6) Build time_conflicts
            time_conflicts = [[[] for _ in range(num_courses)] for _ in range(num_students)]
            for i in range(num_students):
                for c1 in range(num_courses):
                    for c2 in range(c1+1, num_courses):
                        if check_time_conflict(course_times[c1], course_times[c2]):
                            time_conflicts[i][c1].append(c2)
                            time_conflicts[i][c2].append(c1)

            # 7) Precompute violation_matrix with CSS classes
            priority_map = {
                'label':      'bg-red-100',
                'time':       'bg-orange-100',
                'capacity':   'bg-yellow-100',
                'preference': 'bg-blue-100',
                'none':       'bg-green-100'
            }
            # count enrollments per course
            course_counts = [sum(row[j] for row in enrollment_matrix) for j in range(num_courses)]
            violation_matrix = []
            for i in range(num_students):
                # labels for selected courses
                selected = [j for j in range(num_courses) if enrollment_matrix[i][j] == 1]
                label_counts = {}
                for j in selected:
                    lab = course_labels[j]
                    label_counts[lab] = label_counts.get(lab, 0) + 1

                row_classes = []
                for j in range(num_courses):
                    if enrollment_matrix[i][j] == 0:
                        row_classes.append('')  # not enrolled
                        continue

                    vio = set()
                    # preference violation
                    if j not in student_preferences[i]:
                        vio.add('preference')
                    # capacity violation
                    if course_counts[j] > course_caps[j]:
                        vio.add('capacity')
                    # time conflict violation
                    if any(other in time_conflicts[i][j] for other in selected):
                        vio.add('time')
                    # label conflict violation
                    if label_counts.get(course_labels[j], 0) > 1:
                        vio.add('label')

                    # pick highest‐priority violation
                    for key in ('label','time','capacity','preference'):
                        if key in vio:
                            row_classes.append(priority_map[key])
                            break
                    else:
                        row_classes.append(priority_map['none'])

                violation_matrix.append(row_classes)

            # 8) Render with precomputed matrices
            return render_template('pso_results.html',
                enrollment_matrix=enrollment_matrix,
                violation_matrix=violation_matrix,
                course_names=course_names,
                student_names=student_names,
                best_fitness=best_fitness,
                course_labels=course_labels,
                course_caps=course_caps,
                preference_weight=preference_weight,
                time_weight=time_weight,
                label_weight=label_weight,
                capacity_weight=capacity_weight,
                course_load_weight=course_load_weight,
                student_preferences=student_preferences,
                course_times=course_times,
                time_conflicts=time_conflicts
            )

        except Exception as e:
            return render_template('pso_schedule.html', error=f"Invalid input format: {e}")

    # GET method
    return render_template('pso_schedule.html')


@app.route('/algorithm_handler', methods=['POST'])
def algorithm_handler():
    selected_algorithm = request.form['algorithm']
    
    if selected_algorithm == 'ac-3':
        return redirect(url_for('ac3_schedule'))  # Redirect to the AC-3 scheduling page
    elif selected_algorithm == 'pso':
        return redirect(url_for('pso_schedule'))  # Redirect to the PSO scheduling page
    else:
        return redirect(url_for('index'))  # Fallback to the index page if the algorithm is unrecognized

=======
>>>>>>> deployment

if __name__ == '__main__':
    app.run(debug=True)
