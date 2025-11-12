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
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackContext
from telegram import ReplyKeyboardMarkup, KeyboardButton

# Configuration
CONFIG = {
    'telegram_bot_token': '8413664821:AAHjBwysQWk3GFdJV3Bvk3Jp1vhDLpoymI8',
    'telegram_chat_id': '1366899854',
    'api_url': 'https://www.sheinindia.in/c/sverse-5939-37961',
    'check_interval_minutes': 0.1667,
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
        self.telegram_app = None
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
                total_stock INTEGER,
                men_count INTEGER DEFAULT 0,
                women_count INTEGER DEFAULT 0,
                stock_change INTEGER DEFAULT 0,
                notified BOOLEAN DEFAULT FALSE
            )
        ''')
        self.conn.commit()
        print("✅ Database setup completed")
    
    def extract_gender_counts(self, data):
        """
        Extract men and women counts from the JSON data
        Returns: (men_count, women_count)
        """
        men_count = 0
        women_count = 0
        
        try:
            # Method 1: Look for genderfilter objects directly in the data
            if 'genderfilter-Women' in data:
                women_data = data.get('genderfilter-Women', {})
                women_count = women_data.get('count', 0)
                print(f"✅ Found women count in genderfilter-Women: {women_count}")
            
            if 'genderfilter-Men' in data:
                men_data = data.get('genderfilter-Men', {})
                men_count = men_data.get('count', 0)
                print(f"✅ Found men count in genderfilter-Men: {men_count}")
            
            # Method 2: Search through all keys for genderfilter patterns
            if men_count == 0 and women_count == 0:
                for key, value in data.items():
                    if isinstance(value, dict):
                        # Check for women count
                        if 'genderfilter-Women' in key or ('name' in value and value.get('name') == 'Women'):
                            women_count = value.get('count', 0)
                            if women_count > 0:
                                print(f"✅ Found women count in {key}: {women_count}")
                        
                        # Check for men count
                        if 'genderfilter-Men' in key or ('name' in value and value.get('name') == 'Men'):
                            men_count = value.get('count', 0)
                            if men_count > 0:
                                print(f"✅ Found men count in {key}: {men_count}")
            
            # Method 3: Deep search in the entire data structure
            if men_count == 0 and women_count == 0:
                data_str = json.dumps(data)
                
                # Look for women count using regex - specific pattern from the response
                women_pattern = r'"genderfilter-Women":\s*\{[^}]*"count":\s*(\d+)'
                women_match = re.search(women_pattern, data_str)
                if women_match:
                    women_count = int(women_match.group(1))
                    print(f"✅ Found women count via regex: {women_count}")
                
                # Look for men count using regex - specific pattern from the response
                men_pattern = r'"genderfilter-Men":\s*\{[^}]*"count":\s*(\d+)'
                men_match = re.search(men_pattern, data_str)
                if men_match:
                    men_count = int(men_match.group(1))
                    print(f"✅ Found men count via regex: {men_count}")
                
                # Alternative regex patterns
                if women_count == 0:
                    women_pattern2 = r'"name":"Women"[^}]*"count":\s*(\d+)'
                    women_match2 = re.search(women_pattern2, data_str)
                    if women_match2:
                        women_count = int(women_match2.group(1))
                        print(f"✅ Found women count via alternative regex: {women_count}")
                
                if men_count == 0:
                    men_pattern2 = r'"name":"Men"[^}]*"count":\s*(\d+)'
                    men_match2 = re.search(men_pattern2, data_str)
                    if men_match2:
                        men_count = int(men_match2.group(1))
                        print(f"✅ Found men count via alternative regex: {men_count}")
            
        except Exception as e:
            print(f"⚠️ Error extracting gender counts: {e}")
        
        return men_count, women_count
    
    def get_shein_stock_count(self):
        """
        Get total stock count and gender-specific counts from Shein API
        Returns: (total_stock, men_count, women_count)
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
            
            # Parse the HTML response to find the JSON data
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for script tags containing product data
            scripts = soup.find_all('script')
            for script in scripts:
                script_content = script.string
                if script_content and 'facets' in script_content and 'totalResults' in script_content:
                    try:
                        # Extract JSON data from script tag
                        if 'window.goodsDetailData' in script_content:
                            json_str = script_content.split('window.goodsDetailData = ')[1].split(';')[0]
                            data = json.loads(json_str)
                            total_stock = data.get('facets', {}).get('totalResults', 0)
                            
                            # Extract men and women counts
                            men_count, women_count = self.extract_gender_counts(data)
                            
                            print(f"✅ Found total stock: {total_stock}, Men: {men_count}, Women: {women_count}")
                            return total_stock, men_count, women_count
                    except (json.JSONDecodeError, IndexError, KeyError) as e:
                        print(f"⚠️ Error parsing script data: {e}")
                        continue
            
            # Alternative: Search for the pattern in the entire response
            response_text = response.text
            if 'facets' in response_text and 'totalResults' in response_text:
                # Extract total stock
                pattern = r'"facets":\s*\{[^}]*"totalResults":\s*(\d+)'
                match = re.search(pattern, response_text)
                if match:
                    total_stock = int(match.group(1))
                    
                    # Extract gender counts from response text
                    men_count, women_count = self.extract_gender_counts_from_text(response_text)
                    
                    print(f"✅ Found total stock via regex: {total_stock}, Men: {men_count}, Women: {women_count}")
                    return total_stock, men_count, women_count
            
            print("❌ Could not find stock count in response")
            return 0, 0, 0
            
        except requests.RequestException as e:
            print(f"❌ Error making API request: {e}")
            return 0, 0, 0
        except Exception as e:
            print(f"❌ Unexpected error during API call: {e}")
            return 0, 0, 0
    
    def extract_gender_counts_from_text(self, response_text):
        """
        Extract men and women counts from response text using regex
        """
        men_count = 0
        women_count = 0
        
        try:
            # Primary method: Look for the exact genderfilter objects
            women_pattern = r'"genderfilter-Women":\s*\{[^}]*"count":\s*(\d+)'
            women_match = re.search(women_pattern, response_text)
            if women_match:
                women_count = int(women_match.group(1))
                print(f"✅ Found women count via text regex: {women_count}")
            
            men_pattern = r'"genderfilter-Men":\s*\{[^}]*"count":\s*(\d+)'
            men_match = re.search(men_pattern, response_text)
            if men_match:
                men_count = int(men_match.group(1))
                print(f"✅ Found men count via text regex: {men_count}")
            
            # Secondary method: Look for name and count patterns
            if women_count == 0:
                women_pattern2 = r'"name":"Women"[^}]*"count":\s*(\d+)'
                women_match2 = re.search(women_pattern2, response_text)
                if women_match2:
                    women_count = int(women_match2.group(1))
                    print(f"✅ Found women count via alternative text regex: {women_count}")
            
            if men_count == 0:
                men_pattern2 = r'"name":"Men"[^}]*"count":\s*(\d+)'
                men_match2 = re.search(men_pattern2, response_text)
                if men_match2:
                    men_count = int(men_match2.group(1))
                    print(f"✅ Found men count via alternative text regex: {men_count}")
                
        except Exception as e:
            print(f"⚠️ Error extracting gender counts from text: {e}")
        
        return men_count, women_count
    
    def get_previous_stock(self):
        """Get the last recorded stock count from database"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT total_stock, men_count, women_count FROM stock_history ORDER BY timestamp DESC LIMIT 1')
        result = cursor.fetchone()
        if result:
            return result[0], result[1], result[2]
        return 0, 0, 0
    
    def save_current_stock(self, current_stock, men_count, women_count, change=0):
        """Save current stock count to database"""
        cursor = self.conn.cursor()
        cursor.execute('INSERT INTO stock_history (total_stock, men_count, women_count, stock_change) VALUES (?, ?, ?, ?)', 
                      (current_stock, men_count, women_count, change))
        self.conn.commit()
    
    async def send_telegram_message(self, message, chat_id=None):
        """Send message via Telegram"""
        try:
            if chat_id is None:
                chat_id = self.config['telegram_chat_id']
            
            bot = Bot(token=self.config['telegram_bot_token'])
            await bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode='HTML'
            )
            return True
        except Exception as e:
            print(f"❌ Error sending Telegram message: {e}")
            return False
    
    async def send_telegram_message_with_keyboard(self, message, chat_id):
        """Send message with custom keyboard"""
        try:
            keyboard = [
                [KeyboardButton("/start_monitor"), KeyboardButton("/stop_monitor")],
                [KeyboardButton("/check_now"), KeyboardButton("/status")]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            bot = Bot(token=self.config['telegram_bot_token'])
            await bot.send_message(
                chat_id=chat_id,
                text=message,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
            return True
        except Exception as e:
            print(f"❌ Error sending Telegram message with keyboard: {e}")
            return False
    
    def check_stock(self, manual_check=False, chat_id=None):
        """Check if stock has significantly increased"""
        print("🔍 Checking Shein for stock updates...")
        
        # Get current stock count and gender counts
        current_stock, men_count, women_count = self.get_shein_stock_count()
        if current_stock == 0:
            error_msg = "❌ Could not retrieve stock count"
            print(error_msg)
            if manual_check and chat_id:
                asyncio.run(self.send_telegram_message(error_msg, chat_id))
            return
        
        # Get previous stock count and gender counts
        previous_stock, prev_men_count, prev_women_count = self.get_previous_stock()
        
        # Calculate change
        stock_change = current_stock - previous_stock
        
        print(f"📊 Stock: {current_stock} (Previous: {previous_stock}, Change: {stock_change})")
        print(f"👕 Men: {men_count}, Women: {women_count}")
        
        # If manual check, always send current status
        if manual_check and chat_id:
            status_message = f"""
📊 CURRENT STOCK STATUS:

🔄 Total Items: {current_stock}
📈 Change from last check: {stock_change}

👕 Gender Breakdown:
   • Men: {men_count} items
   • Women: {women_count} items

⏰ Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🔗 {self.config['api_url']}
            """.strip()
            asyncio.run(self.send_telegram_message(status_message, chat_id))
        
        # Check if significant increase for automatic alerts
        if (stock_change >= self.config['min_increase_threshold'] and 
            current_stock >= self.config['min_stock_threshold'] and
            not manual_check):
            
            # Save with notification flag
            self.save_current_stock(current_stock, men_count, women_count, stock_change)
            
            # Send notifications
            asyncio.run(self.send_stock_alert(current_stock, previous_stock, stock_change, men_count, women_count))
            print(f"✅ Sent alert for stock increase: +{stock_change}")
        
        else:
            # Save without notification
            self.save_current_stock(current_stock, men_count, women_count, stock_change)
            if not manual_check:
                print("✅ No significant stock change detected")
    
    async def send_stock_alert(self, current_stock, previous_stock, increase, men_count, women_count):
        """Send notifications for significant stock increase"""
        message = f"""
🚨 SVerse STOCK ALERT! 🚨

📈 **Stock Increased Significantly!**

🔄 Change: +{increase} items
📊 Current Total: {current_stock} items
📉 Previous Total: {previous_stock} items

👕 Gender Breakdown:
   • Men: {men_count} items
   • Women: {women_count} items

🔗 Check Now: {self.config['api_url']}

⏰ Alert Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

⚡ Quick! New SVerse items might be available!
        """.strip()
        
        # Send Telegram notification
        await self.send_telegram_message(message)
    
    async def send_test_notification(self, chat_id=None):
        """Send a test notification to verify everything works"""
        test_message = f"""
🧪 TEST NOTIFICATION - Shein Stock Monitor

✅ Your Shein stock monitor is working correctly!
🤖 Bot is active and ready to send alerts
📱 You will receive notifications when SVerse stock increases

🔗 Monitoring: {self.config['api_url']}

⏰ Test Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🎉 Everything is set up properly!
        """.strip()
        
        await self.send_telegram_message(test_message, chat_id)
        print("✅ Test notification sent successfully!")
    
    def start_monitoring_loop(self):
        """Start monitoring in background thread"""
        def monitor():
            print("🔄 Monitoring loop started!")
            while self.monitoring:
                self.check_stock()
                time.sleep(self.config['check_interval_minutes'] * 60)
            print("🛑 Monitoring loop stopped")
        
        self.monitor_thread = threading.Thread(target=monitor)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
    
    async def start_monitoring_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start the monitoring via command"""
        if self.monitoring:
            await update.message.reply_text("🔄 Monitoring is already running!")
            return
        
        self.monitoring = True
        self.start_monitoring_loop()
        
        # Send welcome message with keyboard
        welcome_message = """
✅ Shein Stock Monitor STARTED!

🤖 Bot is now actively monitoring SVerse stock
📱 You will receive alerts when stock increases significantly
⏰ Checking every 5 minutes automatically

Use the buttons below to control the monitor:
• /stop_monitor - Stop monitoring
• /check_now - Check stock immediately
• /status - Current status
        """.strip()
        
        await self.send_telegram_message_with_keyboard(welcome_message, update.effective_chat.id)
        
        # Send test notification
        await self.send_test_notification(update.effective_chat.id)
        
        # Initial check
        self.check_stock()
        
        print("✅ Monitor started via command!")
    
    async def stop_monitoring_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Stop monitoring via command"""
        if not self.monitoring:
            await update.message.reply_text("❌ Monitoring is not running!")
            return
        
        self.monitoring = False
        await update.message.reply_text("🛑 Monitoring stopped!")
        print("🛑 Monitoring stopped via command!")
    
    async def check_now_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check stock immediately via command"""
        await update.message.reply_text("🔍 Checking stock immediately...")
        print("🔍 Manual stock check requested")
        self.check_stock(manual_check=True, chat_id=update.effective_chat.id)
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get current status via command"""
        status = "🟢 RUNNING" if self.monitoring else "🔴 STOPPED"
        
        # Get latest stock data
        cursor = self.conn.cursor()
        cursor.execute('SELECT total_stock, men_count, women_count, timestamp FROM stock_history ORDER BY timestamp DESC LIMIT 1')
        result = cursor.fetchone()
        
        if result:
            total_stock, men_count, women_count, last_check = result
            status_message = f"""
🤖 SHEIN STOCK MONITOR STATUS

📊 Monitor Status: {status}
⏰ Last Check: {last_check}
🔄 Check Interval: 5 minutes

📈 Latest Stock Data:
   • Total Items: {total_stock}
   • Men: {men_count}
   • Women: {women_count}

🔗 Monitoring: {self.config['api_url']}
            """.strip()
        else:
            status_message = f"""
🤖 SHEIN STOCK MONITOR STATUS

📊 Monitor Status: {status}
⏰ Last Check: Never
🔄 Check Interval: 5 minutes

📈 No stock data collected yet.

🔗 Monitoring: {self.config['api_url']}
            """.strip()
        
        await update.message.reply_text(status_message)
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Initial start command with welcome message"""
        welcome_message = """
🤖 Welcome to Shein Stock Monitor!

I will monitor SVerse stock and alert you when new items are added.

Available Commands:
• /start_monitor - Start automatic monitoring
• /stop_monitor - Stop monitoring
• /check_now - Check stock immediately
• /status - Current monitor status
• /start - Show this help message

Use the buttons below to control the monitor!
        """.strip()
        
        await self.send_telegram_message_with_keyboard(welcome_message, update.effective_chat.id)
    
    def setup_telegram_commands(self):
        """Setup Telegram bot command handlers"""
        self.telegram_app = Application.builder().token(self.config['telegram_bot_token']).build()
        
        # Add command handlers
        self.telegram_app.add_handler(CommandHandler("start", self.start_command))
        self.telegram_app.add_handler(CommandHandler("start_monitor", self.start_monitoring_command))
        self.telegram_app.add_handler(CommandHandler("stop_monitor", self.stop_monitoring_command))
        self.telegram_app.add_handler(CommandHandler("check_now", self.check_now_command))
        self.telegram_app.add_handler(CommandHandler("status", self.status_command))
        
        print("✅ Telegram commands setup completed")
    
    async def start_telegram_polling(self):
        """Start Telegram bot polling"""
        if self.telegram_app:
            print("🤖 Starting Telegram bot polling...")
            await self.telegram_app.run_polling()
    
    def start_telegram_in_background(self):
        """Start Telegram bot in background thread"""
        def run_bot():
            asyncio.run(self.start_telegram_polling())
        
        bot_thread = threading.Thread(target=run_bot)
        bot_thread.daemon = True
        bot_thread.start()
        print("✅ Telegram bot started in background")

def main():
    """Main function"""
    print("🚀 Starting Shein Stock Monitor Cloud Bot...")
    print("💡 This bot runs 24/7 in the cloud!")
    print("📱 Sends Telegram alerts when stock increases")
    
    monitor = SheinStockMonitor(CONFIG)
    
    # Setup Telegram commands
    monitor.setup_telegram_commands()
    
    # Start Telegram bot in background
    monitor.start_telegram_in_background()
    
    # Start monitoring immediately (optional - you can remove this if you want only manual start)
    # monitor.start_monitoring()
    
    print("✅ Monitor is running! It will continue automatically.")
    print("💡 Use Telegram commands to control the monitor.")
    print("🤖 Bot is listening for commands...")
    
    try:
        # Keep the main thread alive
        while True:
            time.sleep(60)  # Check every minute if still running
            
    except KeyboardInterrupt:
        print("\n🛑 Stopping monitor...")
        monitor.stop_monitoring()

if __name__ == "__main__":
    main()
