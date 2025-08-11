import sqlite3
import json
from datetime import datetime

def create_tables(conn):
    cursor = conn.cursor()
    # Create services table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS services (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            address TEXT,
            port INTEGER,
            tags TEXT,
            meta TEXT,
            first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create health checks table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS health_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id TEXT NOT NULL,
            check_name TEXT,
            status TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (service_id) REFERENCES services (id)
        )
    ''')
    
    # Create indexes
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_health_checks_service_timestamp 
        ON health_checks (service_id, timestamp)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_health_checks_timestamp 
        ON health_checks (timestamp)
    ''')
    
    conn.commit()
    conn.commit()

def init_database():
    """Initialize database, create tables, and return connection"""
    conn = sqlite3.connect('/data/consul-monitor.db')
    create_tables(conn)
    return conn

def upsert_service(conn, service_data):
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO services (id, name, address, port, tags, meta)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            address = excluded.address,
            port = excluded.port,
            tags = excluded.tags,
            meta = excluded.meta,
            last_seen = CURRENT_TIMESTAMP
    ''', (
        service_data['id'],
        service_data['name'],
        service_data.get('address'),
        service_data.get('port'),
        json.dumps(service_data.get('tags', [])),
        json.dumps(service_data.get('meta', {}))
    ))
    conn.commit()

def insert_health_check(conn, service_id, check_name, status):
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO health_checks (service_id, check_name, status)
        VALUES (?, ?, ?)
    ''', (service_id, check_name, status))
    conn.commit()

def get_all_services_with_health(conn):
    cursor = conn.cursor()
    cursor.execute('''
        SELECT s.id, s.name, s.address, s.port, s.tags, s.meta, 
               h.status, MAX(h.timestamp) AS last_check
        FROM services s
        LEFT JOIN health_checks h ON s.id = h.service_id
        GROUP BY s.id
    ''')
    
    services = []
    for row in cursor.fetchall():
        service = {
            'id': row[0],
            'name': row[1],
            'address': row[2],
            'port': row[3],
            'tags': json.loads(row[4]) if row[4] else [],
            'meta': json.loads(row[5]) if row[5] else {},
            'current_status': row[6] or 'unknown',
            'last_check': row[7]
        }
        services.append(service)
    return services

def get_service_history(conn, service_id, hours=24):
    cursor = conn.cursor()
    cursor.execute('''
        SELECT status, timestamp
        FROM health_checks
        WHERE service_id = ? 
          AND timestamp >= datetime('now', ?)
        ORDER BY timestamp ASC
    ''', (service_id, f'-{hours} hours'))
    return cursor.fetchall()

def get_service_history_detailed(conn, service_id, hours=24):
    """Get detailed service history with proper timestamp handling"""
    cursor = conn.cursor()
    cursor.execute('''
        SELECT status, timestamp
        FROM health_checks
        WHERE service_id = ? 
          AND timestamp >= datetime('now', ?)
        ORDER BY timestamp ASC
    ''', (service_id, f'-{hours} hours'))
    
    results = cursor.fetchall()
    return [(status, timestamp) for status, timestamp in results]

def is_database_available(conn):
    try:
        conn.execute('SELECT 1')
        return True
    except sqlite3.Error:
        return False
