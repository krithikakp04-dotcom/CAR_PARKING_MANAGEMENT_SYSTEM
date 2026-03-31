from connect import get_connection
try:
    db = get_connection()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM Customers")
    customers = cursor.fetchall()
    print('Customers:', len(customers))
    cursor.execute("SELECT * FROM Vehicles")
    vehicles = cursor.fetchall()
    print('Vehicles:', len(vehicles))
    cursor.close()
    db.close()
except Exception as e:
    print('Error:', e)