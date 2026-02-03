from calendar import c
from os import name
from pickle import APPEND
from flask import Flask, render_template, request, redirect, send_file, session, url_for
import sqlite3
from datetime import datetime
import csv

# ----------------------------------
# Flask App Setup
# ----------------------------------
app = Flask(__name__)
app.secret_key = "supersecretkey"  # Needed for sessions

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

@app.route('/')
def home():
    return render_template('index.html')

# ----------------------------------
# Database Initialization
# ----------------------------------
def init_db():
    conn = sqlite3.connect('visitors.db')
    c = conn.cursor()
    
    # Create table if not exists (your original)
    c.execute('''
        CREATE TABLE IF NOT EXISTS visitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            phone TEXT,
            purpose TEXT,
            time TEXT
        )
    ''')
    
    # Add checkout_time column if it doesn't exist yet
    try:
        c.execute("ALTER TABLE visitors ADD COLUMN checkout_time TEXT")
        print("Added checkout_time column")
    except sqlite3.OperationalError:
        # Column already exists - that's fine
        pass
    
    conn.commit()
    conn.close()
# ----------------------------------
# Visitor Page
# ----------------------------------
@app.route('/checkin')
def checkin():
    return render_template('checkin_form.html')

# Save visitor
@app.route('/add', methods=['POST'])
def add():
    name = request.form['name']
    phone = request.form['phone']
    purpose = request.form['purpose']
    other = request.form.get('other_purpose')
    if purpose == "Other" and other:
        purpose = other
    
    time = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    conn = sqlite3.connect('visitors.db')
    c = conn.cursor()
    c.execute(
        "INSERT INTO visitors (name, phone, purpose, time) VALUES (?, ?, ?, ?)",
        (name, phone, purpose, time)
    )
    visitor_id = c.lastrowid
    conn.commit()
    conn.close()
    
    # This return MUST be indented with 4 spaces (same as lines above)
    return f"""\
<!DOCTYPE html>
<html>
<head>
    <meta http-equiv="refresh" content="6;url=/" />
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light text-center mt-5">
    <div class="container">
        <h2 class="text-success mb-4">Thank You, {name}!</h2>
        <p class="lead">Check-in completed successfully.</p>
        <p class="mt-3">Returning to main screen in a few seconds...</p>
    </div>
</body>
</html>
""", 200

@app.route('/checkout/self/<int:visitor_id>', methods=['POST'])
def self_checkout(visitor_id):
    checkout_time = datetime.now().strftime("%Y-%m-%d %H:%M")

    conn = sqlite3.connect('visitors.db')
    c = conn.cursor()
    
    # Only allow checkout if not already checked out
    c.execute("SELECT checkout_time FROM visitors WHERE id = ?", (visitor_id,))
    result = c.fetchone()
    
    if result and result[0] is None:
        c.execute(
            "UPDATE visitors SET checkout_time = ? WHERE id = ?",
            (checkout_time, visitor_id)
        )
        conn.commit()
        conn.close()
        
        return render_template(
            'checkout_success.html',
            checkout_time=checkout_time
        )
    
    conn.close()
    return redirect('/')  # or show error page

# ----------------------------------
# Admin Login
# ----------------------------------
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect('/admin')
        else:
            return render_template('admin_login.html', error="Invalid credentials")

    return render_template('admin_login.html')

# ----------------------------------
# Admin Dashboard
# ----------------------------------
from collections import defaultdict
from datetime import datetime, timedelta

@app.route('/admin', methods=['GET'])
def admin():
    if not session.get('admin_logged_in'):
        return redirect('/admin/login')

    conn = sqlite3.connect('visitors.db')
    c = conn.cursor()

    q = request.args.get('q', '').strip()
    start_date = request.args.get('start')
    end_date = request.args.get('end')

    # ── Build main visitors query ───────────────────────────────────────
    query = "SELECT * FROM visitors"
    params = []
    conditions = []

    if q:
        conditions.append("(name LIKE ? OR phone LIKE ?)")
        like_q = f"%{q}%"
        params.extend([like_q, like_q])

    if start_date:
        conditions.append("date(time) >= ?")
        params.append(start_date)

    if end_date:
        conditions.append("date(time) <= ?")
        params.append(end_date)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY time DESC"

    c.execute(query, params)
    visitors = c.fetchall()

    # ── Today's count (always full day) ────────────────────────────────
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT COUNT(*) FROM visitors WHERE date(time) = ?", (today,))
    today_count = c.fetchone()[0]

    # Count visitors still inside (checkout_time IS NULL)
    c.execute("SELECT COUNT(*) FROM visitors WHERE checkout_time IS NULL")
    inside_count = c.fetchone()[0]

    # ── Chart data: visitors per day ───────────────────────────────────
    chart_query = """
        SELECT date(time) as visit_date, COUNT(*) as count
        FROM visitors
    """
    chart_params = []
    chart_conditions = []

    # Use the same filters as the table (makes chart consistent with filters)
    if start_date:
        chart_conditions.append("date(time) >= ?")
        chart_params.append(start_date)
    if end_date:
        chart_conditions.append("date(time) <= ?")
        chart_params.append(end_date)

    if chart_conditions:
        chart_query += " WHERE " + " AND ".join(chart_conditions)

    chart_query += " GROUP BY date(time) ORDER BY date(time)"

    c.execute(chart_query, chart_params)
    chart_rows = c.fetchall()

    # Prepare data for Chart.js (labels = dates, values = counts)
    chart_labels = []
    chart_values = []

    if chart_rows:
        # Fill missing days with 0 if you want continuous chart
        # (optional — comment out if you prefer only days with visitors)
        min_date = datetime.strptime(chart_rows[0][0], "%Y-%m-%d")
        max_date = datetime.strptime(chart_rows[-1][0], "%Y-%m-%d")
        current = min_date
        date_to_count = {row[0]: row[1] for row in chart_rows}

        while current <= max_date:
            date_str = current.strftime("%Y-%m-%d")
            chart_labels.append(date_str)
            chart_values.append(date_to_count.get(date_str, 0))
            current += timedelta(days=1)
    else:
        # Fallback: last 7 days if no data in range
        for i in range(6, -1, -1):
            d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            chart_labels.append(d)
            chart_values.append(0)

    chart_data = dict(zip(chart_labels, chart_values))

    

    conn.close()

    return render_template(
        'admin.html',
        visitors=visitors,
        total=today_count,
        inside_count=inside_count,     # ← new
        start_date=start_date,
        end_date=end_date,
        q=q,
        chart_data=chart_data
   )

# ----------------------------------
# Export CSV
# ----------------------------------
@app.route('/export')
def export():
    if not session.get('admin_logged_in'):
        return redirect('/admin/login')

    conn = sqlite3.connect('visitors.db')
    c = conn.cursor()
    c.execute("SELECT * FROM visitors")
    data = c.fetchall()
    conn.close()

    filename = "visitors_export.csv"
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["ID", "Name", "Phone", "Purpose", "Time"])
        writer.writerows(data)

    return send_file(filename, as_attachment=True)

# ----------------------------------
# Logout
# ----------------------------------
@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect('/admin/login')

# ----------------------------------
# Checkout
# ----------------------------------

# --- @app.route('/admin/checkout/<int:visitor_id>', methods=['POST'])
# ---def checkout(visitor_id):
    # ---if not session.get('admin_logged_in'):
      # ---  return redirect('/admin/login')

   # --- checkout_time = datetime.now().strftime("%Y-%m-%d %H:%M")

   # --- conn = sqlite3.connect('visitors.db')
  # ---  c = conn.cursor()
    
    # Only allow checkout if not already checked out
  # ---  c.execute("SELECT checkout_time FROM visitors WHERE id = ?", (visitor_id,))
  # ---  current = c.fetchone()
    
 # ---   if current and current[0] is None:
 # ---       c.execute(
  # ---          "UPDATE visitors SET checkout_time = ? WHERE id = ?",
  # ---          (checkout_time, visitor_id)
  # ---      )
 # ---       conn.commit()
 # ---       # Optional: flash message (we'll add later if you want)
    
  # ---  conn.close()
    
 # ---   # Redirect back to admin with same filters preserved
 # ---   return redirect(url_for('admin', **request.args))

@app.route('/checkout', methods=['GET', 'POST'])
def public_checkout():
    conn = sqlite3.connect('visitors.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    message = None
    message_type = 'info'  # default
    visitors = []
    search_term = ''
    redirect_after = None   # we will set this only on success

    if request.method == 'POST':
        search_term = request.form.get('search', '').strip().lower()
        action = request.form.get('action')
        visitor_id = request.form.get('visitor_id')

        # Handle checkout
        if action == 'checkout' and visitor_id:
            checkout_time = datetime.now().strftime("%Y-%m-%d %H:%M")
            c.execute("""
                UPDATE visitors
                SET checkout_time = ?
                WHERE id = ? AND checkout_time IS NULL
            """, (checkout_time, visitor_id))

            if c.rowcount == 1:
                conn.commit()
                message = "Thank you! You have successfully checked out."
                message_type = 'success'
                redirect_after = 4  # seconds until redirect (silent)
                visitors = []       # clear the list after success
            else:
                message = "This visit could not be checked out (already done or not found)."
                message_type = 'danger'

        # Normal search (only if no successful checkout)
        if not redirect_after:
            if search_term:
                like = f"%{search_term}%"
                c.execute("""
                    SELECT id, name, phone, time, purpose
                    FROM visitors
                    WHERE checkout_time IS NULL
                      AND (LOWER(name) LIKE ? OR LOWER(phone) LIKE ?)
                    ORDER BY time DESC
                    LIMIT 5
                """, (like, like))
                visitors = c.fetchall()

    conn.close()

    return render_template(
        'checkout.html',
        visitors=visitors,
        message=message,
        message_type=message_type,
        search_term=search_term,
        redirect_after=redirect_after
    )
# ----------------------------------
# Run App
# ----------------------------------
if __name__ == '__main__':
    init_db()
    app.run(debug=True)