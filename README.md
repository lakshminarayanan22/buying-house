# Buying House Platform

A two-sided sourcing platform connecting **brands** and **suppliers**, with an internal
console for the merchandising team — and an AI supplier-matching agent designed for from day
one but deliberately built last.

Current state: **Phase 0 (foundation) and Supplier Tier-1 onboarding**, plus a natural-language
record editor. Production-shaped, internal console first.

---

## The one idea that shapes everything

The agent in Phase 6 is a data problem, not a model problem. Every decision below is made so
that the data it will eventually learn from is structured, attributable, and honest:

- **Taxonomy, not free text.** Capabilities are controlled-vocabulary references with an alias
  table, so "S/J", "Sinker" and "Single Jersey" all resolve to one value. Unrecognised terms go
  to a review queue instead of a free-text column.
- **Provenance on every claim.** `DataSource` records whether a number was self-reported by the
  factory, checked by our team, or observed from real transactions. Onboarding answers are a
  cold-start *prior*, not a fact.
- **Outcomes are observed, never asked.** `SupplierPerformance` carries roughly half the
  planned scoring weight and cannot be filled in by anyone — it is computed from orders. The
  table exists and stays empty until there are orders to compute it from.
- **Identity is gated.** Brands and suppliers cannot resolve each other without an explicit,
  logged reveal. That gatekeeping is the commercial model, so it lives in the access-control
  layer rather than in a UI condition.

---

## Stack

| Layer | Choice |
|---|---|
| API | Python 3.11, FastAPI, Pydantic v2 |
| ORM / migrations | SQLAlchemy 2.0, Alembic |
| Database | PostgreSQL 15+ with `pgvector` enabled from the first migration |
| Auth | JWT sessions, Argon2id passwords, OTP login for suppliers |
| Background jobs | Notification outbox table + worker (Celery/Redis wiring ready) |
| Frontend | Next.js 16 (App Router), TypeScript, Tailwind v4 |
| NL→SQL | sqlglot guard + Claude (`claude-opus-5`) planner, both optional |

---

## Running it

```bash
# Database
createdb buyinghouse            # or: docker compose up -d db
cd backend
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env

.venv/bin/alembic upgrade head
.venv/bin/python -m app.seed.run_seed        # taxonomy + notification templates
.venv/bin/python -m app.seed.bootstrap_admin # prints a generated Super Admin password
.venv/bin/python -m app.seed.demo            # optional: 5 suppliers, 1 brand, 3 logins
.venv/bin/uvicorn app.main:app --reload --port 8000

# Frontend
cd ../frontend && npm install && npm run dev  # http://localhost:3000
```

Demo logins (from `app.seed.demo`, password `ChangeMe123!`):
`merch@buyinghouse.co`, `sourcing@buyinghouse.co`, `buyer@northwind.co`.

### Tests

```bash
cd backend && .venv/bin/python -m pytest -q      # 61 tests
```

Most run on SQLite. The natural-language editor's tests require Postgres
(`createdb buyinghouse_test`) and skip without it — on SQLite, UUIDs are stored dashless, every
UUID literal would match nothing, and those tests would pass against a no-op.

---

## What is built

### Access control (`app/rbac/`)
`can(user, action, resource)` authorises a row you already hold; `scope_filter(model, actor)`
restricts the rows you can *find*, which is where list endpoints actually leak. Deny is the
default. A reveal is read-only and one-directional; a brand can never resolve another brand
however the reveal set is constructed. 28 tests, weighted towards the denials.

### Taxonomy (`app/models/reference.py`, `app/services/taxonomy.py`)
One namespaced `reference_item` table, 170 seeded values across 13 domains, 349 aliases, and a
materialised path so a "Knitwear" filter matches the T-shirt suppliers beneath it.

Taxonomy foreign keys are **composite** — `(id, domain)` with a CHECK pinning the domain — so
Postgres rejects a fibre id stored in a process column rather than trusting every code path to
remember. Verified by test.

### Onboarding (`app/api/suppliers.py`)
Tier 1 is eight fields. Tier 2 (capacity, MOQ, lead times, machinery) is what actually gates
RFQ participation. Tier 3 is granted by a human verification decision, never earned by filling
fields. The same endpoints serve self-service and assisted onboarding, with `DataSource`
recording which.

### Directory (`app/api/directory.py`)
Faceted search over process, category, fibre, GSM, MOQ (unit-aware), certificate validity,
month-wise free capacity, and geography. This is the honest prototype of the agent's hard-filter
step — if it cannot find the right factory today, no model will fix that later.

### Bulk import (`app/api/imports.py`)
Excel in, with one SAVEPOINT per row: a bad row reports its reason and the other 199 still land.
Idempotent on GST, then on (name, city). `dry_run=true` validates and leaves no trace.

### Natural-language record editor (`app/nlsql/`)
Describe a change in English (or write the SQL). It runs inside a transaction, the real
before/after rows are captured, the transaction is rolled back, and you confirm a highlighted
diff. Same experience as "apply then undo", without a window where wrong data is live.

Security is enforced on the parsed AST, not in the prompt: one statement, DML only, an explicit
table allowlist, and a mandatory WHERE on UPDATE/DELETE. `activity_log`, `app_user`,
`otp_challenge`, `org_invite`, `brand_supplier_reveal` and `supplier_performance` are never
writable. Confirm re-reads the targeted rows and refuses on a fingerprint mismatch. Every
affected row gets its own audit entry. Super Admin only.

---

## Not built yet

Phases 2–6 from the plan: enquiry → RFQ → quotation, sampling, orders and the TNA calendar,
inspections and shipments, the nightly performance rollups, and the matching agent itself.

The schema anticipates them where retrofitting would be expensive — `SupplierPerformance`,
`SupplierCapacityCalendar`, the `capability_narrative` that Phase 6 will embed, and pgvector
enabled in the first migration.
