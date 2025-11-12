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
        Get stock count for both Women and Men from Shein API with basic headers
        Returns: tuple (women_stock, men_stock, total_stock)
        """
        try:
            # Basic headers to mimic a normal browser request
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
            
            response = requests.get(
                self.config['api_url'],
                headers=headers,
                timeout=15
            )
            response.raise_for_status()
            
            print(f"✅ Response status: {response.status_code}")
            
            # Extract stock from response text using regex
            return self.extract_stock_from_response_text(response.text)
            
        except requests.RequestException as e:
            print(f"❌ Error making API request: {e}")
            return 0, 0, 0
        except Exception as e:
            print(f"❌ Unexpected error during API call: {e}")
            return 0, 0, 0
    
    def extract_stock_from_response_text(self, response_text):
        """Extract stock counts from response text using regex patterns"""
        women_stock = 0
        men_stock = 0
        
        try:
            # Debug: Check if we have the expected content
            if 'genderfilter-Women' not in response_text:
                print("⚠️ genderfilter-Women not found in response")
                # Save response for debugging
                with open('/tmp/debug_response.html', 'w', encoding='utf-8') as f:
                    f.write(response_text)
                print("📁 Saved response to /tmp/debug_response.html for inspection")
            
            # Pattern for women stock - more flexible pattern
            women_patterns = [
                r'"genderfilter-Women":\s*\{[^}]*"count":\s*(\d+)',
                r'genderfilter-Women[^}]*count[^}]*?(\d+)',
                r'Women[^}]*count[^}]*?(\d+)'
            ]
            
            for pattern in women_patterns:
                women_match = re.search(pattern, response_text)
                if women_match:
                    women_stock = int(women_match.group(1))
                    print(f"✅ Found women stock: {women_stock} with pattern: {pattern}")
                    break
            
            # Pattern for men stock - more flexible pattern
            men_patterns = [
                r'"genderfilter-Men":\s*\{[^}]*"count":\s*(\d+)',
                r'genderfilter-Men[^}]*count[^}]*?(\d+)',
                r'Men[^}]*count[^}]*?(\d+)'
            ]
            
            for pattern in men_patterns:
                men_match = re.search(pattern, response_text)
                if men_match:
                    men_stock = int(men_match.group(1))
                    print(f"✅ Found men stock: {men_stock} with pattern: {pattern}")
                    break
            else:
                # If no men stock found, set to 0
                men_stock = 0
                print("ℹ️ No men stock found, setting to 0")
                
            total_stock = women_stock + men_stock
            
            print(f"📊 Final stock - Women: {women_stock}, Men: {men_stock}, Total: {total_stock}")
            return women_stock, men_stock, total_stock
            
        except Exception as e:
            print(f"❌ Error extracting stock via regex: {e}")
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
        print("🔍 Checking Shein for stock updates...")
        
        # Get current stock counts
        women_stock, men_stock, current_total = self.get_shein_stock_count()
        
        if current_total == 0:
            print("❌ Could not retrieve stock count")
            return
        
        # Get previous stock counts
        prev_women, prev_men, previous_total = self.get_previous_stock()
        
        # Calculate change
        stock_change = current_total - previous_total
        
        print(f"📊 Stock - Women: {women_stock}, Men: {men_stock}, Total: {current_total}")
        print(f"📈 Change: {stock_change} (Previous Total: {previous_total})")
        
        # Check if significant increase
        if (stock_change >= self.config['min_increase_threshold'] and 
            current_total >= self.config['min_stock_threshold']):
            
            # Save with notification flag
            self.save_current_stock(women_stock, men_stock, current_total, stock_change)
            
            # Send notifications
            asyncio.run(self.send_stock_alert(women_stock, men_stock, current_total, previous_total, stock_change))
            print(f"✅ Sent alert for stock increase: +{stock_change}")
        
        else:
            # Save without notification
            self.save_current_stock(women_stock, men_stock, current_total, stock_change)
            print("✅ No significant stock change detected")
    
    async def send_stock_alert(self, women_stock, men_stock, current_total, previous_total, increase):
        """Send notifications for significant stock increase"""
        message = f"""
🚨 SVerse STOCK ALERT! 🚨

📈 **Stock Increased Significantly!**

👚 Women's Stock: {women_stock} items
👔 Men's Stock: {men_stock} items
📊 Total Stock: {current_total} items

🔄 Change: +{increase} items
📉 Previous Total: {previous_total} items

🔗 Check Now: {self.config['api_url']}

⏰ Alert Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

⚡ Quick! New SVerse items might be available!
        """.strip()
        
        # Send Telegram notification
        await self.send_telegram_message(message)
    
    async def send_test_notification(self):
        """Send a test notification to verify everything works"""
        test_message = f"""
🧪 TEST NOTIFICATION - Shein Stock Monitor

✅ Your Shein stock monitor is working correctly!
🤖 Bot is active and ready to send alerts
📱 You will receive notifications when SVerse stock increases

🔗 Monitoring: {self.config['api_url']}
⏰ Check Interval: {self.config['check_interval_seconds']} seconds
📈 Alert Threshold: +{self.config['min_increase_threshold']} items

⏰ Test Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🎉 Everything is set up properly!
        """.strip()
        
        await self.send_telegram_message(test_message)
        print("✅ Test notification sent successfully!")
    
    def start_monitoring_loop(self):
        """Start monitoring in background thread"""
        def monitor():
            print("🔄 Monitoring loop started!")
            while self.monitoring:
                self.check_stock()
                time.sleep(self.config['check_interval_seconds'])
            print("🛑 Monitoring loop stopped")
        
        self.monitor_thread = threading.Thread(target=monitor)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
    
    def start_monitoring(self):
        """Start the monitoring"""
        if self.monitoring:
            print("🔄 Monitoring is already running!")
            return
        
        self.monitoring = True
        self.start_monitoring_loop()
        
        # Send test notification
        asyncio.run(self.send_test_notification())
        
        # Initial check
        self.check_stock()
        
        print(f"✅ Monitor started successfully! Checking every {self.config['check_interval_seconds']} seconds...")
    
    def stop_monitoring(self):
        """Stop monitoring"""
        if not self.monitoring:
            print("❌ Monitoring is not running!")
            return
        
        self.monitoring = False
        print("🛑 Monitoring stopped!")

def main():
    """Main function"""
    print("🚀 Starting Shein Stock Monitor Cloud Bot...")
    print("💡 This bot runs 24/7 in the cloud!")
    print("📱 Sends Telegram alerts when stock increases")
    print(f"⏰ Check interval: {CONFIG['check_interval_seconds']} seconds")
    print(f"📈 Alert threshold: +{CONFIG['min_increase_threshold']} items")
    
    monitor = SheinStockMonitor(CONFIG)
    
    # Start monitoring immediately
    monitor.start_monitoring()
    
    print("✅ Monitor is running! It will continue automatically.")
    print("💡 The bot will check stock every 10 seconds and send alerts for significant increases.")
    
    try:
        # Keep the main thread alive
        while True:
            time.sleep(60)  # Check every minute if still running
            
    except KeyboardInterrupt:
        print("\n🛑 Stopping monitor...")
        monitor.stop_monitoring()

if __name__ == "__main__":
    main()
