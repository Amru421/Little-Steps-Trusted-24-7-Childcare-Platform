# Nestcare

A responsive childcare discovery and operations app with persistent SQLite storage. Parents can search verified centers, request hourly or daily care, and request monthly subscriptions. Providers can maintain their center profile, availability, pricing, and caregiver introductions, then respond to requests. Administrators can review accounts and centers, monitor activity, and resolve family concerns.

**Payments and refunds are not implemented.** Requests do not collect money or card details. Live CCTV and medical emergency integrations are also outside this version.

## Run locally

Requires Python 3.10 or later; there are no third-party packages to install.

```powershell
python server.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The database is created as `nestcare.sqlite3` in this folder on first start. Use `NESTCARE_DB` to put it somewhere else, or `NESTCARE_PORT` to change the port.

## Demo accounts

| Role | Email | Password |
|---|---|---|
| Administrator | `admin@nestcare.local` | `NestcareAdmin123!` |
| Childcare provider | `provider@nestcare.local` | `NestcareProvider123!` |
| Parent | Register through the app | Set during registration |

These are local demonstration credentials, **not production credentials**. The listed centers, caregivers, prices, and certifications are sample data. The server binds to loopback by default and is intended for local evaluation. Do not use the demo with real children’s or families’ personal information. Provider-submitted certification names are review information, not uploaded evidence or an independent safety certification. Search is city-based (no geocoding/maps integration), and this version does not upload verification documents.

A public deployment needs production-grade hosting and operational controls, including HTTPS, managed secrets, backups, rate limiting, monitoring, privacy/compliance review, and a production authentication/storage design.

## Included workflows

- Parent registration and sign-in with administrator approval; center search by city, age group, and 24-hour availability.
- Center details, caregiver introductions, safety information, and hourly/daily/monthly plan pricing.
- Live capacity checks before hourly, daily, or monthly care requests; capacity is rechecked when a request is submitted. In-app status notifications are included.
- Provider applications held for approval; provider dashboards for schedules, capacity, pricing, caregiver profiles, and request decisions.
- Admin review of provider and center applications, booking/subscription overview, and family concern resolution.
- A transcript-led app tour and a public feedback form whose submissions are visible only to administrators.
- Role-gated API routes, parameterized SQL, password hashing, HTTP-only same-site sessions, and a local persistent SQLite database.

The app tour is available at `/explainer.html`, and feedback can be submitted at `/feedback.html`. Feedback is stored in the app database for administrator review; the form asks visitors not to submit children’s personal or health information.

## Verification

Run the backend/API integration tests with:

```powershell
python -m unittest discover -s tests -v
```

## Deploy to Render

The included [render.yaml](./render.yaml) creates a Python web service and a persistent disk for SQLite. It disables sample/demo accounts and data, enables secure cookies, and prompts you to set `NESTCARE_ADMIN_EMAIL` and `NESTCARE_ADMIN_PASSWORD` as deployment secrets. Choose a unique admin password with at least 16 characters and do not commit secrets. The service and persistent disk use Render’s paid Starter resources; review current pricing before creating the service.

After this repository has been pushed, start the deployment using the [Render Blueprint link](https://render.com/deploy?repo=https://github.com/Amru421/Little-Steps-Trusted-24-7-Childcare-Platform). Render will ask you to sign in, review the paid resources, and enter the admin secrets. The public app URL is assigned by Render after the deployment completes.

This deployment configuration is suitable for a **demo**, not production childcare operations. Do not collect real children’s data until the app has had a professional security, privacy, and regulatory review and appropriate production controls have been implemented.
