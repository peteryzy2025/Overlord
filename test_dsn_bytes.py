import psycopg

print("psycopg version:", psycopg.__version__)

conn = psycopg.connect(
    host="192.168.110.54",
    port="5432",
    dbname="overlord_db",
    user="postgres",
    password="YUEER0811",
)

print("connected ok!")
conn.close()
