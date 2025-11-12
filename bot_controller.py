import requests
from bs4 import BeautifulSoup
import sqlite3
import time
import logging
import json
from datetime import datetime
import os
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
        Get stock count for both Women and Men from Shein API using the working method
        Returns: tuple (women_stock, men_stock, total_stock)
        """
        try:
            headers = {
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'accept-language': 'en-US,en;q=0.9',
                'cache-control': 'no-cache',
                'pragma': 'no-cache',
                'priority': 'u=0, i',
                'sec-ch-ua': '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'document',
                'sec-fetch-mode': 'navigate',
                'sec-fetch-site': 'same-origin',
                'sec-fetch-user': '?1',
                'upgrade-insecure-requests': '1',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
            }
            
            response = requests.get(
                self.config['api_url'],
                headers=headers,
                timeout=15
            )
            response.raise_for_status()
            
            # Parse the HTML response to find the JSON data - USING WORKING METHOD
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for script tags containing product data
            scripts = soup.find_all('script')
            for script in scripts:
                script_content = script.string
                if script_content and 'facets' in script_content and 'genderfilter' in script_content:
                    try:
                        # Extract JSON data from script tag - WORKING METHOD
                        if 'window.goodsDetailData' in script_content:
                            json_str = script_content.split('window.goodsDetailData = ')[1].split(';')[0]
                            data = json.loads(json_str)
                            return self.extract_gender_stock_from_data(data)
                        elif 'window.goodsListV2' in script_content:
                            json_str = script_content.split('window.goodsListV2 = ')[1].split(';')[0]
                            data = json.loads(json_str)
                            return self.extract_gender_stock_from_data(data)
                    except (json.JSONDecodeError, IndexError, KeyError) as e:
                        print(f"⚠️ Error parsing script data: {e}")
                        continue
            
            # Alternative: Search for gender patterns in the entire response
            response_text = response.text
            return self.extract_gender_stock_from_response(response_text)
            
        except requests.RequestException as e:
            print(f"❌ Error making API request: {e}")
            return 0, 0, 0
        except Exception as e:
            print(f"❌ Unexpected error during API call: {e}")
            return 0, 0, 0
    
    def extract_gender_stock_from_data(self, data):
        """Extract women and men stock counts from JSON data"""
        women_stock = 0
        men_stock = 0
        
        try:
            # Navigate through the JSON structure to find gender filters
            facets = data.get('facets', {})
            if not facets:
                # Try alternative location
                facets = data.get('result', {}).get('facets', {})
            
            gender_filter = facets.get('genderfilter', {})
            
            # Extract women stock
            women_data = gender_filter.get('genderfilter-Women', {})
            if women_data and 'count' in women_data:
                women_stock = women_data['count']
            
            # Extract men stock
            men_data = gender_filter.get('genderfilter-Men', {})
            if men_data and 'count' in men_data:
                men_stock = men_data['count']
            else:
                men_stock = 0
                
            total_stock = women_stock + men_stock
            
            print(f"✅ Found stock - Women: {women_stock}, Men: {men_stock}, Total: {total_stock}")
            return women_stock, men_stock, total_stock
            
        except Exception as e:
            print(f"❌ Error extracting gender stock from data: {e}")
            return 0, 0, 0
    
    def extract_gender_stock_from_response(self, response_text):
        """Extract gender stock counts from response text using regex patterns"""
        women_stock = 0
        men_stock = 0
        
        try:
            # Pattern for women stock
            women_pattern = r'"genderfilter-Women":\s*\{[^}]*"count":\s*(\d+)'
            women_match = re.search(women_pattern, response_text)
            if women_match:
                women_stock = int(women_match.group(1))
            
            # Pattern for men stock
            men_pattern = r'"genderfilter-Men":\s*\{[^}]*"count":\s*(\d+)'
            men_match = re.search(men_pattern, response_text)
            if men_match:
                men_stock = int(men_match.group(1))
            else:
                men_stock = 0
                
            total_stock = women_stock + men_stock
            
            print(f"✅ Found stock via regex - Women: {women_stock}, Men: {men_stock}, Total: {total_stock}")
            return women_stock, men_stock, total_stock
            
        except Exception as e:
            print(f"❌ Error extracting gender stock via regex: {e}")
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
