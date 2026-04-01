from flask import Flask, render_template, request, redirect, session, url_for, flash
from functools import wraps
from connect import get_connection
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'super-secret-key-change-me'

RATE_PER_HOUR = 10  # Rate per hour

# Login-required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# helper: A1..E5 <-> 1..25 conversions

def slot_label_from_id(slot_id):
    try:
        slot_id = int(slot_id)
    except (TypeError, ValueError):
        return None
    if not (1 <= slot_id <= 25):
        return None
    letters = ['A', 'B', 'C', 'D', 'E']
    parent = letters[(slot_id - 1) // 5]
    sub = ((slot_id - 1) % 5) + 1
    return f"{parent}{sub}"


def slot_id_from_input(value):
    if value is None:
        return None
    value = str(value).strip()
    if value.isdigit():
        return int(value)
    if len(value) == 2 and value[0] in 'ABCDE' and value[1] in '12345':
        letters = ['A', 'B', 'C', 'D', 'E']
        return (letters.index(value[0])) * 5 + int(value[1])
    return None

# -------------------
# Login
# -------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        # Basic credentials; replace with DB lookup in production
        if username == 'admin' and password == 'admin123':
            session['user'] = username
            flash('Login successful', 'success')
            return redirect(url_for('home'))
        flash('Invalid username or password', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))

# -------------------
# Home / Dashboard
# -------------------
@app.route('/')
@login_required
def home():
    db = get_connection()
    cursor = db.cursor()

    cursor.execute("SELECT * FROM Parking_Slots ORDER BY slot_id")
    slots = cursor.fetchall()

    # Map slots by ID for lookup
    slot_by_id = {int(row[0]): row for row in slots}

    # Build exactly 5 parent slots, each with 5 subslots: A1..A5, B1..B5, C1..C5, D1..D5, E1..E5
    slot_groups = {}
    letters = ['A', 'B', 'C', 'D', 'E']
    for num in range(1, 26):
        parent_idx = (num - 1) // 5
        parent_name = letters[parent_idx]
        sub_name = f"{parent_name}{((num - 1) % 5) + 1}"

        if num in slot_by_id:
            db_slot = slot_by_id[num]
            status = db_slot[2] if len(db_slot) > 2 else 'Unknown'
            slot_obj = {'slot_id': num, 'status': status, 'rows': db_slot, 'placeholder': False}
        else:
            slot_obj = {'slot_id': num, 'status': 'Not installed', 'rows': None, 'placeholder': True}

        slot_groups.setdefault(parent_name, []).append({'db': slot_obj, 'label': sub_name})

    # Ensure we have empty groups up to E even if some slots are missing
    for letter in letters:
        slot_groups.setdefault(letter, [])

    # Compute stats
    total_slots = 25
    available = sum(1 for group in slot_groups.values() for item in group if not item['db']['placeholder'] and item['db']['status'] == 'Available')
    occupied = sum(1 for group in slot_groups.values() for item in group if not item['db']['placeholder'] and item['db']['status'] != 'Available')
    not_installed = total_slots - available - occupied

    # Get active tickets for occupied slots
    cursor.execute("""
        SELECT t.ticket_id, t.slot_id, v.vehicle_number
        FROM Tickets t
        JOIN Vehicles v ON t.vehicle_id = v.vehicle_id
        WHERE t.exit_time IS NULL
    """)
    active_ticket_rows = cursor.fetchall()
    active_tickets = {row[1]: {"ticket_id": row[0], "vehicle_number": row[2]} for row in active_ticket_rows}

    cursor.close()
    db.close()
    return render_template(
        "index.html",
        slot_groups=slot_groups,
        active_tickets=active_tickets,
        total_slots=total_slots,
        available=available,
        occupied=occupied,
        not_installed=not_installed
    )

# -------------------
# Install Missing Slot
@app.route('/install/<string:slot_label>')
def install_slot(slot_label):
    # Expected label like A1..E5
    if len(slot_label) != 2 or slot_label[0] not in ['A','B','C','D','E'] or slot_label[1] not in '12345':
        return "<h2>Invalid slot label</h2><a href='/'>Back</a>"

    letters = ['A','B','C','D','E']
    parent_index = letters.index(slot_label[0])
    sub_index = int(slot_label[1])
    slot_id = parent_index * 5 + sub_index

    db = get_connection()
    cursor = db.cursor()
    cursor.execute("SELECT slot_id FROM Parking_Slots WHERE slot_id=%s", (slot_id,))
    existing = cursor.fetchone()
    if existing:
        cursor.close()
        db.close()
        return redirect('/')

    # create slot as Available, adjust columns as per schema
    cursor.execute("INSERT INTO Parking_Slots (slot_id, status) VALUES (%s, %s)", (slot_id, 'Available'))
    db.commit()
    cursor.close()
    db.close()
    return redirect('/')

# -------------------
# Book Slot
# -------------------
@app.route('/book', methods=['GET', 'POST'])
@login_required
def book():
    db = get_connection()
    cursor = db.cursor()

    raw_slot = request.args.get('slot_id')  # Get clicked slot from dashboard
    slot_id = slot_id_from_input(raw_slot)
    pre_slot_label = slot_label_from_id(slot_id)

    if request.method == 'POST':
        name = request.form['name'].strip()
        phone = request.form['phone'].strip()
        vehicle = request.form['vehicle'].strip()

        # Validate customer name: letters and spaces only
        if not name or not name.replace(' ', '').isalpha():
            flash('Name must contain only alphabetic characters and spaces', 'error')
            cursor.close()
            db.close()
            return render_template('book.html', rate=RATE_PER_HOUR, pre_slot=slot_id)

        # Validate phone number is numeric and 10 digits long
        if not phone.isdigit() or len(phone) != 10:
            flash('Phone number must contain exactly 10 digits (0-9)', 'error')
            cursor.close()
            db.close()
            return render_template('book.html', rate=RATE_PER_HOUR, pre_slot=slot_id)

        # Use pre-selected slot (existing or from form) or first available
        if 'slot_id' in request.form and request.form['slot_id']:
            selected_slot = request.form['slot_id']
            slot_id = slot_id_from_input(selected_slot)
            pre_slot_label = slot_label_from_id(slot_id)
            if slot_id is None:
                cursor.close()
                db.close()
                return "<h2>Invalid slot selected!</h2><a href='/'>Back to Dashboard</a>"

            cursor.execute("SELECT status FROM Parking_Slots WHERE slot_id=%s", (slot_id,))
            status = cursor.fetchone()
            if not status or status[0] != 'Available':
                cursor.close()
                db.close()
                return "<h2>Slot not available!</h2><a href='/'>Back to Dashboard</a>"
        else:
            cursor.execute("SELECT slot_id FROM Parking_Slots WHERE status='Available' LIMIT 1")
            slot = cursor.fetchone()
            if not slot:
                cursor.close()
                db.close()
                return "<h2>Parking Full!</h2><a href='/'>Back to Dashboard</a>"
            slot_id = slot[0]
            pre_slot_label = slot_label_from_id(slot_id)

        # Insert Customer
        cursor.execute("INSERT INTO Customers (name, phone) VALUES (%s, %s)", (name, phone))
        customer_id = cursor.lastrowid

        # Insert Vehicle (type = 'Car')
        cursor.execute(
            "INSERT INTO Vehicles (vehicle_number, vehicle_type, customer_id) VALUES (%s, %s, %s)",
            (vehicle, 'Car', customer_id)
        )
        vehicle_id = cursor.lastrowid

        # Assign slot
        cursor.execute("UPDATE Parking_Slots SET status='Occupied' WHERE slot_id=%s", (slot_id,))
        cursor.execute(
            "INSERT INTO Tickets (vehicle_id, slot_id, entry_time) VALUES (%s, %s, NOW())",
            (vehicle_id, slot_id)
        )
        ticket_id = cursor.lastrowid

        db.commit()
        cursor.close()
        db.close()
        # redirect to single-generated ticket view while keeping /tickets for all tickets
        return redirect(f'/ticket/{ticket_id}')

    cursor.close()
    db.close()
    return render_template("book.html", rate=RATE_PER_HOUR, pre_slot=pre_slot_label, slot_id=slot_id)

# -------------------
# Tickets Page
# -------------------
@app.route('/tickets')
def tickets():
    db = get_connection()
    cursor = db.cursor()

    selected_slot = request.args.get('slot_id')
    highlight_ticket = request.args.get('highlight_ticket')

    cursor.execute("""
        SELECT t.ticket_id, t.vehicle_id, t.slot_id, t.entry_time, t.exit_time, t.amount, v.vehicle_number
        FROM Tickets t
        JOIN Vehicles v ON t.vehicle_id = v.vehicle_id
        ORDER BY t.entry_time DESC
    """)

    tickets_data = cursor.fetchall()

    selected_ticket = None
    if highlight_ticket:
        cursor.execute("""
            SELECT t.ticket_id, t.vehicle_id, t.slot_id, t.entry_time, t.exit_time, t.amount, v.vehicle_number
            FROM Tickets t
            JOIN Vehicles v ON t.vehicle_id = v.vehicle_id
            WHERE t.ticket_id=%s
        """, (highlight_ticket,))
        selected_ticket = cursor.fetchone()

    cursor.close()
    db.close()

    return render_template("tickets.html", tickets=tickets_data, selected_slot=selected_slot, selected_ticket=selected_ticket)

# -------------------
# Single Ticket View
@app.route('/ticket/<int:ticket_id>')
@login_required
def ticket(ticket_id):
    db = get_connection()
    cursor = db.cursor()
    cursor.execute("""
        SELECT t.ticket_id, t.vehicle_id, t.slot_id, t.entry_time, t.exit_time, t.amount, v.vehicle_number
        FROM Tickets t
        JOIN Vehicles v ON t.vehicle_id = v.vehicle_id
        WHERE t.ticket_id=%s
    """, (ticket_id,))
    ticket_data = cursor.fetchone()
    cursor.close()
    db.close()

    if not ticket_data:
        return "<h2>Ticket not found.</h2><a href='/tickets'>View all tickets</a>"

    slot_label = slot_label_from_id(ticket_data[2])
    return render_template("ticket.html", ticket=ticket_data, slot_label=slot_label)

# -------------------
# Exit Vehicle
# -------------------
@app.route('/exit/<int:ticket_id>')
@login_required
def exit_vehicle(ticket_id):
    db = get_connection()
    cursor = db.cursor()

    cursor.execute("SELECT entry_time, slot_id, exit_time FROM Tickets WHERE ticket_id=%s", (ticket_id,))
    ticket = cursor.fetchone()

    if ticket:
        entry_time, slot_id, exit_time = ticket

        # Prevent double-exit and duplicate payments for same ticket
        if exit_time is not None:
            cursor.close()
            db.close()
            return redirect('/tickets')

        now = datetime.now()
        hours = (now - entry_time).total_seconds() / 3600
        hours = max(1, int(hours))
        amount = hours * RATE_PER_HOUR

        cursor.execute(
            "UPDATE Tickets SET exit_time=NOW(), amount=%s WHERE ticket_id=%s",
            (amount, ticket_id)
        )
        cursor.execute("UPDATE Parking_Slots SET status='Available' WHERE slot_id=%s", (slot_id,))

        payment_exists = False
        try:
            cursor.execute("SELECT payment_id FROM Payments WHERE ticket_id=%s", (ticket_id,))
            payment_exists = cursor.fetchone() is not None
        except Exception as e:
            print("Warning: could not query Payments table", e)

        if not payment_exists:
            try:
                cursor.execute(
                    "INSERT INTO Payments (ticket_id, amount, payment_time) VALUES (%s, %s, NOW())",
                    (ticket_id, amount)
                )
            except Exception as e:
                print("Warning: could not insert payment record", e)

        db.commit()

    cursor.close()
    db.close()
    return redirect('/tickets')

# -------------------
# Run App
# -------------------
if __name__ == '__main__':
    app.run(debug=True)