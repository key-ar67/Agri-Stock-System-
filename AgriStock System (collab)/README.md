# AgriStock — Python + MySQL CRUD System

AgriStock is a classroom-ready agricultural inventory management application built with **Python Flask, MySQL, HTML, CSS, and JavaScript**.

## Features
- First-run Super Admin setup; no public staff registration.
- Admin-created user accounts with Admin/Staff roles.
- Login, logout, password change, active/inactive accounts.
- Supplier CRUD, product CRUD, user CRUD, and agricultural knowledge CRUD.
- Stock-in creates a unique batch/lot code automatically.
- Stock-out checks expiry and applies FEFO ordering (First Expiry, First Out).
- Dashboard with low-stock and near-expiry/expired alerts.
- Audit trail for login, account, product, supplier, knowledge, and stock actions.
- Chart.js dashboard and fast-moving product chart.
- Export stock movement report to PDF, Excel (.xlsx), and CSV.
- Light/Dark mode, responsive layout, search, and subtle motion effects.

## Requirements
- Windows 10/11
- Python 3.10 or newer
- MySQL Server (or XAMPP MySQL/MariaDB)
- A browser

## Installation (Windows)
1. Extract the ZIP file to a folder, for example `C:\\AgriStock`.
2. Start **MySQL** in XAMPP Control Panel (or start your MySQL Server service).
3. Open phpMyAdmin at `http://localhost/phpmyadmin`.
4. Import `schema.sql` using the Import tab. It creates the `agristock_db` database and tables.
5. Open the AgriStock folder in VS Code.
6. Open Terminal in the project folder and create a virtual environment:

   ```powershell
   py -m venv venv
   .\\venv\\Scripts\\activate
   ```

7. Install the Python packages:

   ```powershell
   pip install -r requirements.txt
   ```

8. Copy `.env.example` and rename the copy to `.env`. Edit the database values to match your MySQL setup:

   ```env
   SECRET_KEY=use-a-long-random-secret
   DB_HOST=localhost
   DB_USER=root
   DB_PASSWORD=
   DB_NAME=agristock_db
   DB_PORT=3306
   LOW_STOCK_THRESHOLD=10
   NEAR_EXPIRY_DAYS=30
   ```

   If your MySQL root account has a password, put it after `DB_PASSWORD=`.

9. Run the app:

   ```powershell
   python app.py
   ```

10. Open `http://127.0.0.1:5000`. On the first run, the setup page asks you to create the Super Admin account. After setup, login with that account.

## Suggested demonstration flow for your grading video
1. Show the initial Admin setup (only if the database is fresh).
2. Login as Admin and create a Staff account.
3. Logout and login as Staff. Show that User Management and Audit Trail are not visible and inaccessible.
4. As Admin, add a supplier and a product.
5. Receive stock. Point out the automatically generated batch code.
6. Add a second batch for the same product with an earlier expiry date.
7. Attempt stock-out using the later-expiry batch. The app should show the FEFO reminder and prevent the transaction.
8. Stock-out from the earliest-expiry batch and show the quantity decrease.
9. Show dashboard alerts, Reports charts, and PDF/Excel/CSV exports.
10. Show audit trail and password change.
11. Switch between Light Mode and Dark Mode.

## CRUD coverage
| Module | Create | Read | Update | Delete |
|---|---:|---:|---:|---:|
| Users | Yes | Yes | Yes | Yes |
| Suppliers | Yes | Yes | Yes | Yes |
| Products | Yes | Yes | Yes | Yes* |
| Knowledge entries | Yes | Yes | Yes | Yes |
| Batches | Stock-in | Yes | Admin adjustment | History retained |

*Products with batch history cannot be deleted, to preserve inventory and audit integrity. This is intentional.

## Important notes / limitations
- The first Super Admin is created through the one-time `/setup` route. There is no public registration.
- Staff can view suppliers/products/batches, receive stock, perform stock-out, view reports, and change their password. Admin-only actions include user management, masterlist editing, knowledge editing, batch adjustments, and audit trail.
- FEFO is enforced per product: a later-expiry batch cannot be released while an earlier-expiry eligible batch for the same product still has stock.
- The system uses typed batch-code entry; no barcode scanner or QR scanner is required.
- Chart.js is loaded from its CDN, so the charts need an internet connection. The core CRUD and inventory pages do not depend on Chart.js.
- For a real business deployment, use HTTPS, a production WSGI server, CSRF protection, backups, stricter input validation, and a dedicated least-privilege MySQL account. Do not use Flask debug mode in production.
- Do not delete database tables manually if you need to retain audit history.

## Troubleshooting
- **Can't connect to MySQL:** Confirm MySQL is running, database name/user/password/port in `.env` are correct, and `schema.sql` was imported.
- **`ModuleNotFoundError`:** Activate `venv` and run `pip install -r requirements.txt`.
- **Database connector installation:** This project uses PyMySQL as a MySQLdb-compatible driver to make Windows setup easier. If installation fails, update pip with `py -m pip install --upgrade pip` and retry `pip install -r requirements.txt`.
- **Port 5000 already in use:** Change the last line of `app.py` to `app.run(debug=True, port=5001)` and visit `http://127.0.0.1:5001`.
- **Forgot Admin password:** Ask your database administrator to reset the password hash safely; do not create a public registration route.

## Motion inspiration
The visual language uses original CSS for gentle card lift, staggered reveal, focus states, sidebar hover, and theme transitions. These are common motion patterns inspired by the reference library at https://brewedops.cloud/motionlibrary/ . No external animation code is copied into the project.
