#!/usr/bin/env python3
"""
Extract the Fall 2026 undergraduate timetable from the IBA workbook into the three
JSON files the scheduler reads: program_core.json, electives.json, ns_electives.json.

Offline one-off tool. Uses the standard library only (zipfile + ElementTree read the
xlsx parts directly) so it adds no runtime dependency for Render.

Usage:
    python3 tools/extract_fall2026.py             # write the JSON files
    python3 tools/extract_fall2026.py --check     # parse and report, write nothing
"""

import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKBOOK = os.path.join(ROOT, 'Fall Schedule 2026.xlsx')
SHEET = 'xl/worksheets/sheet1.xml'

# Column groups in the undergrad sheet. Each group covers TWO days: a cell in the
# "Monday / Wednesday" block means the class meets on Monday AND on Wednesday,
# unless the cell text says otherwise.
#   (days, course_name_col, program_col, room_col, ums_id_col, teacher_col)
COLUMN_GROUPS = [
    (('Monday', 'Wednesday'), 2, 3, 4, 6, 7),
    (('Tuesday', 'Thursday'), 8, 9, 10, 11, 12),
    (('Friday', 'Saturday'), 13, 14, 15, 16, 17),
]

DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

# Pools that become the general / NS elective pool. Anything here that is not
# restricted to a specific cohort is selectable as a general elective.
GENERAL_POOLS = {
    'NS',
    'Social Science Elective',
    'Finance Elective',
    'Marketing Elective',
    'Management Elective',
    'Economics Elective',
    'Accounting Elective',
    'Business Analytics Elective',
    'Mathematics Elective',
}
CS_POOL = 'Computer Science Elective'

# Cohort labels such as "BSCS - 7" / "BBA - 3".
COHORT_RE = re.compile(r'^(BS[A-Z]*|BBA)\s*-\s*\d+$', re.I)

# Rows that are not bookable undergraduate classes.
SKIP_NAME_RE = re.compile(
    r'^\s*(reserved\b|ms\s|mba\b|emba\b|new course\b|teacher to be)', re.I)

DAY_WORD_RE = re.compile(
    r'\b(mon|tues?|wed(?:nes)?|wdnes|thur?s?|fri|satur)(?:day)?s?\b', re.I)
DAY_WORD_MAP = {
    'mon': 'Monday', 'tue': 'Tuesday', 'tues': 'Tuesday',
    'wed': 'Wednesday', 'wednes': 'Wednesday', 'wdnes': 'Wednesday',
    'thur': 'Thursday', 'thurs': 'Thursday', 'thu': 'Thursday',
    'fri': 'Friday', 'satur': 'Saturday',
}

# "8:30 AM to 11:15 AM", "9:00 t0 11:30", "10:30 am - 11:45 am", "1:00 to 2:15"
TIME_RANGE_RE = re.compile(
    r'(\d{1,2})[:;](\d{2})\s*(am|pm)?\s*(?:-|--|–|to|t0)\s*(\d{1,2})[:;](\d{2})\s*(am|pm)?',
    re.I)

RESTRICTION_RE = re.compile(r'\(\s*(open\s*to\s*all|only\s+bs[a-z]+)\s*\)?', re.I)

# The workbook spells the same thing several ways. Left untouched, the solver would
# treat "French 1 (Langugae)" and "French-1 (Language)" as two different subjects and
# happily put both in one schedule.
NAME_FIXUPS = [
    (re.compile(r'\bLangugae\b', re.I), 'Language'),
    (re.compile(r'^(Arabic|French|Chinese|Persian|Turkish|Spanish)\s+(\d)', re.I),
     r'\1-\2'),
    (re.compile(r'\+[A-Z]\d+:[A-Z]\d+'), ''),        # stray Excel range artefact
    (re.compile(r'\bSuatainablity\b', re.I), 'Sustainability'),
    (re.compile(r'\bto\s*All\b', re.I), 'to All'),
]
ROOM_FIXUPS = [(re.compile(r'\bTestimg\b', re.I), 'Testing')]

# Cells the heuristics get wrong. Keyed by (excel_row, group_index); the value
# replaces the parsed segment list. None means "drop this cell entirely".
MANUAL_OVERRIDES = {
    # Two unrelated lab sections crammed into one cell, teacher list order reversed.
    (79, 2): [('Database Systems (Lab)', 'Ms. Abeera Tariq', ['Friday'], None),
              ('Database Systems (Lab)', 'TBA', ['Saturday'], None)],
    (248, 2): [('Data Structures (Lab)', 'Dr Imran Rauf', ['Friday'], None),
               ('Data Structures (Lab)', 'TBA', ['Saturday'], None)],
    (77, 2): [('Data Structures (Lab)', 'TBA', ['Friday'], None),
              ('Database Systems (Lab)', 'Ms. Maria Rahim Khowaja', ['Saturday'], None)],
}


# --------------------------------------------------------------------------- xlsx

def col_index(ref):
    n = 0
    for ch in ref:
        if ch.isalpha():
            n = n * 26 + ord(ch.upper()) - 64
        else:
            break
    return n


def read_sheet(path):
    """Yield (excel_row_number, {col_index: text}) with column A forward-filled."""
    z = zipfile.ZipFile(path)
    shared = []
    if 'xl/sharedStrings.xml' in z.namelist():
        sst = ET.fromstring(z.read('xl/sharedStrings.xml'))
        shared = [''.join(t.text or '' for t in si.iter(NS + 't'))
                  for si in sst.iter(NS + 'si')]
    sheet = ET.fromstring(z.read(SHEET))
    for row in sheet.iter(NS + 'row'):
        cells = {}
        for c in row.iter(NS + 'c'):
            v = c.find(NS + 'v')
            if v is None or v.text is None:
                continue
            text = shared[int(v.text)] if c.attrib.get('t') == 's' else v.text
            if text and text.strip():
                cells[col_index(c.attrib['r'])] = text
        yield int(row.attrib['r']), cells


# --------------------------------------------------------------------------- text

def norm_ws(s):
    return re.sub(r'\s+', ' ', (s or '').replace('\xa0', ' ')).strip()


def to_24h(hour, minute, meridiem):
    """Resolve a clock reading to 24h. Without an am/pm marker, 1-7 means PM."""
    hour = int(hour)
    minute = int(minute)
    if meridiem:
        meridiem = meridiem.lower()
        if meridiem == 'pm' and hour != 12:
            hour += 12
        elif meridiem == 'am' and hour == 12:
            hour = 0
    elif 1 <= hour <= 7:
        hour += 12
    return '%02d:%02d' % (hour, minute)


def parse_times(text):
    """All explicit time ranges in the text, as canonical 'HH:MM-HH:MM'."""
    out = []
    for m in TIME_RANGE_RE.finditer(text):
        h1, m1, ap1, h2, m2, ap2 = m.groups()
        # "10:00 to 11:15 & 11:30 to 12:45 pm" - a trailing marker applies to both ends.
        start = to_24h(h1, m1, ap1 or ap2)
        end = to_24h(h2, m2, ap2)
        if start < end:
            out.append('%s-%s' % (start, end))
    return out


def parse_days(text, default_days):
    """Days named in the text, else the column group's default pair."""
    found = []
    for m in DAY_WORD_RE.finditer(text):
        day = DAY_WORD_MAP.get(m.group(1).lower())
        if day and day not in found:
            found.append(day)
    return found or list(default_days)


def clean_name(text):
    """Strip scheduling qualifiers off a course title, keeping (Lab)/(Language)."""
    s = norm_ws(text)
    s = RESTRICTION_RE.sub(' ', s)
    # Parentheticals that carry a day or a time are scheduling notes, not the title.
    s = re.sub(r'\([^)]*\)', lambda m: ' ' if (
        DAY_WORD_RE.search(m.group(0)) or TIME_RANGE_RE.search(m.group(0))
        or re.search(r'double slot|including break', m.group(0), re.I)) else m.group(0), s)
    # Trailing "... Only Friday from 8:30 AM to 11:15 AM" / "... Friday Only 9:00 to 11:30"
    s = re.sub(r'[\s,;:-]*\b(only\s+' + DAY_WORD_RE.pattern[2:-2] + r'|'
               + DAY_WORD_RE.pattern[2:-2] + r'\s+only)\b.*$', '', s, flags=re.I)
    s = re.sub(r'[\s,;:-]*\b(from\s+)?\d{1,2}[:;]\d{2}\s*(am|pm)?\s*(?:-|to|t0)\s*.*$', '',
               s, flags=re.I)
    s = re.sub(r'[\s,;:-]*\bdouble slot\b.*$', '', s, flags=re.I)
    s = re.sub(r'[\s.,;:+-]+$', '', norm_ws(s))
    s = norm_ws(s)
    for pattern, repl in NAME_FIXUPS:
        s = pattern.sub(repl, s)
    if s and s == s.upper() and len(s) > 4:
        s = s.title()  # a few titles are shouted in all caps
    return norm_ws(s)


def clean_instructor(text):
    s = norm_ws(text)
    s = re.sub(r'^(Mr|Mrs|Ms|Dr)\.?\s*', lambda m: m.group(1) + '. ', s, flags=re.I)
    return norm_ws(s) or 'TBA'


def clean_room(text):
    s = norm_ws((text or '').replace('\n', ' '))
    for pattern, repl in ROOM_FIXUPS:
        s = pattern.sub(repl, s)
    return s


def split_segments(name_cell, teacher_cell):
    """Split a multi-course cell into (raw_name, teacher, extra_lines) segments."""
    lines = [norm_ws(l) for l in (name_cell or '').replace('\t', '\n').split('\n')]
    lines = [l for l in lines if l]
    teachers = [norm_ws(t) for t in (teacher_cell or '').split('\n')]
    teachers = [t for t in teachers if t]

    segments = []
    for line in lines:
        is_qualifier = bool(
            re.match(r'^(only\b|\(|from\b|\d{1,2}[:;]\d{2})', line, re.I)
            or re.match(r'^(' + DAY_WORD_RE.pattern[2:-2] + r')\b\s*[:;-]', line, re.I))
        if segments and is_qualifier:
            segments[-1][1].append(line)
        else:
            segments.append([line, []])

    out = []
    for i, (head, extra) in enumerate(segments):
        teacher = teachers[i] if i < len(teachers) else (teachers[0] if teachers else '')
        out.append((head, teacher, extra))
    return out


# --------------------------------------------------------------------------- build

def build_sections():
    """Parse the sheet into sections: dicts with name/program/instructor/room/meetings."""
    sections = []
    current_block = ''

    for rownum, cells in read_sheet(WORKBOOK):
        if 1 in cells:
            current_block = cells[1]
        block_times = parse_times(norm_ws(current_block))
        if not block_times:
            continue  # header, calendar footer, or a row above the grid
        block_time = block_times[0]

        for gi, (default_days, c_name, c_prog, c_room, c_id, c_teach) in enumerate(COLUMN_GROUPS):
            raw_name = cells.get(c_name, '')
            program = norm_ws(cells.get(c_prog, ''))
            if not norm_ws(raw_name) or not program:
                continue
            if program not in GENERAL_POOLS and program != CS_POOL \
                    and not any(COHORT_RE.match(p.strip()) for p in program.split(',')):
                continue

            room = clean_room(cells.get(c_room, ''))
            ums = norm_ws(cells.get(c_id, ''))
            ums = ums[:-2] if ums.endswith('.0') else ums
            if not re.fullmatch(r'\d{5,6}', ums):
                ums = ''  # that column also holds capacities and stray teacher names

            override = MANUAL_OVERRIDES.get((rownum, gi))
            if override is not None:
                parsed = [(nm, tch, dys, tms) for nm, tch, dys, tms in override]
            else:
                parsed = []
                for head, teacher, extra in split_segments(raw_name, cells.get(c_teach, '')):
                    text = ' '.join([head] + extra)
                    parsed.append((clean_name(head), teacher,
                                   parse_days(text, default_days),
                                   parse_times(text) or None))

            for name, teacher, days, times in parsed:
                if not name or SKIP_NAME_RE.match(name):
                    continue
                times = times or [block_time]
                meetings = sorted({(d, t) for d in days for t in times})
                restriction = ''
                m = RESTRICTION_RE.search(norm_ws(raw_name))
                if m:
                    restriction = norm_ws(m.group(1)).title()
                for prog in [p.strip() for p in program.split(',') if p.strip()]:
                    if prog == 'BBA':      # "Business Analytics Elective, BBA"
                        continue
                    sections.append({
                        'name': name,
                        'source_program': prog,
                        'instructor': clean_instructor(teacher),
                        'room': room,
                        'ums': ums,
                        'restriction': restriction,
                        'meetings': meetings,
                        'row': rownum,
                    })
    return sections


def merge_duplicates(sections):
    """Collapse rows that describe the same offering.

    A double-slot class is printed once per time block it spans, so the same section
    shows up on two rows. The instructor is deliberately left out of the key: the
    workbook spells some names two ways ("Ms. Kiran Khan Ali" / "Mr. Kiran Khan Ali"),
    and two different sections cannot occupy one room at one time anyway.
    """
    seen = {}
    out = []
    for s in sections:
        key = (s['name'], s['source_program'], s['room'], tuple(s['meetings']))
        if key in seen:
            if s['ums'] and not seen[key]['ums']:
                seen[key]['ums'] = s['ums']
            if seen[key]['instructor'] == 'TBA' and s['instructor'] != 'TBA':
                seen[key]['instructor'] = s['instructor']
            continue
        seen[key] = s
        out.append(s)
    return out


def assign_ids(sections):
    """UMS class number where it is present and unique, otherwise a stable F26-NNNN."""
    ums_counts = defaultdict(int)
    for s in sections:
        if s['ums']:
            ums_counts[s['ums']] += 1

    ordered = sorted(sections, key=lambda s: (s['name'], s['source_program'],
                                              s['instructor'], s['room'],
                                              tuple(s['meetings'])))
    used = set()
    seq = 0
    for s in ordered:
        if s['ums'] and ums_counts[s['ums']] == 1 and s['ums'] not in used:
            s['id'] = s['ums']
        else:
            seq += 1
            s['id'] = 'F26-%04d' % seq
        used.add(s['id'])
    return sections


def to_records(section, program_value, comment_bits):
    comments = ' | '.join([b for b in comment_bits if b])
    return [{
        'name': section['name'],
        'program': program_value,
        'instructor': section['instructor'],
        'id': section['id'],
        'room': section['room'],
        'day': day,
        'time': time,
        'comments': comments,
    } for day, time in section['meetings']]


def main():
    check_only = '--check' in sys.argv
    sections = assign_ids(merge_duplicates(build_sections()))

    core, cs_electives, general = [], [], []
    dropped_restricted = 0

    for s in sections:
        prog = s['source_program']
        if prog == CS_POOL:
            cs_electives += to_records(s, 'Elective',
                                       ['CS Elective', s['restriction'],
                                        'UMS %s' % s['ums'] if s['ums'] else ''])
        elif prog in GENERAL_POOLS:
            if re.search(r'only\s+bs', s['restriction'], re.I):
                dropped_restricted += 1
                continue
            general += to_records(s, 'NS-Elective',
                                  [prog, s['restriction'],
                                   'UMS %s' % s['ums'] if s['ums'] else ''])
        else:
            core += to_records(s, prog,
                               ['UMS %s' % s['ums'] if s['ums'] else ''])

    print('sections: %d  ->  core %d recs / CS elective %d recs / general %d recs'
          % (len(sections), len(core), len(cs_electives), len(general)))
    print('dropped %d cohort-restricted general electives' % dropped_restricted)

    print('\nBSCS - 7 core:')
    for r in sorted([r for r in core if r['program'] == 'BSCS - 7'],
                    key=lambda r: (r['time'], r['day'])):
        print('  %-8s %-32s %-10s %-9s %-28s %s'
              % (r['id'], r['name'], r['day'], r['time'], r['instructor'], r['room']))

    names = sorted({r['name'] for r in cs_electives})
    print('\nCS electives: %d distinct titles, %d sections'
          % (len(names), len({r['id'] for r in cs_electives})))
    for n in names:
        print('  -', n)

    print('\nGeneral elective pool: %d distinct titles, %d sections'
          % (len({r['name'] for r in general}), len({r['id'] for r in general})))

    problems = [r for r in core + cs_electives + general if not r['id'] or not r['time']]
    if problems:
        print('\n!! %d records with a missing id or time' % len(problems))

    if check_only:
        return

    for filename, data in (('program_core.json', core),
                           ('electives.json', cs_electives),
                           ('ns_electives.json', general)):
        path = os.path.join(ROOT, filename)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
            f.write('\n')
        print('wrote %s (%d records)' % (filename, len(data)))


if __name__ == '__main__':
    main()
