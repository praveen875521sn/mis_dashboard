# ECP Impact Dashboard — Django Edition

Converted from Flask to Django for better performance and scalability.

## Key differences from Flask version

| Flask | Django |
|-------|--------|
| `flask` sessions | Django signed-cookie sessions |
| `@app.route` | `path()` in `urls.py` |
| `render_template()` | `render()` |
| `jsonify()` | `JsonResponse()` |
| `if _IS_WORKER:` startup | `AppConfig.ready()` in `apps.py` |
| `app_mysql.py` globals | `app_state.py` module |

## Project structure

```
impact_sdg/
├── manage.py
├── requirements.txt
├── gunicorn_conf.py
├── .env.example
├── impact_sdg/
│   ├── settings.py       # Django settings
│   ├── urls.py           # Root URL conf
│   └── wsgi.py
└── dashboard/
    ├── apps.py           # Startup hook (replaces _IS_WORKER block)
    ├── app_state.py      # In-memory globals (CANDIDATES, USERS, etc.)
    ├── db_mysql.py       # MySQL layer (unchanged from Flask version)
    ├── logic.py          # Business logic (load_user_master, rebuild_from_raw, etc.)
    ├── views.py          # All API and page views
    ├── urls.py           # URL patterns
    ├── static/           # Static files
    └── templates/        # login.html, index.html, upload.html
```

## Setup & run

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your MySQL credentials

# 3. Run development server
python manage.py runserver 0.0.0.0:8000

# 4. Production (gunicorn)
gunicorn impact_sdg.wsgi -c gunicorn_conf.py
```

## All original API routes are preserved

- `GET  /`                          → Dashboard (login required)
- `GET  /login`                     → Login page
- `POST /api/auth/login`            → Login
- `POST /api/auth/logout`           → Logout
- `GET  /api/filters`               → Available filter options
- `GET  /api/upload/stats`          → Upload stats (IT only)
- `POST /api/upload/ecp`            → Upload ECP data
- `POST /api/upload/attendance`     → Upload attendance data
- `POST /api/upload/fa`             → Upload FA data
- `POST /api/upload/community`      → Upload community data
- `POST /api/upload/batch_plan`     → Upload batch plan
- `GET  /api/upload/rebuild_status` → Background rebuild progress
- `GET  /api/users/list`            → List users (IT only)
- `POST /api/users/save`            → Create/update user (IT only)
- `POST /api/users/delete`          → Deactivate user (IT only)
- `GET  /api/photos`                → Session photos
- `GET  /setup/bootstrap`           → First-time admin setup
