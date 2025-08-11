from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
import logging
import threading
import consul_client
import database
import sqlite3
import atexit

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ConsulPoller:
    def __init__(self, database_connection_factory):
        self.scheduler = BackgroundScheduler(
            executors={'default': ThreadPoolExecutor(1)},
            job_defaults={'coalesce': True, 'max_instances': 1}
        )
        self.get_db_conn = database_connection_factory
        self.running = False
        
    def start(self):
        """Start the background polling"""
        if not self.running:
            logger.info("Starting Consul background polling...")
            
            # Initial poll on startup
            self.poll_consul()
            
            # Schedule recurring polls every 60 seconds
            self.scheduler.add_job(
                func=self.poll_consul,
                trigger="interval", 
                seconds=60,
                id='consul_poll',
                name='Poll Consul for service health'
            )
            
            self.scheduler.start()
            self.running = True
            logger.info("Background polling started")
            
            # Ensure cleanup on exit
            atexit.register(lambda: self.stop())
    
    def stop(self):
        """Stop the background polling"""
        if self.running:
            logger.info("Stopping Consul background polling...")
            self.scheduler.shutdown(wait=False)
            self.running = False
            logger.info("Background polling stopped")
    
    def poll_consul(self):
        """Poll Consul and update database - runs every minute"""
        try:
            logger.info("Polling Consul for service data...")
            
            if not consul_client.is_consul_available():
                logger.warning("Consul unavailable during background poll")
                return
            
            # Get fresh data from Consul
            service_data = consul_client.fetch_all_service_data()
            
            if not service_data:
                logger.warning("No service data received from Consul")
                return
            
            # Get database connection
            conn = self.get_db_conn()
            
            # Update database with fresh data
            services_updated = 0
            health_checks_inserted = 0
            
            for service_id, data in service_data.items():
                # Upsert service
                database.upsert_service(conn, {
                    'id': service_id,
                    'name': data['name'],
                    'address': data['address'],
                    'port': data['port'],
                    'tags': data['tags'],
                    'meta': data['meta']
                })
                services_updated += 1
                
                # Insert health checks - raw data points every minute
                for check in data['health_checks']:
                    database.insert_health_check(
                        conn, service_id, 
                        check['check_name'], 
                        check['status']
                    )
                    health_checks_inserted += 1
            
            conn.close()
            
            logger.info(f"Poll complete: {services_updated} services updated, "
                       f"{health_checks_inserted} health checks recorded")
                
        except Exception as e:
            logger.error(f"Error during Consul polling: {e}")

# Global poller instance
poller = None

def get_database_connection():
    """Factory function for database connections in background thread"""
    return database.init_database()

def start_background_polling():
    """Start the background polling service"""
    global poller
    if poller is None:
        poller = ConsulPoller(get_database_connection)
        poller.start()
    return poller

def stop_background_polling():
    """Stop the background polling service"""
    global poller
    if poller:
        poller.stop()
        poller = None
