# IBA Course Planner

Builds every clash-free Fall 2026 timetable for an IBA Karachi student. You block the hours you
can't attend and lock in sections you want. The planner enumerates every combination of the
remaining sections with Google OR-Tools CP-SAT and ranks the results by days on campus, gaps
between classes, or preferred instructors.

**Live demo:** _add the Render URL after the first deploy_

> **AI disclosure.** AI assistants (Claude, by Anthropic) wrote or heavily refactored large parts
> of this project, then the author reviewed it. That covers the CP-SAT model, the Flask routes,
> the HTMX/Tailwind interface, the data extraction script, the tests and this README. The
> project's idea, curriculum data choices and testing were directed by the author, and every
> AI-written change was read and run before it was committed. Treat it as a portfolio project,
> not as official university software.

> **Data disclaimer.** The section data comes from the published Fall 2026 timetable workbook
> (`data/Fall Schedule 2026.xlsx`). Sections can move or close, so always confirm on the official
> portal before you register. The calendar export assumes the term runs from 24 Aug to 12 Dec 2026
> (UTC+5). Change `term` in `config.json` if the academic calendar says otherwise.

## What it does

1. **Choose a program and semester**, for example `BSCS - 7`. This sets the core courses and how
   many electives you need.
2. **Block busy hours.** Click cells in the weekly grid. Any section meeting in a blocked hour is
   ruled out.
3. **Pick core sections, electives and NS electives**, or pick none. Picked sections are locked
   in. Courses you leave open get whichever section fits. The large NS-elective pool is searchable.
4. **Find timetables.** Results can be filtered by days on campus and ranked by fewest days, fewest
   gaps, or a ranked list of preferred instructors. If no complete timetable exists, the planner
   shows the ones that drop the fewest courses and lists what's missing.
5. **Export** one timetable as an `.ics` calendar file, or export one or all of them as CSV.

## How the solver works

Each required course becomes a CP-SAT variable whose domain is that course's open sections. The
constraints are:

- no two chosen sections overlap in time;
- the same subject is never taken twice;
- interchangeable elective slots are symmetry-broken, so a timetable never appears twice in a
  different order.

The solver enumerates all solutions, capped at 500. If none exist and partial timetables are
allowed, it maximises the number of placed courses and enumerates every solution of that size.
`tools/verify_solver.py` holds headless regression checks for the solver and the ranking.

## Stack

- Python 3.11, Flask 3, Flask-Session, Flask-Limiter
- Google OR-Tools CP-SAT
- Jinja templates, Tailwind (Play CDN) and HTMX 1.9 for partial page swaps. No build step.
- Gunicorn on Render's free tier

## Run locally

```bash
pip install -r requirements.txt
python app.py            # http://localhost:5000
python tools/verify_solver.py
```

## Deploy (Render)

`render.yaml` defines a single free web service (one Gunicorn worker, four threads). Create a
Blueprint from the repo and set:

| Variable      | Purpose                                                                |
|---------------|------------------------------------------------------------------------|
| `SECRET_KEY`  | Session signing. Render generates it.                                  |
| `ADMIN_TOKEN` | Enables `/admin?token=…`. Without it, the admin page returns 404.      |

Free instances sleep when idle, so the first request after a while takes ~30 s. The disk is
ephemeral: edits made on `/admin` are lost on redeploy. Change the JSON files in the repo instead.

## Data files

| File                       | Contents                                                   |
|----------------------------|------------------------------------------------------------|
| `program_core.json`        | Core-course sections, tagged by program and semester       |
| `electives.json`           | General-elective sections                                  |
| `ns_electives.json`        | NS-elective sections                                       |
| `program_requirements.json`| Core and elective counts per program                       |
| `config.json`              | Days, time slots and term dates                            |
| `data/`                    | Source timetable workbook                                  |
| `archive/`                 | Older data files that the app no longer reads              |

`tools/extract_fall2026.py` regenerates the course JSON from the workbook.

## Project layout

- `app.py`: Flask routes, the wizard, result ranking and exports
- `cpsat_solver.py`: the CP-SAT model and solution enumeration
- `templates/`: `base.html` layout, home, program choice, planner, results and admin pages
- `tools/`: data extraction and solver checks

## License

MIT
