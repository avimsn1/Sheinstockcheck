import requests
import sqlite3
import time
import logging
import json
from datetime import datetime
import threading
import re
import asyncio

# Configuration
CONFIG = {
    'telegram_bot_token': '8413664821:AAHjBwysQWk3GFdJV3Bvk3Jp1vhDLpoymI8',
    'telegram_chat_id': '1366899854',
    'api_url': 'https://www.sheinindia.in/c/sverse-5939-37961',
    'check_interval_seconds': 10,
    'min_stock_threshold': 10,
    'database_path': '/tmp/shein_monitor.db',
    'min_increase_threshold': 10
}

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class SheinStockMonitor:
    def __init__(self, config):
        self.config = config
        self.monitoring = False
        self.monitor_thread = None
        self.setup_database()
        print("🤖 Shein Monitor initialized")
    
    def setup_database(self):
        """Initialize SQLite database"""
        self.conn = sqlite3.connect(self.config['database_path'], check_same_thread=False)
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                women_stock INTEGER,
                men_stock INTEGER,
                total_stock INTEGER,
                stock_change INTEGER DEFAULT 0,
                notified BOOLEAN DEFAULT FALSE
            )
        ''')
        self.conn.commit()
        print("✅ Database setup completed")
    
    def get_shein_stock_count(self):
        """
        Simple curl-like request to get women and men stock counts
        Returns: tuple (women_stock, men_stock, total_stock)
        """
        try:
            # Simple request without any headers - just like curl
            response = requests.get(self.config['api_url'], timeout=15)
            response.raise_for_status()
            
            response_text = response.text
            print("✅ Got response from Shein")
            
            # Extract women stock
            women_match = re.search(r'"genderfilter-Women":\{[^}]*"count":\s*(\d+)', response_text)
            women_stock = int(women_match.group(1)) if women_match else 0
            
            # Extract men stock
            men_match = re.search(r'"genderfilter-Men":\{[^}]*"count":\s*(\d+)', response_text)
            men_stock = int(men_match.group(1)) if men_match else 0
            
            total_stock = women_stock + men_stock
            
            print(f"📊 Women: {women_stock}, Men: {men_stock}, Total: {total_stock}")
            return women_stock, men_stock, total_stock
            
        except Exception as e:
            print(f"❌ Error: {e}")
            return 0, 0, 0
    
    def get_previous_stock(self):
        """Get the last recorded stock counts from database"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT women_stock, men_stock, total_stock FROM stock_history ORDER BY timestamp DESC LIMIT 1')
        result = cursor.fetchone()
        if result:
            return result[0], result[1], result[2]  # women, men, total
        return 0, 0, 0
    
    def save_current_stock(self, women_stock, men_stock, total_stock, change=0):
        """Save current stock counts to database"""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO stock_history (women_stock, men_stock, total_stock, stock_change) 
            VALUES (?, ?, ?, ?)
        ''', (women_stock, men_stock, total_stock, change))
        self.conn.commit()
    
    async def send_telegram_message(self, message):
        """Send message via Telegram"""
        try:
            from telegram import Bot
            
            bot = Bot(token=self.config['telegram_bot_token'])
            await bot.send_message(
                chat_id=self.config['telegram_chat_id'],
                text=message,
                parse_mode='HTML'
            )
            return True
        except Exception as e:
            print(f"❌ Error sending Telegram message: {e}")
            return False
    
    def check_stock(self):
        """Check if stock has significantly increased"""
        print("🔍 Checking stock...")
        
        # Get current stock counts
        women_stock, men_stock, current_total = self.get_shein_stock_count()
        
        if current_total == 0:
            print("❌ Could not retrieve stock count")
            return
        
        # Get previous stock counts
        prev_women, prev_men, previous_total = self.get_previous_stock()
        
        # Calculate change
        stock_change = current_total - previous_total
        
        print(f"📈 Change: {stock_change} (Previous: {previous_total})")
        
        # Check if significant increase
        if stock_change >= self.config['min_increase_threshold']:
            
            # Save with notification
            self.save_current_stock(women_stock, men_stock, current_total, stock_change)
            
            # Send alert
            asyncio.run(self.send_stock_alert(women_stock, men_stock, current_total, previous_total, stock_change))
            print(f"🚨 Sent alert for stock increase: +{stock_change}")
        
        else:
            # Save without notification
            self.save_current_stock(women_stock, men_stock, current_total, stock_change)
            print("✅ No significant change")
    
    async def send_stock_alert(self, women_stock, men_stock, current_total, previous_total, increase):
        """Send notifications for significant stock increase"""
        message = f"""
🚨 SVerse STOCK ALERT! 🚨

📈 **Stock Increased!**

👚 Women: {women_stock} items
👔 Men: {men_stock} items
📊 Total: {current_total} items

🔄 Change: +{increase} items
📉 Previous: {previous_total} items

🔗 Check: {self.config['api_url']}

⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

⚡ Quick! New items available!
        """.strip()
        
        await self.send_telegram_message(message)
    
    async def send_test_notification(self):
        """Send a test notification"""
        test_message = f"""
🧪 TEST - Shein Stock Monitor

✅ Monitor is working!
🤖 Bot is active
📱 Alerts enabled

🔗 {self.config['api_url']}
⏰ Check: {self.config['check_interval_seconds']}s
📈 Alert: +{self.config['min_increase_threshold']} items

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """.strip()
        
        await self.send_telegram_message(test_message)
        print("✅ Test notification sent!")
    
    def start_monitoring_loop(self):
        """Start monitoring in background thread"""
        def monitor():
            print("🔄 Monitoring started!")
            while self.monitoring:
                self.check_stock()
                time.sleep(self.config['check_interval_seconds'])
            print("🛑 Monitoring stopped")
        
        self.monitor_thread = threading.Thread(target=monitor)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
    
    def start_monitoring(self):
        """Start the monitoring"""
        if self.monitoring:
            print("🔄 Already running!")
            return
        
        self.monitoring = True
        self.start_monitoring_loop()
        
        # Send test notification
        asyncio.run(self.send_test_notification())
        
        # Initial check
        self.check_stock()
        
        print(f"✅ Monitoring every {self.config['check_interval_seconds']} seconds")
    
    def stop_monitoring(self):
        """Stop monitoring"""
        if not self.monitoring:
            print("❌ Not running!")
            return
        
        self.monitoring = False
        print("🛑 Stopped!")

def main():
    """Main function"""
    print("🚀 Starting Shein Stock Monitor...")
    print("📱 Telegram alerts enabled")
    print(f"⏰ Check every: {CONFIG['check_interval_seconds']} seconds")
    print(f"📈 Alert threshold: +{CONFIG['min_increase_threshold']} items")
    
    monitor = SheinStockMonitor(CONFIG)
    monitor.start_monitoring()
    
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n🛑 Stopping...")
        monitor.stop_monitoring()

if __name__ == "__main__":
    main()
