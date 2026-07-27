# AI-Driven University Scheduler

A comprehensive automated scheduling system designed to solve complex resource allocation and timetabling problems for universities. This project utilizes constraint satisfaction techniques to generate valid, conflict-free course timetables.

## Features

- **Automated Scheduling:** Generates university course schedules while minimizing conflicts.
- **Constraint Satisfaction:** Models the scheduling problem as a Constraint Satisfaction Problem (CSP).
- **Algorithms:**
  - **CP-SAT (Google OR-Tools):** The CSP is handed to OR-Tools' CP-SAT solver, which enumerates every conflict-free schedule exactly once. Interchangeable elective slots are symmetry-broken so the same schedule is never reported twice in a different order.
  - **Partial schedules:** When no complete schedule fits, the solver maximises the number of courses it can place and returns all schedules of that size.
- **Web Interface:** A Flask-based web application provides an interactive interface for uploading data, generating schedules, and viewing results.

## Tech Stack

- **Backend:** Python, Flask
- **Solver:** Google OR-Tools (CP-SAT)
- **Frontend:** HTML/CSS (Jinja2 templates)

## Installation & Usage

### 1. Prerequisites
- Python 3.8 or higher.
- `pip` (Python package installer).

### 2. Setup
Clone the repository and install dependencies:
```bash
git clone <repository-url>
cd ai-scheduler-deployment
pip install -r requirements.txt
```

### 3. Running the Application
Start the Flask server:
```bash
python app.py
```
The application will be accessible at `http://localhost:5000`.

### 4. Data Setup & Workflow
The scheduler requires specific data files to function. These can be managed directly through the web interface on the landing page:

1.  **Configure Days & Slots:** Define the working days and time slots (e.g., "Monday", "08:30-09:45") in the configuration section.
2.  **Upload/Edit Course Data:**
    - **Program Core:** Main courses for specific programs.
    - **Electives:** General elective courses.
    - **NS Electives:** Natural Science electives.
3.  **Define Program Requirements:** Specify how many courses from each pool (Core, Elective, NS-Elective) are required for a given program.
4.  **Generate Schedule:**
    - Navigate to the "Select Program" page.
    - Follow the 4-step wizard to:
        - Define "No-Class" constraints (times you want to keep free).
        - Select specific sections for Core, Electives, and NS Electives if preferred.
    - Click "Generate" to run the CP-SAT solver.
5.  **View & Export:** Review the generated schedules, filter by number of days, or sort by gaps. You can export the results to CSV.

## Project Structure

- `app.py`: The main Flask application entry point and route handlers.
- `cpsat_solver.py`: The CP-SAT model - conflict, duplicate-subject and symmetry-breaking constraints, plus solution enumeration.
- `tools/extract_fall2026.py`: One-off extractor that turns the Fall 2026 timetable workbook into the course JSON files.
- `tools/verify_solver.py`: Headless regression checks for the solver.
- `templates/`: HTML templates for the web interface.
- `config.json`: Stores days and time slot configurations.
- `program_requirements.json`: Defines course requirements per program.
- `program_core.json`, `electives.json`, `ns_electives.json`: JSON data stores for course offerings.

## License

[MIT License]
