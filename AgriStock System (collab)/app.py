import os
import csv
import io
import secrets

from datetime import date, datetime, timedelta
from functools import wraps

import pymysql
from pymysql.cursors import DictCursor

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, session, send_file, abort, g
)

from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key")

app.config.update(
    MYSQL_HOST=os.getenv("DB_HOST", "localhost"),
    MYSQL_USER=os.getenv("DB_USER", "root"),
    MYSQL_PASSWORD=os.getenv("DB_PASSWORD", ""),
    MYSQL_DB=os.getenv("DB_NAME", "agristock_db"),
    MYSQL_PORT=int(os.getenv("DB_PORT", "3306"))
)

# Direct MySQL Connection
def get_db_connection():

    if "agristock_db_connection" not in g:

        g.agristock_db_connection = pymysql.connect(
            host=app.config["MYSQL_HOST"],
            user=app.config["MYSQL_USER"],
            password=app.config["MYSQL_PASSWORD"],
            database=app.config["MYSQL_DB"],
            port=app.config["MYSQL_PORT"],
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False
        )

    return g.agristock_db_connection


class MySQL:

    @property
    def connection(self):
        return get_db_connection()


mysql = MySQL()


@app.teardown_appcontext
def close_db_connection(exception=None):

    connection = g.pop("agristock_db_connection", None)

    if connection is not None:

        if exception is not None:
            connection.rollback()

        connection.close()


LOW_STOCK = int(os.getenv("LOW_STOCK_THRESHOLD", "10"))
NEAR_DAYS = int(os.getenv("NEAR_EXPIRY_DAYS", "30"))

def query(sql, args=(), one=False, commit=False):
    cur = mysql.connection.cursor()
    cur.execute(sql, args)
    result = cur.fetchone() if one else cur.fetchall()
    if commit: mysql.connection.commit()
    cur.close()
    return result

def execute(sql, args=()):
    cur = mysql.connection.cursor()
    cur.execute(sql, args)
    mysql.connection.commit()
    last_id = cur.lastrowid
    cur.close()
    return last_id

def audit(action, details=""):
    if session.get("user_id"):
        execute("INSERT INTO audit_logs(user_id,username,action,details,ip_address) VALUES(%s,%s,%s,%s,%s)",
                (session["user_id"], session.get("username",""), action, details, request.remote_addr))

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"): return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapped

def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"): return redirect(url_for("login"))
        if session.get("role") != "Admin":
            flash("Admin access only.", "error"); return redirect(url_for("dashboard"))
        return fn(*args, **kwargs)
    return wrapped

@app.context_processor
def inject_globals():
    return {"today": date.today(), "low_stock_threshold": LOW_STOCK}

@app.route("/")
def index():
    if not session.get("user_id"):
        count = query("SELECT COUNT(*) AS n FROM users", one=True)["n"]
        return redirect(url_for("setup") if count == 0 else url_for("login"))
    return redirect(url_for("dashboard"))

@app.route("/setup", methods=["GET","POST"])
def setup():
    if query("SELECT COUNT(*) AS n FROM users", one=True)["n"] > 0:
        return redirect(url_for("login"))
    if request.method == "POST":
        full = request.form.get("full_name","").strip()
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        confirm = request.form.get("confirm_password","")
        if not full or not username or len(password) < 8:
            flash("Complete all fields. Password must be at least 8 characters.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        else:
            execute("INSERT INTO users(username,password_hash,full_name,role) VALUES(%s,%s,%s,'Admin')",
                    (username, generate_password_hash(password), full))
            flash("Super Admin created. Please log in.", "success")
            return redirect(url_for("login"))
    return render_template("setup.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if query("SELECT COUNT(*) AS n FROM users", one=True)["n"] == 0: return redirect(url_for("setup"))
    if request.method == "POST":
        username = request.form.get("username","").strip()
        user = query("SELECT * FROM users WHERE username=%s AND is_active=1", (username,), one=True)
        if user and check_password_hash(user["password_hash"], request.form.get("password","")):
            session.clear()
            session.update(user_id=user["id"], username=user["username"], full_name=user["full_name"], role=user["role"])
            audit("LOGIN", "Successful login")
            return redirect(url_for("dashboard"))
        flash("Invalid username or password, or account is inactive.", "error")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    audit("LOGOUT", "User logged out")
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    # 1. Dashboard statistics
    stats = query("""
        SELECT
            (SELECT COUNT(*) FROM products) AS products,

            (SELECT COALESCE(SUM(quantity_remaining), 0)
             FROM batches
             WHERE expiry_date IS NULL
                OR expiry_date >= CURDATE()) AS units,

            (SELECT COUNT(*)
             FROM products p
             LEFT JOIN (
                 SELECT product_id,
                        SUM(quantity_remaining) AS total_stock
                 FROM batches
                 WHERE expiry_date IS NULL
                    OR expiry_date >= CURDATE()
                 GROUP BY product_id
             ) sb ON sb.product_id = p.id
             WHERE COALESCE(sb.total_stock, 0)
                   <= p.reorder_level) AS low_items,

            (SELECT COUNT(*)
             FROM batches
             WHERE quantity_remaining > 0
               AND expiry_date BETWEEN CURDATE()
               AND DATE_ADD(CURDATE(), INTERVAL %s DAY)
            ) AS near_expiry,

            (SELECT COUNT(*)
             FROM batches
             WHERE quantity_remaining > 0
               AND expiry_date < CURDATE()
            ) AS expired_batches
    """, (NEAR_DAYS,), one=True)

    # 2. Expiry alerts
    alerts = query("""
        SELECT
            p.product_name,
            sb.batch_code,
            sb.quantity_remaining,
            DATEDIFF(sb.expiry_date, CURDATE()) AS days_left
        FROM batches sb
        JOIN products p ON p.id = sb.product_id
        WHERE sb.quantity_remaining > 0
          AND sb.expiry_date IS NOT NULL
          AND sb.expiry_date <=
              DATE_ADD(CURDATE(), INTERVAL %s DAY)
        ORDER BY sb.expiry_date ASC
        LIMIT 10
    """, (NEAR_DAYS,))

    # 3. Low-stock products
    low = query("""
        SELECT
            p.product_name,
            p.unit,
            p.reorder_level AS reorder_level,
            COALESCE(SUM(
                CASE
                    WHEN sb.expiry_date IS NULL
                      OR sb.expiry_date >= CURDATE()
                    THEN sb.quantity_remaining
                    ELSE 0
                END
            ), 0) AS stock
        FROM products p
        LEFT JOIN batches sb
            ON sb.product_id = p.id
        GROUP BY p.id, p.product_name,
                 p.unit, p.reorder_level
        HAVING stock <= p.reorder_level
        ORDER BY stock ASC
        LIMIT 10
    """)

    # 4. Recent stock movements
    movements = query("""
        SELECT
            p.product_name,
            UPPER(REPLACE(sm.movement_type, '_', ' ')) AS movement_type,
            sm.quantity,
            u.username,
            sm.created_at
        FROM stock_movements sm
        LEFT JOIN products p ON p.id = sm.product_id
        LEFT JOIN users u ON u.id = sm.performed_by
        ORDER BY sm.created_at DESC
        LIMIT 10
    """)

    # 5. Seven-day stock movement chart
    chart = query("""
        SELECT
            DATE_FORMAT(created_at, '%%Y-%%m-%%d') AS day,
            SUM(
                CASE WHEN movement_type = 'STOCK IN'
                THEN quantity ELSE 0 END
            ) AS stock_in,
            SUM(
                CASE WHEN movement_type = 'STOCK OUT'
                THEN quantity ELSE 0 END
            ) AS stock_out
        FROM stock_movements
        WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 6 DAY)
        GROUP BY DATE(created_at)
        ORDER BY DATE(created_at)
    """)

    return render_template(
        "dashboard.html",
        stats=stats,
        low=low,
        alerts=alerts,
        movements=movements,
        chart=chart
    )

# Generic CRUD helpers; user accounts and knowledge are admin-managed.
@app.route("/users")
@admin_required
def users():
    rows = query("SELECT id,username,full_name,role,is_active,created_at FROM users ORDER BY id DESC")
    return render_template("users.html", rows=rows)

@app.route("/users/add", methods=["GET","POST"])
@admin_required
def user_add():
    if request.method == "POST":
        username=request.form.get("username","").strip(); full=request.form.get("full_name","").strip()
        password=request.form.get("password",""); role=request.form.get("role","Staff")
        if not username or not full or len(password)<8 or role not in ("Admin","Staff"):
            flash("Check the fields. Password must be at least 8 characters.", "error")
        else:
            try:
                execute("INSERT INTO users(username,password_hash,full_name,role) VALUES(%s,%s,%s,%s)",
                        (username,generate_password_hash(password),full,role))
                audit("CREATE USER", f"Created {username} ({role})"); flash("User created.", "success")
                return redirect(url_for("users"))
            except Exception: mysql.connection.rollback(); flash("Username already exists or database error.", "error")
    return render_template("user_form.html", item=None)

@app.route("/users/<int:uid>/edit", methods=["GET","POST"])
@admin_required
def user_edit(uid):
    item=query("SELECT id,username,full_name,role,is_active FROM users WHERE id=%s",(uid,),one=True)
    if not item: abort(404)
    if request.method=="POST":
        full=request.form.get("full_name","").strip(); role=request.form.get("role","Staff")
        active=1 if request.form.get("is_active") else 0
        if uid==session["user_id"] and active==0:
            flash("You cannot deactivate your own account.", "error")
        elif role not in ("Admin","Staff"): flash("Invalid role.", "error")
        else:
            execute("UPDATE users SET full_name=%s,role=%s,is_active=%s WHERE id=%s",(full,role,active,uid))
            audit("UPDATE USER",f"Updated {item['username']}"); flash("User updated.","success"); return redirect(url_for("users"))
    return render_template("user_form.html",item=item)

@app.route("/users/<int:uid>/delete",methods=["POST"])
@admin_required
def user_delete(uid):
    if uid==session["user_id"]: flash("You cannot delete your own account.","error")
    else:
        execute("DELETE FROM users WHERE id=%s",(uid,)); audit("DELETE USER",f"User ID {uid}"); flash("User deleted.","success")
    return redirect(url_for("users"))

@app.route("/suppliers")
@login_required
def suppliers():
    return render_template("suppliers.html",rows=query("SELECT * FROM suppliers ORDER BY supplier_name"))

@app.route("/suppliers/add",methods=["GET","POST"])
@admin_required
def supplier_add():
    if request.method=="POST":
        name=request.form.get("supplier_name","").strip()
        if not name: flash("Supplier name is required.","error")
        else:
            execute("INSERT INTO suppliers(supplier_name,contact,address,email) VALUES(%s,%s,%s,%s)",
                    (name,request.form.get("contact"),request.form.get("address"),request.form.get("email")))
            audit("CREATE SUPPLIER",name); flash("Supplier added.","success"); return redirect(url_for("suppliers"))
    return render_template("supplier_form.html",item=None)

@app.route("/suppliers/<int:sid>/edit",methods=["GET","POST"])
@admin_required
def supplier_edit(sid):
    item=query("SELECT * FROM suppliers WHERE id=%s",(sid,),one=True)
    if not item: abort(404)
    if request.method=="POST":
        execute("UPDATE suppliers SET supplier_name=%s,contact=%s,address=%s,email=%s WHERE id=%s",
                (request.form.get("supplier_name"),request.form.get("contact"),request.form.get("address"),request.form.get("email"),sid))
        audit("UPDATE SUPPLIER",item["supplier_name"]); flash("Supplier updated.","success"); return redirect(url_for("suppliers"))
    return render_template("supplier_form.html",item=item)

@app.route("/suppliers/<int:sid>/delete",methods=["POST"])
@admin_required
def supplier_delete(sid):
    execute("DELETE FROM suppliers WHERE id=%s",(sid,)); audit("DELETE SUPPLIER",f"ID {sid}"); flash("Supplier deleted.","success")
    return redirect(url_for("suppliers"))

@app.route("/products")
@login_required
def products():
    rows=query("""SELECT p.*,COALESCE(SUM(CASE WHEN b.expiry_date>=CURDATE() THEN b.quantity_remaining ELSE 0 END),0) stock
                  FROM products p LEFT JOIN batches b ON p.id=b.product_id GROUP BY p.id ORDER BY p.product_name""")
    return render_template("products.html",rows=rows)

@app.route("/products/add",methods=["GET","POST"])
@admin_required
def product_add():
    if request.method=="POST":
        name=request.form.get("product_name","").strip()
        if not name: flash("Product name is required.","error")
        else:
            execute("INSERT INTO products(product_name,category,unit,reorder_level,description) VALUES(%s,%s,%s,%s,%s)",
                    (name,request.form.get("category"),request.form.get("unit") or "pcs",int(request.form.get("reorder_level") or 10),request.form.get("description")))
            audit("CREATE PRODUCT",name); flash("Product added.","success"); return redirect(url_for("products"))
    return render_template("product_form.html",item=None)

@app.route("/products/<int:pid>/edit",methods=["GET","POST"])
@admin_required
def product_edit(pid):
    item=query("SELECT * FROM products WHERE id=%s",(pid,),one=True)
    if not item: abort(404)
    if request.method=="POST":
        execute("UPDATE products SET product_name=%s,category=%s,unit=%s,reorder_level=%s,description=%s WHERE id=%s",
                (request.form.get("product_name"),request.form.get("category"),request.form.get("unit"),int(request.form.get("reorder_level") or 10),request.form.get("description"),pid))
        audit("UPDATE PRODUCT",item["product_name"]); flash("Product updated.","success"); return redirect(url_for("products"))
    return render_template("product_form.html",item=item)

@app.route("/products/<int:pid>/delete",methods=["POST"])
@admin_required
def product_delete(pid):
    used=query("SELECT (SELECT COUNT(*) FROM batches WHERE product_id=%s) + (SELECT COUNT(*) FROM stock_movements WHERE product_id=%s) AS n",(pid,pid),one=True)["n"]
    if used: flash("Cannot delete: this product has batch history. Keep it for audit/report accuracy.","error")
    else:
        execute("DELETE FROM products WHERE id=%s",(pid,)); audit("DELETE PRODUCT",f"ID {pid}"); flash("Product deleted.","success")
    return redirect(url_for("products"))

@app.route("/stock-in",methods=["GET","POST"])
@login_required
def stock_in():
    if request.method=="POST":
        try:
            product_id=int(request.form["product_id"]); qty=int(request.form["quantity"])
            supplier_id=request.form.get("supplier_id") or None
            received=request.form.get("date_received"); mfg=request.form.get("manufacture_date") or None
            expiry=request.form.get("expiry_date")
            if qty<=0 or date.fromisoformat(expiry)<date.fromisoformat(received): raise ValueError()
            product=query("SELECT product_name FROM products WHERE id=%s",(product_id,),one=True)
            if not product: raise ValueError()
            code="AG-"+datetime.now().strftime("%y%m%d")+"-"+secrets.token_hex(3).upper()
            batch_id=execute("""INSERT INTO batches(batch_code,product_id,supplier_id,quantity_received,quantity_remaining,date_received,manufacture_date,expiry_date,created_by)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (code,product_id,supplier_id,qty,qty,received,mfg,expiry,session["user_id"]))
            execute("INSERT INTO stock_movements(movement_type,product_id,batch_id,quantity,reference_no,performed_by) VALUES('STOCK IN',%s,%s,%s,%s,%s)",
                    (product_id,batch_id,qty,code,session["user_id"]))
            audit("STOCK IN",f"{product['product_name']} | {qty} | {code}")
            flash(f"Stock received. Generated batch: {code}","success"); return redirect(url_for("batches"))
        except Exception:
            mysql.connection.rollback(); flash("Please check product, quantity and dates. Expiry must not be before received date.","error")
    return render_template("stock_in.html",products=query("SELECT * FROM products ORDER BY product_name"),suppliers=query("SELECT * FROM suppliers ORDER BY supplier_name"))

@app.route("/stock-out",methods=["GET","POST"])
@login_required
def stock_out():
    suggestion=None
    if request.method=="POST":
        code=request.form.get("batch_code","").strip().upper()
        qty=int(request.form.get("quantity") or 0)
        batch=query("""SELECT b.*,p.product_name,p.unit FROM batches b JOIN products p ON p.id=b.product_id
                       WHERE b.batch_code=%s AND b.quantity_remaining>0 AND b.expiry_date>=CURDATE()""",(code,),one=True)
        if not batch: flash("Batch not found, expired, or already depleted.","error")
        elif qty<=0 or qty>batch["quantity_remaining"]: flash(f"Invalid quantity. Available: {batch['quantity_remaining']} {batch['unit']}.","error")
        else:
            # FEFO warning: inform staff if an earlier-expiry usable batch exists.
            earlier=query("""SELECT batch_code,expiry_date FROM batches WHERE product_id=%s AND quantity_remaining>0
                             AND expiry_date>=CURDATE() AND expiry_date<%s ORDER BY expiry_date LIMIT 1""",
                          (batch["product_id"],batch["expiry_date"]),one=True)
            if earlier:
                flash(f"FEFO reminder: use {earlier['batch_code']} first (expires {earlier['expiry_date']}).","error")
            else:
                execute("UPDATE batches SET quantity_remaining=quantity_remaining-%s WHERE id=%s",(qty,batch["id"]))
                execute("INSERT INTO stock_movements(movement_type,product_id,batch_id,quantity,reference_no,performed_by) VALUES('STOCK OUT',%s,%s,%s,%s,%s)",
                        (batch["product_id"],batch["id"],qty,code,session["user_id"]))
                audit("STOCK OUT",f"{batch['product_name']} | {qty} | {code}")
                flash("Stock-out recorded successfully.","success"); return redirect(url_for("stock_out"))
    # Staff can type a batch code; system also shows the next FEFO batch to guide them.
    suggestion=query("""SELECT b.batch_code,b.expiry_date,b.quantity_remaining,p.product_name,p.unit
                        FROM batches b JOIN products p ON p.id=b.product_id
                        WHERE b.quantity_remaining>0 AND b.expiry_date>=CURDATE()
                        ORDER BY b.expiry_date,b.id LIMIT 1""",one=True)
    return render_template("stock_out.html",suggestion=suggestion)

@app.route("/batches")
@login_required
def batches():
    rows=query("""SELECT b.*,p.product_name,p.unit,s.supplier_name,u.username
                  FROM batches b JOIN products p ON p.id=b.product_id
                  LEFT JOIN suppliers s ON s.id=b.supplier_id LEFT JOIN users u ON u.id=b.created_by
                  ORDER BY b.expiry_date,b.id""")
    return render_template("batches.html",rows=rows)

@app.route("/batches/<int:bid>/adjust",methods=["POST"])
@admin_required
def batch_adjust(bid):
    qty=int(request.form.get("quantity") or 0)
    batch=query("SELECT * FROM batches WHERE id=%s",(bid,),one=True)
    if not batch or batch["quantity_remaining"]+qty<0: flash("Invalid adjustment.","error")
    else:
        execute("UPDATE batches SET quantity_remaining=quantity_remaining+%s WHERE id=%s",(qty,bid))
        execute("INSERT INTO stock_movements(movement_type,product_id,batch_id,quantity,reference_no,notes,performed_by) VALUES('ADJUSTMENT',%s,%s,%s,%s,%s,%s)",
                (batch["product_id"],bid,abs(qty),batch["batch_code"],"Admin stock adjustment: "+str(qty),session["user_id"]))
        audit("ADJUST BATCH",f"{batch['batch_code']} adjustment {qty}"); flash("Batch adjusted.","success")
    return redirect(url_for("batches"))

@app.route("/knowledge")
@login_required
def knowledge():
    rows=query("SELECT * FROM knowledge_items ORDER BY module_type,title")
    return render_template("knowledge.html",rows=rows)

@app.route("/knowledge/add",methods=["GET","POST"])
@admin_required
def knowledge_add():
    if request.method=="POST":
        execute("""INSERT INTO knowledge_items(module_type,title,crop,season,symptoms,content,prevention)
                  VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                 (request.form.get("module_type"),request.form.get("title"),request.form.get("crop"),request.form.get("season"),request.form.get("symptoms"),request.form.get("content"),request.form.get("prevention")))
        audit("CREATE KNOWLEDGE ITEM",request.form.get("title")); flash("Knowledge item added.","success"); return redirect(url_for("knowledge"))
    return render_template("knowledge_form.html",item=None)

@app.route("/knowledge/<int:kid>/edit",methods=["GET","POST"])
@admin_required
def knowledge_edit(kid):
    item=query("SELECT * FROM knowledge_items WHERE id=%s",(kid,),one=True)
    if not item: abort(404)
    if request.method=="POST":
        execute("""UPDATE knowledge_items SET module_type=%s,title=%s,crop=%s,season=%s,symptoms=%s,content=%s,prevention=%s WHERE id=%s""",
                (request.form.get("module_type"),request.form.get("title"),request.form.get("crop"),request.form.get("season"),request.form.get("symptoms"),request.form.get("content"),request.form.get("prevention"),kid))
        audit("UPDATE KNOWLEDGE ITEM",item["title"]); flash("Knowledge item updated.","success"); return redirect(url_for("knowledge"))
    return render_template("knowledge_form.html",item=item)

@app.route("/knowledge/<int:kid>/delete",methods=["POST"])
@admin_required
def knowledge_delete(kid):
    execute("DELETE FROM knowledge_items WHERE id=%s",(kid,)); audit("DELETE KNOWLEDGE ITEM",f"ID {kid}"); flash("Knowledge item deleted.","success")
    return redirect(url_for("knowledge"))

@app.route("/reports")
@login_required
def reports():
    movements=query("""SELECT m.*,p.product_name,b.batch_code,u.username FROM stock_movements m
                       JOIN products p ON p.id=m.product_id LEFT JOIN batches b ON b.id=m.batch_id
                       LEFT JOIN users u ON u.id=m.performed_by ORDER BY m.created_at DESC LIMIT 500""")
    fast=query("""SELECT p.product_name,SUM(m.quantity) sold FROM stock_movements m JOIN products p ON p.id=m.product_id
                  WHERE m.movement_type='STOCK OUT' GROUP BY p.id ORDER BY sold DESC LIMIT 10""")
    ratio=query("""SELECT
      COALESCE((SELECT SUM(quantity) FROM stock_movements WHERE movement_type='STOCK OUT'),0) sold,
      COALESCE((SELECT SUM(quantity_remaining) FROM batches WHERE expiry_date<CURDATE()),0) expired""",one=True)
    return render_template("reports.html",movements=movements,fast=fast,ratio=ratio)

@app.route("/export/<kind>")
@login_required
def export_report(kind):
    rows=query("""SELECT m.id,m.movement_type,p.product_name,b.batch_code,m.quantity,m.reference_no,m.notes,u.username,m.created_at
                  FROM stock_movements m JOIN products p ON p.id=m.product_id
                  LEFT JOIN batches b ON b.id=m.batch_id LEFT JOIN users u ON u.id=m.performed_by
                  ORDER BY m.created_at DESC""")
    headers=["ID","Movement","Product","Batch","Quantity","Reference","Notes","User","Timestamp"]
    if kind=="csv":
        output=io.StringIO(); writer=csv.writer(output); writer.writerow(headers)
        for r in rows: writer.writerow([r.get(k) for k in ["id","movement_type","product_name","batch_code","quantity","reference_no","notes","username","created_at"]])
        return send_file(io.BytesIO(output.getvalue().encode("utf-8-sig")),mimetype="text/csv",as_attachment=True,download_name="agristock_movements.csv")
    if kind=="xlsx":
        from openpyxl import Workbook
        wb=Workbook(); ws=wb.active; ws.title="Stock Movements"; ws.append(headers)
        for r in rows: ws.append([str(r.get(k) or "") for k in ["id","movement_type","product_name","batch_code","quantity","reference_no","notes","username","created_at"]])
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width=min(max(max(len(str(c.value or "")) for c in col)+2,12),32)
        out=io.BytesIO(); wb.save(out); out.seek(0)
        return send_file(out,mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",as_attachment=True,download_name="agristock_movements.xlsx")
    if kind=="pdf":
        from reportlab.lib.pagesizes import landscape, A4
        from reportlab.platypus import SimpleDocTemplate,Table,TableStyle,Paragraph,Spacer
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        out=io.BytesIO(); doc=SimpleDocTemplate(out,pagesize=landscape(A4))
        data=[headers]+[[str(r.get(k) or "")[:35] for k in ["id","movement_type","product_name","batch_code","quantity","reference_no","notes","username","created_at"]] for r in rows]
        table=Table(data,repeatRows=1)
        table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#173f2b")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.3,colors.HexColor("#d8e2da")),("FONTSIZE",(0,0),(-1,-1),7),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f1f6f1")]),("VALIGN",(0,0),(-1,-1),"TOP")]))
        doc.build([Paragraph("AgriStock — Stock Movement Report",getSampleStyleSheet()["Title"]),Spacer(1,12),table])
        out.seek(0); return send_file(out,mimetype="application/pdf",as_attachment=True,download_name="agristock_movements.pdf")
    abort(404)

@app.route("/audit")
@admin_required
def audit_page():
    rows=query("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 500")
    return render_template("audit.html",rows=rows)

@app.route("/change-password",methods=["GET","POST"])
@login_required
def change_password():
    if request.method=="POST":
        current=request.form.get("current_password",""); new=request.form.get("new_password","")
        user=query("SELECT password_hash FROM users WHERE id=%s",(session["user_id"],),one=True)
        if not check_password_hash(user["password_hash"],current): flash("Current password is incorrect.","error")
        elif len(new)<8: flash("New password must be at least 8 characters.","error")
        elif new!=request.form.get("confirm_password"): flash("New passwords do not match.","error")
        else:
            execute("UPDATE users SET password_hash=%s WHERE id=%s",(generate_password_hash(new),session["user_id"]))
            audit("CHANGE PASSWORD","Password updated"); flash("Password changed successfully.","success"); return redirect(url_for("dashboard"))
    return render_template("change_password.html")

@app.errorhandler(500)
def server_error(e):
    return render_template("error.html",message="A server/database error occurred. Check that MySQL is running and the database is imported."),500

if __name__ == "__main__":
    app.run(debug=True)
