# Face Attendance System

Fully automated face-recognition-based attendance system for housekeeping staff.

**Shift: 7:00 AM – 4:00 PM | OT: After 4:00 PM**

---

## Quick Start

```bash
# Option 1: Direct
chmod +x run.sh && ./run.sh

# Option 2: Docker
docker-compose up --build

# Option 3: Manual
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**URLs:**
- Punch Kiosk: `http://localhost:8000/punch`
- Admin Login: `http://localhost:8000/login` → `admin / admin123`
- Dashboard: `http://localhost:8000/dashboard`
- API Docs: `http://localhost:8000/docs`

---

## Architecture

```
face-attendance/
├── app/
│   ├── main.py                 # FastAPI app, startup, page routes
│   ├── config.py               # All configurable settings (.env)
│   ├── database.py             # SQLAlchemy engine + session
│   ├── schemas.py              # Pydantic request/response models
│   ├── models/
│   │   ├── staff.py            # Staff + FaceEmbedding tables
│   │   ├── attendance.py       # AttendancePunch + AttendanceRecord
│   │   ├── audit.py            # Immutable AuditLog
│   │   └── user.py             # User (auth/RBAC)
│   ├── services/
│   │   ├── face_service.py     # InsightFace detection, matching, liveness
│   │   ├── attendance_service.py # Punch logic, record CRUD, muster
│   │   └── ot_service.py       # OT calculation, shift logic
│   ├── routes/
│   │   ├── auth_routes.py      # Login, register
│   │   ├── staff_routes.py     # Staff CRUD, bulk upload, face registration
│   │   └── attendance_routes.py # Punch, today view, muster, export, edit
│   └── auth/
│       └── auth_service.py     # JWT, password hashing, RBAC
├── templates/                   # Jinja2 HTML pages
│   ├── index.html              # Landing page
│   ├── login.html              # Admin login
│   ├── punch.html              # Punch kiosk (camera)
│   ├── dashboard.html          # Admin dashboard
│   ├── staff.html              # Staff management
│   └── muster.html             # Muster book
├── static/
│   ├── css/style.css           # Full stylesheet
│   └── js/app.js               # API client + utilities
├── .env                        # Configuration
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── run.sh
```

---

## Database Schema

### `staff`
| Column | Type | Notes |
|--------|------|-------|
| id | INT PK | Auto-increment |
| employee_id | VARCHAR(50) | Unique, indexed |
| name | VARCHAR(200) | Required |
| designation | VARCHAR(100) | Optional |
| phone | VARCHAR(20) | Validated format |
| shift_start | VARCHAR(10) | Default "07:00" |
| shift_end | VARCHAR(10) | Default "16:00" |
| weekly_off | VARCHAR(20) | Default "Sunday" |
| is_active | BOOLEAN | Soft-delete flag |
| created_at | DATETIME | Auto |
| updated_at | DATETIME | Auto |

### `face_embeddings`
| Column | Type | Notes |
|--------|------|-------|
| id | INT PK | |
| staff_id | INT FK → staff | |
| embedding | BLOB | 512-float numpy array as bytes |
| version | INT | Increments on re-registration |
| is_active | BOOLEAN | Only one active per staff |
| archived_at | DATETIME | Set when superseded |
| registered_by | VARCHAR | Audit trail |

### `attendance_punches`
| Column | Type | Notes |
|--------|------|-------|
| id | INT PK | |
| staff_id | INT FK → staff | |
| punch_type | VARCHAR | IN / OUT / REJECTED |
| punch_time | DATETIME | |
| confidence | FLOAT | Face match score |
| is_valid | BOOLEAN | False for rejected |
| rejection_reason | VARCHAR | Why rejected |

### `attendance_records`
| Column | Type | Notes |
|--------|------|-------|
| id | INT PK | |
| staff_id | INT FK → staff | |
| date | DATE | Indexed |
| punch_in_time | DATETIME | |
| punch_out_time | DATETIME | |
| total_work_minutes | INT | Raw total |
| regular_minutes | INT | Within shift |
| ot_minutes | INT | After shift end, rounded 15min |
| status | VARCHAR | Present/Absent/Partial/Invalid/Weekly Off |
| is_edited | BOOLEAN | |
| edited_by | VARCHAR | |
| original_punch_in | DATETIME | Pre-edit value preserved |
| original_punch_out | DATETIME | Pre-edit value preserved |
| edit_reason | VARCHAR | |

### `audit_logs`
| Column | Type | Notes |
|--------|------|-------|
| id | INT PK | |
| action | VARCHAR | PUNCH_IN, EDIT_ATTENDANCE, etc. |
| entity_type | VARCHAR | attendance, staff |
| entity_id | INT | |
| performed_by | VARCHAR | |
| details | TEXT | JSON with before/after |
| timestamp | DATETIME | Immutable |

### `users`
| Column | Type | Notes |
|--------|------|-------|
| id | INT PK | |
| username | VARCHAR | Unique |
| password_hash | VARCHAR | bcrypt |
| role | VARCHAR | admin / supervisor / viewer |

---

## API Reference

### Auth
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/auth/login` | No | Login → JWT token |
| POST | `/api/auth/register` | Admin | Create user |

### Staff
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/staff/` | No | List all staff |
| POST | `/api/staff/` | No | Add single staff |
| PUT | `/api/staff/{emp_id}` | No | Update staff |
| DELETE | `/api/staff/{emp_id}` | No | Deactivate (soft) |
| POST | `/api/staff/{emp_id}/register-face` | No | Register face (multipart) |
| POST | `/api/staff/bulk-upload` | No | CSV bulk upload |

### Attendance
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/attendance/punch` | No | Face punch IN/OUT (multipart) |
| GET | `/api/attendance/today` | No | Today's attendance |
| GET | `/api/attendance/muster` | No | Monthly muster book |
| PUT | `/api/attendance/record/{id}` | Admin/Supervisor | Edit record |
| GET | `/api/attendance/export/muster` | No | Excel export |
| GET | `/api/attendance/punches` | No | Raw punch log |

---

## OT Calculation Logic

```
Shift: 7:00 AM → 4:00 PM (configurable per staff)

┌─────────────────────────────────────────────────┐
│  7:00 AM          4:00 PM                       │
│  ├──── Regular ────┤──── OT ──── → punch out    │
│  shift_start       shift_end                    │
└─────────────────────────────────────────────────┘

Rules:
1. Early arrival (before 7 AM): Regular time counts from 7 AM only
2. Work within 7 AM - 4 PM: Counted as regular_minutes
3. Work after 4 PM: Counted as ot_minutes
4. OT rounded to nearest 15-minute block:
   - 0-7 min  → 0 min
   - 8-22 min → 15 min
   - 23-37 min → 30 min
   - 38-52 min → 45 min
   - 53-67 min → 60 min

Status determination:
- Present: Worked ≥ 50% of shift
- Partial: Punched in but < 50% of shift or no punch-out
- Absent: No punches
- Invalid: Punch-out without punch-in
- Weekly Off: Configured day with no punches
```

---

## Face Recognition Workflow

```
Image Capture → Decode → Liveness Check → Face Detection → Extract Embedding → Match

Liveness checks:
1. Laplacian blur detection (screens/photos are blurrier)
2. Bright spot / glare detection (screen reflections)
3. Texture variance check (printed photos have low variance)
4. Minimum face size check (too small = far away / photo)

Matching:
- Cosine similarity between captured and stored embeddings
- All active embeddings cached in memory for speed
- Threshold: 0.45 (configurable)
- Best match returned if above threshold
```

---

## Edge Cases Handled

| Scenario | Handling |
|----------|----------|
| No face in frame | Reject + message "No face detected" |
| Multiple faces | Reject + message "Multiple faces detected" |
| Low confidence match | Reject + log attempt with score |
| Photo/screen spoofing | Liveness check rejects |
| Same person punches twice | Auto-alternates IN/OUT |
| Punch-out without punch-in | Creates record with "Invalid" status + warning |
| Rate limit abuse | Max 6 punches/hour per person |
| Employee punching for another | Face recognition prevents—each face maps to one ID |
| Midnight crossing | Date based on punch-in date |
| Camera failure | Frontend shows clear error message |
| DB failure | SQLAlchemy transaction rollback |
| Edit attendance | Original values preserved, audit logged |
| Duplicate employee IDs | Unique constraint + validation |
| Deactivated staff tries punch | Rejected with message |

---

## Configuration (.env)

All thresholds and timings are configurable:

```env
SHIFT_START=07:00         # Shift start time
SHIFT_END=16:00           # Shift end (OT starts after)
FACE_MATCH_THRESHOLD=0.45 # Face similarity threshold
LIVENESS_ENABLED=true     # Anti-spoofing checks
MIN_FACE_SIZE=80          # Minimum face pixels
MAX_PUNCH_ATTEMPTS_PER_HOUR=6
WORKING_DAYS_PER_WEEK=6
DEFAULT_WEEKLY_OFF=Sunday
```

---

## Roles & Permissions

| Action | Admin | Supervisor | Viewer |
|--------|-------|-----------|--------|
| View dashboard | ✓ | ✓ | ✓ |
| View muster book | ✓ | ✓ | ✓ |
| Edit attendance | ✓ | ✓ | ✗ |
| Add/manage staff | ✓ | ✓ | ✗ |
| Create users | ✓ | ✗ | ✗ |
| Export data | ✓ | ✓ | ✓ |
| Punch (kiosk) | Public — no auth required |
#   t e s t   d e p l o y  
 