# connect.py

import mysql.connector

def get_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",   # or root
        password="191004",   # your password
        database="CAR_PARKING_MANAGEMENT_SYSTEM"
    )