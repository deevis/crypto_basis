import os
import json
import logging
import subprocess
import time
import smtplib
import requests
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from btc_service import BTCService
from pathlib import Path
import binascii
from db_config import SessionLocal, init_db
from models import OPReturnScan, LargeOPReturn
from sqlalchemy import func

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s:%(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

class NotificationManager:
    """Manages notifications via multiple free channels
    
    Setup Instructions:
    
    1. EMAIL (SMTP - Gmail, Outlook, etc.):
       Set in .env:
       NOTIFY_EMAIL_ENABLED=true
       NOTIFY_EMAIL_SMTP_SERVER=smtp.gmail.com (or smtp-mail.outlook.com for Outlook)
       NOTIFY_EMAIL_SMTP_PORT=587
       NOTIFY_EMAIL_USERNAME=your-email@gmail.com
       NOTIFY_EMAIL_PASSWORD=your-app-password  # Use app password for Gmail
       NOTIFY_EMAIL_TO=recipient@example.com
       NOTIFY_EMAIL_FROM=your-email@gmail.com (optional, defaults to username)
    
    2. TELEGRAM BOT (Free, no credit card):
       a) Create a bot: Message @BotFather on Telegram, send /newbot
       b) Get your bot token
       c) Get your chat ID: Message your bot, then visit:
          https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
       Set in .env:
       NOTIFY_TELEGRAM_ENABLED=true
       NOTIFY_TELEGRAM_BOT_TOKEN=your-bot-token
       NOTIFY_TELEGRAM_CHAT_ID=your-chat-id
    
    3. DISCORD WEBHOOK (Free):
       a) Discord Server Settings > Integrations > Webhooks > New Webhook
       b) Copy webhook URL
       Set in .env:
       NOTIFY_DISCORD_ENABLED=true
       NOTIFY_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
    
    3b. STATUS DISCORD WEBHOOK (Free, separate channel for startup/heartbeat):
       a) Create a separate webhook for status messages (startup, heartbeat)
       b) Copy webhook URL
       Set in .env:
       NOTIFY_STATUS_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
       (Automatically enabled if URL is provided)
    
    4. SMS via EMAIL (Free, carrier-dependent):
       Use carrier email-to-SMS gateway (e.g., 1234567890@vtext.com for Verizon)
       Set in .env:
       NOTIFY_SMS_ENABLED=true
       NOTIFY_SMS_EMAIL_TO=1234567890@vtext.com
       (Also requires email SMTP settings above)
    """
    
    def __init__(self):
        load_dotenv()
        
        # Email (SMTP) configuration
        self.email_enabled = os.getenv('NOTIFY_EMAIL_ENABLED', 'false').lower() in ('true', '1', 'yes')
        self.email_smtp_server = os.getenv('NOTIFY_EMAIL_SMTP_SERVER', 'smtp.gmail.com')
        self.email_smtp_port = int(os.getenv('NOTIFY_EMAIL_SMTP_PORT', '587'))
        self.email_username = os.getenv('NOTIFY_EMAIL_USERNAME')
        self.email_password = os.getenv('NOTIFY_EMAIL_PASSWORD')  # App password for Gmail
        self.email_to = os.getenv('NOTIFY_EMAIL_TO')
        self.email_from = os.getenv('NOTIFY_EMAIL_FROM', self.email_username)
        
        # Telegram Bot configuration
        self.telegram_enabled = os.getenv('NOTIFY_TELEGRAM_ENABLED', 'false').lower() in ('true', '1', 'yes')
        self.telegram_bot_token = os.getenv('NOTIFY_TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.getenv('NOTIFY_TELEGRAM_CHAT_ID')
        
        # Discord Webhook configuration
        self.discord_enabled = os.getenv('NOTIFY_DISCORD_ENABLED', 'false').lower() in ('true', '1', 'yes')
        self.discord_webhook_url = os.getenv('NOTIFY_DISCORD_WEBHOOK_URL')
        
        # Status Discord Webhook configuration (for startup/heartbeat messages)
        self.status_discord_enabled = os.getenv('NOTIFY_STATUS_DISCORD_ENABLED', 'false').lower() in ('true', '1', 'yes')
        self.status_discord_webhook_url = os.getenv('NOTIFY_STATUS_DISCORD_WEBHOOK_URL')
        if not self.status_discord_enabled and self.status_discord_webhook_url:
            # Auto-enable if URL is provided
            self.status_discord_enabled = True
        
        # Email-to-SMS configuration (carrier gateways)
        self.sms_enabled = os.getenv('NOTIFY_SMS_ENABLED', 'false').lower() in ('true', '1', 'yes')
        self.sms_email_to = os.getenv('NOTIFY_SMS_EMAIL_TO')  # e.g., 1234567890@vtext.com for Verizon
        
        # Check if any notification method is configured
        self.any_enabled = (
            self.email_enabled or 
            self.telegram_enabled or 
            self.discord_enabled or 
            self.sms_enabled
        )
        
        if self.any_enabled:
            logger.info("🔔 Notification system enabled")
            if self.email_enabled:
                logger.info(f"   📧 Email: {self.email_to}")
            if self.telegram_enabled:
                logger.info(f"   📱 Telegram: Chat ID {self.telegram_chat_id}")
            if self.discord_enabled:
                logger.info(f"   💬 Discord: Webhook configured")
            if self.status_discord_enabled:
                logger.info(f"   📊 Status Discord: Webhook configured")
            if self.sms_enabled:
                logger.info(f"   📲 SMS: {self.sms_email_to}")
        else:
            logger.debug("🔕 Notification system disabled (set NOTIFY_* environment variables)")
    
    def send_email(self, subject, body):
        """Send email via SMTP"""
        if not self.email_enabled or not self.email_username or not self.email_password or not self.email_to:
            return False
        
        try:
            msg = MIMEMultipart()
            msg['From'] = self.email_from
            msg['To'] = self.email_to
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))
            
            server = smtplib.SMTP(self.email_smtp_server, self.email_smtp_port)
            server.starttls()
            server.login(self.email_username, self.email_password)
            server.send_message(msg)
            server.quit()
            
            logger.debug(f"   ✓ Email sent to {self.email_to}")
            return True
        except Exception as e:
            logger.warning(f"   ⚠️  Email notification failed: {e}")
            return False
    
    def send_telegram(self, message):
        """Send message via Telegram Bot"""
        if not self.telegram_enabled or not self.telegram_bot_token or not self.telegram_chat_id:
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            payload = {
                'chat_id': self.telegram_chat_id,
                'text': message,
                'parse_mode': 'HTML'
            }
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            
            logger.debug(f"   ✓ Telegram message sent")
            return True
        except Exception as e:
            logger.warning(f"   ⚠️  Telegram notification failed: {e}")
            return False
    
    def send_discord(self, message, file_path=None, file_name=None):
        """Send message via Discord webhook, optionally with file attachment"""
        if not self.discord_enabled or not self.discord_webhook_url:
            return False
        
        try:
            if file_path and file_path.exists():
                # Send with file attachment
                with open(file_path, 'rb') as f:
                    files = {
                        'file': (file_name or file_path.name, f.read())
                    }
                    payload = {
                        'content': message
                    }
                    response = requests.post(
                        self.discord_webhook_url,
                        data=payload,
                        files=files,
                        timeout=30
                    )
            else:
                # Send text-only message
                payload = {
                    'content': message
                }
                response = requests.post(self.discord_webhook_url, json=payload, timeout=10)
            
            response.raise_for_status()
            
            logger.debug(f"   ✓ Discord message sent" + (" with file attachment" if file_path else ""))
            return True
        except Exception as e:
            logger.warning(f"   ⚠️  Discord notification failed: {e}")
            return False
    
    def send_status_discord(self, message):
        """Send status message via status Discord webhook (for startup/heartbeat)"""
        if not self.status_discord_enabled or not self.status_discord_webhook_url:
            return False
        
        try:
            payload = {
                'content': message
            }
            response = requests.post(self.status_discord_webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            
            logger.debug(f"   ✓ Status Discord message sent")
            return True
        except Exception as e:
            logger.warning(f"   ⚠️  Status Discord notification failed: {e}")
            return False
    
    def send_sms(self, message):
        """Send SMS via email-to-SMS gateway"""
        if not self.sms_enabled or not self.sms_email_to:
            return False
        
        # Use email system to send SMS
        return self.send_email(f"OP_RETURN Alert", message)
    
    def notify_startup(self, interval_seconds, heartbeat_interval=None):
        """Send notification when continual scanning starts
        
        If status Discord webhook is configured, send startup messages there.
        Otherwise, send to regular notification channels (Email, Telegram, SMS, Discord).
        """
        subject = "🔄 OP_RETURN Scanner Started"
        message = f"OP_RETURN continual scanning started\nInterval: {interval_seconds} seconds"
        if heartbeat_interval:
            message += f"\nHeartbeat interval: {heartbeat_interval} seconds"
        message += "\nMonitoring for new large OP_RETURNs..."
        
        html_message = f"<b>🔄 OP_RETURN Scanner Started</b>\n\nInterval: {interval_seconds} seconds"
        if heartbeat_interval:
            html_message += f"\nHeartbeat interval: {heartbeat_interval} seconds"
        html_message += "\nMonitoring for new large OP_RETURNs..."
        
        # If status Discord is configured, send there (separate status channel)
        if self.status_discord_enabled:
            status_message = f"🔄 **OP_RETURN Scanner Started**\n\nInterval: {interval_seconds} seconds"
            if heartbeat_interval:
                status_message += f"\nHeartbeat interval: {heartbeat_interval} seconds"
            status_message += "\nMonitoring for new large OP_RETURNs..."
            self.send_status_discord(status_message)
        else:
            # Otherwise, send to regular notification channels
            if self.any_enabled:
                self.send_email(subject, message)
                self.send_telegram(html_message)
                self.send_discord(f"🔄 {subject}\n\n{message}")
                if self.sms_enabled:
                    self.send_sms(message)
    
    def notify_heartbeat(self, blocks_scanned_since_last, total_blocks_scanned, last_block_scanned, failed_rpc_calls=0, first_block_scanned=None, last_block_scanned_range=None):
        """Send heartbeat notification with scan statistics
        
        Args:
            blocks_scanned_since_last: Number of blocks scanned since last heartbeat
            total_blocks_scanned: Total blocks scanned overall
            last_block_scanned: Last block scanned overall
            failed_rpc_calls: Number of failed RPC calls since last heartbeat
            first_block_scanned: First block number scanned since last heartbeat (for range display)
            last_block_scanned_range: Last block number scanned since last heartbeat (for range display)
        """
        message = f"💓 **Heartbeat**\n\n"
        
        if failed_rpc_calls > 0:
            message += f"⚠️ **Warning**: {failed_rpc_calls} failed RPC call(s) since last heartbeat\n"
            if blocks_scanned_since_last == 0:
                message += f"Blocks scanned since last heartbeat: **0** (all attempts failed due to RPC errors)\n"
            else:
                # Include block range if available
                if first_block_scanned is not None and last_block_scanned_range is not None:
                    message += f"Blocks scanned since last heartbeat: **{blocks_scanned_since_last}** ({first_block_scanned}-{last_block_scanned_range}) (some RPC failures occurred)\n"
                else:
                    message += f"Blocks scanned since last heartbeat: **{blocks_scanned_since_last}** (some RPC failures occurred)\n"
        else:
            # Include block range if available
            if first_block_scanned is not None and last_block_scanned_range is not None:
                message += f"Blocks scanned since last heartbeat: **{blocks_scanned_since_last}** ({first_block_scanned}-{last_block_scanned_range})\n"
            else:
                message += f"Blocks scanned since last heartbeat: **{blocks_scanned_since_last}**\n"
        
        message += (
            f"Total blocks scanned: **{total_blocks_scanned:,}**\n"
            f"Last scanned block: **{last_block_scanned}**"
        )
        
        self.send_status_discord(message)
    
    def notify_new_op_returns(self, found_items):
        """Send notification about newly found OP_RETURNs
        
        Args:
            found_items: List of dicts with keys: block, mined_by, txid, size, type, file_path (optional)
        """
        if not self.any_enabled or not found_items:
            return
        
        count = len(found_items)
        subject = f"🔔 {count} New Large OP_RETURN(s) Found!"
        
        # Build message body
        lines = [f"Found {count} large OP_RETURN(s):\n"]
        for item in found_items[:10]:  # Limit to first 10 for readability
            # Get file type (prefer file_type if available, otherwise use type)
            file_type = item.get('file_type') or item.get('type', 'binary')
            
            # Get file size if file exists on disk
            file_size_str = ""
            if item.get('file_path') and Path(item['file_path']).exists():
                try:
                    file_size = Path(item['file_path']).stat().st_size
                    file_size_str = f" (File: {file_size:,} bytes)"
                except:
                    pass
            
            # Format file type display
            type_display = file_type.upper()
            if file_type in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']:
                type_display = f"Image ({file_type.upper()})"
            elif file_type in ['mp3', 'wav', 'ogg', 'flac']:
                type_display = f"Audio ({file_type.upper()})"
            elif file_type in ['mp4', 'avi', 'webm']:
                type_display = f"Video ({file_type.upper()})"
            elif file_type == 'text':
                type_display = "Text"
            
            lines.append(f"Block {item['block']}: {item['size']:,} bytes - Type: {type_display}{file_size_str}")
            lines.append(f"  TX: {item['txid']}")
            lines.append(f"  Miner: {item['mined_by']}")
            
            # Include text body if available (check both file_type and type fields)
            decoded_text = item.get('decoded_text')
            if (file_type == 'text' or item.get('type') == 'text') and decoded_text:
                # Limit text preview to reasonable length (first 500 chars)
                text_preview = decoded_text[:500]
                if len(decoded_text) > 500:
                    text_preview += "..."
                lines.append(f"  Text content:")
                lines.append(f"  {text_preview}")
            
            lines.append("")
        
        if count > 10:
            lines.append(f"... and {count - 10} more")
        
        body = "\n".join(lines)
        
        # Build HTML message for Telegram
        html_lines = [f"<b>🔔 {count} New Large OP_RETURN(s) Found!</b>\n\n"]
        for item in found_items[:10]:
            # Get file type (prefer file_type if available, otherwise use type)
            file_type = item.get('file_type') or item.get('type', 'binary')
            
            # Get file size if file exists on disk
            file_size_str = ""
            if item.get('file_path') and Path(item['file_path']).exists():
                try:
                    file_size = Path(item['file_path']).stat().st_size
                    file_size_str = f" (File: {file_size:,} bytes)"
                except:
                    pass
            
            # Format file type display
            type_display = file_type.upper()
            if file_type in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']:
                type_display = f"Image ({file_type.upper()})"
            elif file_type in ['mp3', 'wav', 'ogg', 'flac']:
                type_display = f"Audio ({file_type.upper()})"
            elif file_type in ['mp4', 'avi', 'webm']:
                type_display = f"Video ({file_type.upper()})"
            elif file_type == 'text':
                type_display = "Text"
            
            html_lines.append(f"<b>Block {item['block']}</b>: {item['size']:,} bytes - Type: <b>{type_display}</b>{file_size_str}")
            html_lines.append(f"TX: <code>{item['txid']}</code>")
            html_lines.append(f"Miner: {item['mined_by']}")
            
            # Include text body if available (check both file_type and type fields)
            decoded_text = item.get('decoded_text')
            if (file_type == 'text' or item.get('type') == 'text') and decoded_text:
                # Limit text preview to reasonable length (first 500 chars)
                text_preview = decoded_text[:500]
                if len(decoded_text) > 500:
                    text_preview += "..."
                html_lines.append(f"<b>Text content:</b>")
                html_lines.append(f"<pre>{text_preview}</pre>")
            
            html_lines.append("")
        
        if count > 10:
            html_lines.append(f"... and {count - 10} more")
        
        html_body = "\n".join(html_lines)
        
        # Send via all enabled channels
        self.send_email(subject, body)
        self.send_telegram(html_body)
        
        # For Discord, send individual messages with file attachments if available
        # Discord supports file attachments, so we can include images/audio/video
        sent_with_attachments = False
        for item in found_items[:5]:  # Limit to first 5 for Discord (to avoid spam)
            file_path = item.get('file_path')
            file_type = item.get('file_type', '')
            
            # Check if it's a media file that Discord can display
            is_media_file = file_path and file_type and (
                file_type in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'] or  # Images
                file_type in ['mp3', 'wav', 'ogg', 'flac'] or  # Audio
                file_type in ['mp4', 'avi', 'webm']  # Video
            )
            
            if is_media_file and Path(file_path).exists():
                # Get file size
                file_size_str = ""
                try:
                    file_size = Path(file_path).stat().st_size
                    file_size_str = f" (File: {file_size:,} bytes)"
                except:
                    pass
                
                # Format file type display
                type_display = file_type.upper()
                if file_type in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']:
                    type_display = f"Image ({file_type.upper()})"
                elif file_type in ['mp3', 'wav', 'ogg', 'flac']:
                    type_display = f"Audio ({file_type.upper()})"
                elif file_type in ['mp4', 'avi', 'webm']:
                    type_display = f"Video ({file_type.upper()})"
                
                # Send individual message with file attachment
                item_msg = (
                    f"🔔 **Block {item['block']}**: {item['size']:,} bytes - Type: **{type_display}**{file_size_str}\n"
                    f"TX: `{item['txid']}`\n"
                    f"Miner: {item['mined_by']}"
                )
                
                # Include text body if it's text type (check both file_type and type fields)
                decoded_text = item.get('decoded_text')
                if (file_type == 'text' or item.get('type') == 'text') and decoded_text:
                    # Limit text preview to reasonable length (first 500 chars)
                    text_preview = decoded_text[:500]
                    if len(decoded_text) > 500:
                        text_preview += "..."
                    item_msg += f"\n\n**Text content:**\n```\n{text_preview}\n```"
                
                self.send_discord(item_msg, file_path=Path(file_path), file_name=f"block_{item['block']}_{item['txid'][:16]}.{file_type}")
                sent_with_attachments = True
        
        # Send summary message if we didn't send individual attachments, or if there are more items
        if not sent_with_attachments or len(found_items) > 5:
            # Remove bell icon from subject since we're adding it here, or just use body without subject prefix
            self.send_discord(f"{subject}\n\n{body}")
        
        if self.sms_enabled:
            self.send_sms(body)
    
    def notify_bip_signal(self, bip_signal_data):
        """Send notification about BIP signaling detected in a block
        
        Args:
            bip_signal_data: dict with BIP signaling info (from BIPDetector.detect_bip110)
        """
        if not self.any_enabled or not bip_signal_data:
            return
        
        bip_name = bip_signal_data.get('bip', 'BIP')
        block_number = bip_signal_data.get('block_number')
        mined_by = bip_signal_data.get('mined_by', 'Unknown')
        block_time = bip_signal_data.get('block_time', '')
        detection_methods = bip_signal_data.get('detection_methods', [])
        coinbase_text = bip_signal_data.get('coinbase_text')
        
        subject = f"🔔 {bip_name} Signal Detected!"
        
        # Build message body
        lines = [
            f"{bip_name} signal detected in block {block_number}",
            f"",
            f"Block: {block_number}",
            f"Mined by: {mined_by}",
            f"Time: {block_time}",
            f"Detection methods: {', '.join(detection_methods)}",
        ]
        
        if coinbase_text:
            # Show coinbase text preview (first 200 chars)
            coinbase_preview = coinbase_text[:200]
            if len(coinbase_text) > 200:
                coinbase_preview += "..."
            lines.append(f"")
            lines.append(f"Coinbase text preview:")
            lines.append(f"{coinbase_preview}")
        
        body = "\n".join(lines)
        
        # Build HTML message for Telegram
        html_lines = [
            f"<b>🔔 {bip_name} Signal Detected!</b>",
            f"",
            f"<b>Block:</b> {block_number}",
            f"<b>Mined by:</b> {mined_by}",
            f"<b>Time:</b> {block_time}",
            f"<b>Detection methods:</b> {', '.join(detection_methods)}",
        ]
        
        if coinbase_text:
            coinbase_preview = coinbase_text[:200]
            if len(coinbase_text) > 200:
                coinbase_preview += "..."
            html_lines.append(f"")
            html_lines.append(f"<b>Coinbase text preview:</b>")
            html_lines.append(f"<pre>{coinbase_preview}</pre>")
        
        html_body = "\n".join(html_lines)
        
        # Build Discord message (Markdown format)
        discord_lines = [
            f"🔔 **{bip_name} Signal Detected!**",
            f"",
            f"**Block:** {block_number}",
            f"**Mined by:** {mined_by}",
            f"**Time:** {block_time}",
            f"**Detection methods:** {', '.join(detection_methods)}",
        ]
        
        if coinbase_text:
            coinbase_preview = coinbase_text[:200]
            if len(coinbase_text) > 200:
                coinbase_preview += "..."
            discord_lines.append(f"")
            discord_lines.append(f"**Coinbase text preview:**")
            discord_lines.append(f"```\n{coinbase_preview}\n```")
        
        discord_msg = "\n".join(discord_lines)
        
        # Send via all enabled channels
        self.send_email(subject, body)
        self.send_telegram(html_body)
        self.send_discord(discord_msg)
        
        if self.sms_enabled:
            self.send_sms(body)

class BIPDetector:
    """Detects BIP signaling in Bitcoin blocks
    
    Supports multiple BIPs with extensible detection methods:
    - BIP-110: Block size increase proposals (coinbase text patterns, version bits)
    - Can be extended for other BIPs
    """
    
    def __init__(self, bip_blocks_dir):
        """Initialize BIP detector
        
        Args:
            bip_blocks_dir: Path to directory where BIP block data is stored (e.g., bitcoin_large_op_returns/bip_blocks)
        """
        self.bip_blocks_dir = Path(bip_blocks_dir)
        self.bip_blocks_dir.mkdir(exist_ok=True, parents=True)
        
        # BIP-110 detection patterns (coinbase text fallback - primary detection is version bit 4)
        # BIP-110 is about temporarily limiting arbitrary data in Bitcoin
        # Primary detection method: version bit 4 (0x10) in block version field
        # These patterns are fallback/confirmation patterns in coinbase text
        self.bip110_patterns = [
            'bip110',
            'bip-110',
            'bip 110',
            'limit data',
            'limit op_return',
            'clean up',
            'data limit',
        ]
    
    def detect_bip110(self, coinbase_tx, block_header, block_number, block_time, mined_by):
        """Detect BIP-110 signaling in a block
        
        Args:
            coinbase_tx: Coinbase transaction dict
            block_header: Block header dict (contains version, etc.)
            block_number: Block number
            block_time: Block timestamp (datetime)
            mined_by: Miner/pool name
            
        Returns:
            dict with BIP-110 signaling info if detected, None otherwise
        """
        detected = False
        detection_methods = []
        coinbase_text = None
        
        # Method 1: Check coinbase text for BIP-110 patterns
        if coinbase_tx and coinbase_tx.get('vin'):
            coinbase_input = coinbase_tx['vin'][0]
            if 'coinbase' in coinbase_input:
                coinbase_hex = coinbase_input['coinbase']
                try:
                    coinbase_bytes = bytes.fromhex(coinbase_hex)
                    coinbase_text = coinbase_bytes.decode('ascii', errors='ignore').lower()
                    
                    # Debug: Log coinbase text for blocks we're specifically checking
                    # This helps identify new patterns
                    if block_number in [938903]:  # Known BIP-110 block
                        logger.debug(f"   Coinbase text for block {block_number}: {repr(coinbase_text[:500])}")
                    
                    # Check for BIP-110 patterns
                    for pattern in self.bip110_patterns:
                        pattern_lower = pattern.lower()
                        if pattern_lower in coinbase_text:
                            detected = True
                            detection_methods.append(f"coinbase_text:{pattern}")
                            break
                except Exception as e:
                    logger.debug(f"   Error decoding coinbase for block {block_number}: {e}")
                    pass
        
        # Method 2: Check block version bits (BIP-9 style signaling)
        # BIP-110 uses version bit 4 (0x10) for signaling
        # Bit 29 (0x20000000) indicates BIP-9 signaling is active
        # Bit 4 (0x10) specifically signals BIP-110 support
        if block_header and 'version' in block_header:
            version = block_header['version']
            # Check if version has BIP-9 signaling bit set (bit 29)
            bip9_active = version & 0x20000000  # Bit 29 set indicates BIP-9 signaling
            # Check if bit 4 is set (BIP-110 specific signal)
            bip110_bit = version & 0x10  # Bit 4 signals BIP-110
            
            if bip9_active and bip110_bit:
                detected = True
                detection_methods.append(f"version_bit_4:0x{version:08x}")
            elif bip9_active:
                # BIP-9 active but not BIP-110 - log for analysis
                detection_methods.append(f"version_bits_other:0x{version:08x}")
        
        if detected:
            return {
                'bip': 'BIP-110',
                'block_number': block_number,
                'block_time': block_time.isoformat(),
                'mined_by': mined_by or 'Unknown',
                'detection_methods': detection_methods,
                'coinbase_text': coinbase_text if coinbase_text else None,
                'block_version': block_header.get('version') if block_header else None,
            }
        
        return None
    
    def save_bip_signal(self, bip_name, signal_data):
        """Save BIP signaling data to JSONL file
        
        Args:
            bip_name: BIP identifier (e.g., 'bip-110')
            signal_data: dict with signaling information
            
        Returns:
            True if saved (or already exists), False on error
        """
        # Normalize BIP name (e.g., 'BIP-110' -> 'bip-110')
        bip_name_normalized = bip_name.lower().replace('_', '-')
        jsonl_file = self.bip_blocks_dir / f"{bip_name_normalized}.jsonl"
        
        block_number = signal_data.get('block_number')
        if block_number is None:
            logger.warning(f"BIP signal data missing block_number, skipping save")
            return False
        
        # Check if block already exists in file
        existing_blocks = set()
        if jsonl_file.exists():
            try:
                with open(jsonl_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            existing_block = entry.get('block_number')
                            if existing_block is not None:
                                existing_blocks.add(existing_block)
                        except json.JSONDecodeError:
                            # Skip malformed lines
                            continue
            except Exception as e:
                logger.debug(f"Error reading existing BIP signals from {jsonl_file}: {e}")
        
        # Skip if block already exists
        if block_number in existing_blocks:
            logger.debug(f"Block {block_number} already in {jsonl_file.name}, skipping duplicate")
            return True
        
        # Append to JSONL file (one JSON object per line)
        try:
            with open(jsonl_file, 'a', encoding='utf-8', newline='\n') as f:
                json.dump(signal_data, f, ensure_ascii=False)
                f.write('\n')
            return True
        except Exception as e:
            logger.warning(f"Error saving BIP signal to {jsonl_file}: {e}")
            return False

class OPReturnScanner:
    def __init__(self, output_dir="bitcoin_large_op_returns/op_return_data", use_database=True, auto_sync_git=None):
        # Load environment variables
        load_dotenv()
        
        self.btc_service = BTCService(test_connection=True)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.use_database = use_database
        
        # Initialize BIP detector (bip_blocks directory next to op_return_data)
        bip_blocks_dir = self.output_dir.parent / 'bip_blocks'
        self.bip_detector = BIPDetector(bip_blocks_dir)
        
        # Auto-sync git: check environment variable if not explicitly set
        if auto_sync_git is None:
            auto_sync_git = os.getenv('OP_RETURN_AUTO_SYNC_GIT', 'false').lower() in ('true', '1', 'yes')
        self.auto_sync_git = auto_sync_git
        
        # Get GitHub token for authentication
        self.github_token = os.getenv('GITHUB_TOKEN')
        
        # Determine submodule root (parent of op_return_data directory)
        # If output_dir is bitcoin_large_op_returns/op_return_data, submodule_root is bitcoin_large_op_returns
        if 'op_return_data' in str(self.output_dir):
            self.submodule_root = self.output_dir.parent
        else:
            # If output_dir is just bitcoin_large_op_returns, use it directly
            self.submodule_root = self.output_dir if 'bitcoin_large_op_returns' in str(self.output_dir) else None
        
        if self.use_database:
            # Initialize database tables
            init_db()
            self.db = SessionLocal()
        
        # File signatures for detection (magic numbers)
        # Order matters - more specific signatures should come first
        self.file_signatures = {
            # Images
            b'\xFF\xD8\xFF': ('jpg', 'image/jpeg'),
            b'\x89PNG\r\n\x1a\n': ('png', 'image/png'),
            b'GIF87a': ('gif', 'image/gif'),
            b'GIF89a': ('gif', 'image/gif'),
            b'RIFF': ('webp', 'image/webp'),  # WebP - check for WEBP after RIFF header
            b'BM': ('bmp', 'image/bmp'),
            b'\x49\x49\x2A\x00': ('tiff', 'image/tiff'),  # Little-endian TIFF
            b'\x4D\x4D\x00\x2A': ('tiff', 'image/tiff'),  # Big-endian TIFF
            b'\x00\x00\x01\x00': ('ico', 'image/x-icon'),
            
            # Documents
            b'%PDF': ('pdf', 'application/pdf'),
            b'\xD0\xCF\x11\xE0': ('doc', 'application/msword'),  # Old DOC format
            b'PK\x03\x04': ('zip', 'application/zip'),  # Could also be DOCX/XLSX/JAR/APK
            
            # Archives
            b'\x37\x7A\xBC\xAF\x27\x1C': ('7z', 'application/x-7z-compressed'),
            b'Rar!\x1A\x07\x00': ('rar', 'application/x-rar-compressed'),  # RAR 1.5+
            b'Rar!\x1A\x07\x01\x00': ('rar', 'application/x-rar-compressed'),  # RAR 5.0+
            b'\x1F\x8B': ('gz', 'application/gzip'),
            b'BZh': ('bz2', 'application/x-bzip2'),
            b'\x75\x73\x74\x61\x72': ('tar', 'application/x-tar'),  # At offset 257, but checking here
            
            # Audio
            b'ID3': ('mp3', 'audio/mpeg'),
            b'\xFF\xFB': ('mp3', 'audio/mpeg'),  # MP3 without ID3
            b'\xFF\xF3': ('mp3', 'audio/mpeg'),  # MP3 without ID3
            b'fLaC': ('flac', 'audio/flac'),
            b'OggS': ('ogg', 'audio/ogg'),
            
            # Video
            b'\x00\x00\x00\x18ftypmp42': ('mp4', 'video/mp4'),
            b'\x00\x00\x00\x20ftypmp42': ('mp4', 'video/mp4'),
            b'\x00\x00\x00\x18ftypisom': ('mp4', 'video/mp4'),
            b'\x00\x00\x00\x20ftypisom': ('mp4', 'video/mp4'),
            b'RIFF': ('avi', 'video/x-msvideo'),  # Must check for AVI list later
            
            # Executables
            b'MZ': ('exe', 'application/x-msdownload'),  # Windows PE
            b'\x7FELF': ('elf', 'application/x-executable'),  # Linux ELF
            
            # Other
            b'{': ('json', 'application/json'),  # Simple JSON detection
            b'<?xml': ('xml', 'application/xml'),
        }
        
        if not self.btc_service.is_available:
            raise Exception("Bitcoin Core RPC not available")
        
        # Initialize notification system
        self.notifier = NotificationManager()
    
    def __del__(self):
        """Close database connection when done"""
        if hasattr(self, 'db'):
            self.db.close()
    
    def get_last_scanned_block(self):
        """Get the highest block number that was scanned"""
        if not self.use_database:
            return None
        
        result = self.db.query(func.max(OPReturnScan.block_number)).scalar()
        return result
    
    def get_first_scanned_block(self):
        """Get the lowest block number that was scanned"""
        if not self.use_database:
            return None
        
        result = self.db.query(func.min(OPReturnScan.block_number)).scalar()
        return result
    
    def get_scan_statistics(self):
        """Get overall statistics about scanned blocks"""
        if not self.use_database:
            return None
        
        stats = self.db.query(
            func.count(OPReturnScan.id).label('total_blocks_scanned'),
            func.sum(OPReturnScan.large_op_returns_found).label('total_large_op_returns'),
            func.min(OPReturnScan.block_number).label('first_block'),
            func.max(OPReturnScan.block_number).label('last_block'),
            func.avg(OPReturnScan.large_op_returns_found).label('avg_per_block')
        ).first()
        
        return {
            'total_blocks_scanned': stats.total_blocks_scanned or 0,
            'total_large_op_returns': stats.total_large_op_returns or 0,
            'first_block': stats.first_block,
            'last_block': stats.last_block,
            'avg_per_block': float(stats.avg_per_block) if stats.avg_per_block else 0
        }
    
    def block_already_scanned(self, block_number):
        """Check if a block has already been scanned"""
        if not self.use_database:
            return False
        
        return self.db.query(OPReturnScan).filter_by(block_number=block_number).first() is not None
    
    def extract_mining_pool(self, coinbase_tx):
        """Extract mining pool information from coinbase transaction"""
        try:
            # Get the coinbase input (first input of first tx)
            if not coinbase_tx.get('vin') or len(coinbase_tx['vin']) == 0:
                return None, None
            
            coinbase_input = coinbase_tx['vin'][0]
            
            # Check if it's a coinbase transaction
            if 'coinbase' not in coinbase_input:
                return None, None
            
            # Decode the coinbase hex
            coinbase_hex = coinbase_input['coinbase']
            try:
                coinbase_bytes = bytes.fromhex(coinbase_hex)
                # Try to decode as ASCII, ignore errors
                coinbase_text = coinbase_bytes.decode('ascii', errors='ignore')
            except:
                coinbase_text = coinbase_hex
            
            # Common mining pool signatures
            pool_signatures = {
                'ViaBTC': 'ViaBTC',
                'F2Pool': 'F2Pool',
                'AntPool': 'AntPool',
                'Foundry': 'Foundry USA',
                'foundry': 'Foundry USA',
                'Binance': 'Binance Pool',
                'BTC.com': 'BTC.com',
                'Poolin': 'Poolin',
                'SlushPool': 'Slush Pool',
                'MARA': 'Marathon Digital',
                'marathon': 'Marathon Digital',
                'SpiderPool': 'SpiderPool',
                'SBI': 'SBI Crypto',
                'EMCD': 'EMCD',
                'Luxor': 'Luxor',
                'BraiinsPool': 'Braiins Pool',
                'stratum': 'Braiins Pool',
                'ckpool': 'CKPool',
                '/luckyPool/': 'luckyPool',
                'luckyPool': 'luckyPool',
                'ultimus': 'Ultimus Pool',
                'SecPool': 'SecPool',
            }
            
            # Search for pool signature in coinbase text
            coinbase_lower = coinbase_text.lower()
            for signature, pool_name in pool_signatures.items():
                if signature.lower() in coinbase_lower:
                    return pool_name, coinbase_text
            
            # If no known pool found, return unknown with coinbase text
            return 'Unknown', coinbase_text
            
        except Exception as e:
            logger.debug(f"Error extracting mining pool: {e}")
            return None, None
    
    def detect_file_type(self, data):
        """Detect file type from binary data or data URI
        
        Returns: (file_ext, mime_type, decoded_binary, storage_format)
        """
        import re
        import base64
        
        storage_format = 'raw'
        
        # First check if this is a data URI (e.g., data:image/png;base64,...)
        try:
            decoded = data.decode('utf-8', errors='ignore')
            data_uri_pattern = r'^data:(image|video|audio|application)/([a-zA-Z0-9\-\+\.]+);base64,(.+)$'
            match = re.match(data_uri_pattern, decoded.strip())
            
            # Also handle malformed data URIs like data:/jpeg;base64,...
            if not match:
                malformed_pattern = r'^data:/([a-zA-Z0-9\-\+\.]+);base64,(.+)$'
                match = re.match(malformed_pattern, decoded.strip())
                if match:
                    # Infer MIME type from extension
                    ext_only = match.group(1).lower()
                    base64_data = match.group(2)
                    
                    # Map common extensions to MIME categories and subtypes
                    ext_to_mime = {
                        'jpeg': ('image', 'jpeg'),
                        'jpg': ('image', 'jpeg'),
                        'png': ('image', 'png'),
                        'gif': ('image', 'gif'),
                        'webp': ('image', 'webp'),
                        'bmp': ('image', 'bmp'),
                        'svg': ('image', 'svg+xml'),
                        'mp4': ('video', 'mp4'),
                        'webm': ('video', 'webm'),
                        'avi': ('video', 'x-msvideo'),
                        'mp3': ('audio', 'mpeg'),
                        'wav': ('audio', 'wav'),
                        'ogg': ('audio', 'ogg'),
                        'pdf': ('application', 'pdf'),
                        'json': ('application', 'json'),
                    }
                    
                    if ext_only in ext_to_mime:
                        mime_category, mime_subtype = ext_to_mime[ext_only]
                    else:
                        # Default to image if unknown
                        mime_category = 'image'
                        mime_subtype = ext_only
                    
                    storage_format = 'data_uri'
                    full_mime = f'{mime_category}/{mime_subtype}'
                    
                    # Map common MIME types to extensions
                    mime_to_ext = {
                        'image/png': 'png',
                        'image/jpeg': 'jpg',
                        'image/jpg': 'jpg',
                        'image/gif': 'gif',
                        'image/webp': 'webp',
                        'image/bmp': 'bmp',
                        'image/svg+xml': 'svg',
                        'video/mp4': 'mp4',
                        'video/webm': 'webm',
                        'video/x-msvideo': 'avi',
                        'audio/mpeg': 'mp3',
                        'audio/mp3': 'mp3',
                        'audio/ogg': 'ogg',
                        'audio/wav': 'wav',
                        'application/pdf': 'pdf',
                        'application/json': 'json',
                    }
                    
                    ext = mime_to_ext.get(full_mime, ext_only)
                    
                    # Return the extension, mime type, decoded binary data, and storage format
                    try:
                        decoded_binary = base64.b64decode(base64_data)
                        return ext, full_mime, decoded_binary, storage_format
                    except:
                        # If base64 decode fails, return the info but no decoded data
                        return ext, full_mime, None, storage_format
            
            if match:
                storage_format = 'data_uri'
                mime_category = match.group(1)
                mime_subtype = match.group(2)
                base64_data = match.group(3)
                
                # Map common MIME types to extensions
                mime_to_ext = {
                    'image/png': 'png',
                    'image/jpeg': 'jpg',
                    'image/jpg': 'jpg',
                    'image/gif': 'gif',
                    'image/webp': 'webp',
                    'image/bmp': 'bmp',
                    'image/svg+xml': 'svg',
                    'video/mp4': 'mp4',
                    'video/webm': 'webm',
                    'audio/mpeg': 'mp3',
                    'audio/mp3': 'mp3',
                    'audio/ogg': 'ogg',
                    'audio/wav': 'wav',
                    'application/pdf': 'pdf',
                    'application/json': 'json',
                }
                
                full_mime = f'{mime_category}/{mime_subtype}'
                ext = mime_to_ext.get(full_mime, mime_subtype)
                
                # Return the extension, mime type, decoded binary data, and storage format
                try:
                    decoded_binary = base64.b64decode(base64_data)
                    return ext, full_mime, decoded_binary, storage_format
                except:
                    # If base64 decode fails, return the info but no decoded data
                    return ext, full_mime, None, storage_format
        except:
            pass
        
        # Check if raw data is base64-encoded binary (not a data URI)
        # This handles cases where OP_RETURN contains base64 string directly
        try:
            decoded_str = data.decode('utf-8', errors='ignore').strip()
            # Check if it looks like base64 (only base64 chars, reasonable length)
            # Base64 alphabet: A-Z, a-z, 0-9, +, /, = (padding)
            base64_pattern = re.compile(r'^[A-Za-z0-9+/=\s]+$')
            if base64_pattern.match(decoded_str) and len(decoded_str) > 20:
                # Remove whitespace (base64 can have newlines)
                base64_clean = re.sub(r'\s+', '', decoded_str)
                # Try to decode it
                try:
                    decoded_binary = base64.b64decode(base64_clean, validate=True)
                    storage_format = 'base64'
                    # If decode succeeds, check if decoded binary matches a file signature
                    for signature, (ext, mime) in self.file_signatures.items():
                        if decoded_binary.startswith(signature):
                            return ext, mime, decoded_binary, storage_format
                    # If no signature matches but decode succeeded, it's valid base64
                    # Return as binary with generic type
                    return None, None, decoded_binary, storage_format
                except:
                    # Not valid base64, continue to other checks
                    pass
        except:
            pass
        
        # Not a data URI or base64, check file signatures
        # Special handling for RIFF-based formats (WebP, AVI, WAV)
        if data.startswith(b'RIFF') and len(data) >= 12:
            # Check for WebP (RIFF...WEBP)
            if data[8:12] == b'WEBP':
                return 'webp', 'image/webp', None, storage_format
            # Check for AVI (RIFF...AVI )
            elif len(data) >= 16 and data[8:12] == b'AVI ':
                return 'avi', 'video/x-msvideo', None, storage_format
            # Check for WAV (RIFF...WAVE)
            elif len(data) >= 12 and data[8:12] == b'WAVE':
                return 'wav', 'audio/wav', None, storage_format
        
        # Check other file signatures
        for signature, (ext, mime) in self.file_signatures.items():
            # Skip RIFF since we handle it above
            if signature == b'RIFF':
                continue
            if data.startswith(signature):
                return ext, mime, None, storage_format
        return None, None, None, storage_format
    
    def is_text(self, data):
        """Check if data is likely text"""
        try:
            # Try to decode as UTF-8
            decoded = data.decode('utf-8')
            # Check if it's printable
            printable_ratio = sum(c.isprintable() or c.isspace() for c in decoded) / len(decoded)
            return printable_ratio > 0.8, decoded
        except:
            return False, None
    
    def calculate_transaction_fee(self, tx):
        """
        Calculate transaction fee and size from transaction data.
        
        Returns: (fee, vsize, input_count, output_count)
        """
        try:
            # Get transaction size (vsize for SegWit, size for legacy)
            tx_size = tx.get('vsize', tx.get('size', 0))
            input_count = len(tx.get('vin', []))
            output_count = len(tx.get('vout', []))
            
            # Calculate total output value
            total_out = 0
            for vout in tx.get('vout', []):
                total_out += int(vout.get('value', 0) * 100000000)  # Convert BTC to sats
            
            # For block verbosity 2, we should have 'fee' field directly
            # (available in Bitcoin Core since the inputs are resolved)
            tx_fee = 0
            if 'fee' in tx:
                # Fee is negative in BTC, convert to positive satoshis
                tx_fee = int(abs(tx.get('fee', 0)) * 100000000)
            
            return tx_fee, tx_size, input_count, output_count
            
        except Exception as e:
            logger.warning(f"Error calculating transaction fee: {e}")
            return 0, 0, 0, 0
    
    def extract_op_return_from_script(self, script_hex):
        """Extract OP_RETURN data from script hex"""
        try:
            script_bytes = bytes.fromhex(script_hex)
            
            # OP_RETURN is 0x6a
            if script_bytes[0] != 0x6a:
                return None
            
            # Next byte(s) indicate the length
            if len(script_bytes) < 2:
                return None
            
            # Handle different push opcodes
            pos = 1
            if script_bytes[pos] <= 0x4b:  # Direct length (1-75 bytes)
                length = script_bytes[pos]
                pos += 1
            elif script_bytes[pos] == 0x4c:  # OP_PUSHDATA1
                length = script_bytes[pos + 1]
                pos += 2
            elif script_bytes[pos] == 0x4d:  # OP_PUSHDATA2
                length = int.from_bytes(script_bytes[pos+1:pos+3], 'little')
                pos += 3
            elif script_bytes[pos] == 0x4e:  # OP_PUSHDATA4
                length = int.from_bytes(script_bytes[pos+1:pos+5], 'little')
                pos += 5
            else:
                return None
            
            # Extract the data
            data = script_bytes[pos:pos+length]
            return data
            
        except Exception as e:
            logger.debug(f"Error extracting OP_RETURN: {e}")
            return None
    
    def save_op_return_data(self, scan_record, block_number, block_time, txid, vout_index, data, mined_by=None, tx_fee=0, tx_size=0, input_count=0, output_count=0):
        """Save OP_RETURN data to files and database"""
        # Detect file type (may return decoded data for data URIs or base64)
        file_ext, mime_type, decoded_binary, storage_format = self.detect_file_type(data)
        
        # If we got decoded binary data from a data URI or base64, use that for saving
        save_data = decoded_binary if decoded_binary is not None else data
        
        # Check if original data is text (but don't treat decoded base64 as text)
        is_text_data, decoded_text = self.is_text(data)
        # If we decoded base64, don't save it as text
        if decoded_binary is not None:
            is_text_data = False
        else:
            # If it's text and we didn't detect a special format, set storage_format to 'text'
            if is_text_data and storage_format == 'raw':
                storage_format = 'text'
        
        # Convert to hex for database storage
        data_hex = data.hex()
        
        # Calculate fee rate and cost per byte
        fee_rate = (tx_fee / tx_size) if tx_size > 0 else 0
        cost_per_byte = (tx_fee / len(data)) if len(data) > 0 else 0
        
        # Check if data is too large for TEXT column (65535 bytes = 32767 bytes raw)
        # Store NULL in database for very large files, rely on filesystem
        store_raw_data = len(data) <= 32767
        if not store_raw_data:
            logger.info(f"  💾 Large file ({len(data):,} bytes) - storing metadata only, data on disk")
        
        # Save to database
        if self.use_database and scan_record:
            try:
                large_op_return = LargeOPReturn(
                    scan_id=scan_record.id,
                    block_number=block_number,
                    txid=txid,
                    vout_index=vout_index,
                    data_size=len(data),
                    raw_data=data_hex if store_raw_data else None,  # NULL for large files
                    decoded_text=decoded_text if store_raw_data and decoded_text else None,
                    file_type=file_ext or ("text" if is_text_data else "binary"),
                    mime_type=mime_type or ("text/plain" if is_text_data else "application/octet-stream"),
                    is_text=is_text_data,
                    storage_format=storage_format,
                    tx_fee=tx_fee if tx_fee > 0 else None,
                    tx_size=tx_size if tx_size > 0 else None,
                    fee_rate=fee_rate if fee_rate > 0 else None,
                    cost_per_byte=cost_per_byte if cost_per_byte > 0 else None,
                    tx_input_count=input_count if input_count > 0 else None,
                    tx_output_count=output_count if output_count > 0 else None
                )
                self.db.add(large_op_return)
                self.db.commit()
            except Exception as e:
                logger.error(f"  ❌ Error saving to database: {e}")
                self.db.rollback()
        
        # Save to files
        # Create directory for this block
        block_dir = self.output_dir / f"block_{block_number}"
        block_dir.mkdir(exist_ok=True)
        
        # Base filename
        base_name = f"tx_{txid}_{vout_index}"
        
        # Create metadata
        metadata = {
            "block_number": block_number,
            "block_time": block_time.isoformat(),
            "mined_by": mined_by or "Unknown",
            "transaction_id": txid,
            "vout_index": vout_index,
            "data_size": len(data),
            "file_type": file_ext or ("text" if is_text_data else "binary"),
            "mime_type": mime_type or ("text/plain" if is_text_data else "application/octet-stream"),
            "storage_format": storage_format,
            "raw_data_hex": data.hex(),
            "transaction_fee_sats": tx_fee if tx_fee > 0 else None,
            "transaction_size_vbytes": tx_size if tx_size > 0 else None,
            "fee_rate_sats_per_vbyte": round(fee_rate, 2) if fee_rate > 0 else None,
            "cost_per_byte_of_data": round(cost_per_byte, 2) if cost_per_byte > 0 else None,
            "tx_inputs": input_count if input_count > 0 else None,
            "tx_outputs": output_count if output_count > 0 else None
        }
        
        # Save metadata JSON (always - contains hex data for analysis)
        with open(block_dir / f"{base_name}_metadata.json", 'w', newline='\n') as f:
            json.dump(metadata, f, indent=2)
        
        # Check if this is a dangerous executable type
        dangerous_types = {'exe', 'elf'}
        is_dangerous = file_ext in dangerous_types
        
        # Save raw data (skip for executables - security risk)
        if not is_dangerous:
            with open(block_dir / f"{base_name}_raw.bin", 'wb') as f:
                f.write(save_data)
        
        # Save decoded text if applicable (but not if we decoded base64)
        if is_text_data and decoded_binary is None:
            with open(block_dir / f"{base_name}_decoded.txt", 'w', encoding='utf-8') as f:
                f.write(decoded_text)
            logger.info(f"  💬 Text data: {decoded_text[:100]}...")
        
        # Save as file if file type detected (skip executables)
        saved_file_path = None
        if file_ext:
            if is_dangerous:
                logger.warning(f"  ⚠️  Skipping all file creation for: {file_ext} (potential security risk)")
                logger.info(f"     Only metadata JSON saved (hex data preserved for analysis)")
            else:
                file_path = block_dir / f"{base_name}.{file_ext}"
                with open(file_path, 'wb') as f:
                    f.write(save_data)
                saved_file_path = file_path
                logger.info(f"  📄 File saved: {file_path.name} ({mime_type})")
                # Note if we decoded from base64 or data URI
                if decoded_binary is not None:
                    if storage_format == 'data_uri':
                        logger.info(f"  🔓 Decoded from data URI")
                    elif storage_format == 'base64':
                        logger.info(f"  🔓 Decoded from base64")
        
        # Add file path to metadata for notifications
        metadata['saved_file_path'] = str(saved_file_path) if saved_file_path else None
        
        # Add decoded text to metadata for notifications (when it's text type)
        # Determine final file_type to check if it's text
        final_file_type = file_ext or ("text" if is_text_data else "binary")
        if final_file_type == "text" and decoded_text:
            metadata['decoded_text'] = decoded_text
        
        return metadata
    
    def scan_block(self, block_number, skip_if_scanned=True, send_immediate_notifications=False, bip_only=False):
        """Scan a single block for OP_RETURN transactions
        
        Args:
            block_number: Block number to scan
            skip_if_scanned: Skip if already scanned (only applies when not bip_only)
            send_immediate_notifications: Send notifications immediately (only applies when not bip_only)
            bip_only: If True, only detect BIP signaling, skip OP_RETURN scanning
        """
        # Check if already scanned (skip this check in bip_only mode)
        if not bip_only and skip_if_scanned and self.block_already_scanned(block_number):
            logger.info(f"⏭️  Block {block_number} already scanned, skipping")
            return 0
        
        try:
            block_hash = self.btc_service._call_rpc("getblockhash", [block_number])
            block = self.btc_service._call_rpc("getblock", [block_hash, 2])  # Verbosity 2 for full tx data
            
            block_time = datetime.fromtimestamp(block['time'])
            total_tx_count = len(block['tx'])
            found_count = 0
            
            # Extract mining pool from coinbase transaction (first tx)
            mined_by = None
            coinbase_text = None
            coinbase_tx = None
            if len(block['tx']) > 0:
                coinbase_tx = block['tx'][0]
                mined_by, coinbase_text = self.extract_mining_pool(coinbase_tx)
                if mined_by:
                    logger.info(f"⛏️  Block mined by: {mined_by}")
            
            # Check for BIP signaling (e.g., BIP-110)
            # Get block header info (version, etc.)
            block_header = {
                'version': block.get('version'),
                'time': block.get('time'),
                'bits': block.get('bits'),
                'nonce': block.get('nonce'),
            }
            
            # Detect BIP-110 signaling
            bip110_signal = self.bip_detector.detect_bip110(
                coinbase_tx, 
                block_header, 
                block_number, 
                block_time, 
                mined_by
            )
            
            if bip110_signal:
                logger.info(f"🔔 BIP-110 signal detected in block {block_number} (mined by {mined_by})")
                logger.info(f"   Detection methods: {', '.join(bip110_signal['detection_methods'])}")
                if bip110_signal.get('coinbase_text'):
                    logger.debug(f"   Coinbase text: {bip110_signal['coinbase_text'][:200]}")
                self.bip_detector.save_bip_signal('bip-110', bip110_signal)
                # Send notification about BIP signal
                if self.notifier.any_enabled:
                    self.notifier.notify_bip_signal(bip110_signal)
            else:
                # Debug: Log when we don't detect BIP-110 for known blocks
                if block_number in [938903]:
                    logger.warning(f"   ⚠️  Block {block_number} did not match BIP-110 patterns")
                    if coinbase_tx and coinbase_tx.get('vin'):
                        coinbase_input = coinbase_tx['vin'][0]
                        if 'coinbase' in coinbase_input:
                            coinbase_hex = coinbase_input['coinbase']
                            try:
                                coinbase_bytes = bytes.fromhex(coinbase_hex)
                                coinbase_text = coinbase_bytes.decode('ascii', errors='ignore')
                                logger.warning(f"   Coinbase text: {repr(coinbase_text[:500])}")
                            except:
                                logger.warning(f"   Coinbase hex: {coinbase_hex[:200]}")
            
            # If bip_only mode, skip OP_RETURN scanning
            if bip_only:
                return 0
            
            # Create scan record
            scan_record = None
            if self.use_database:
                scan_record = OPReturnScan(
                    block_number=block_number,
                    block_hash=block_hash,
                    block_time=block_time,
                    total_transactions=total_tx_count,
                    large_op_returns_found=0,  # Will update this later
                    mined_by=mined_by,
                    coinbase_text=coinbase_text
                )
                self.db.add(scan_record)
                self.db.commit()
            
            # Check each transaction
            for tx in block['tx']:
                txid = tx['txid']
                
                # Calculate transaction fee information once per transaction
                tx_fee, tx_size, input_count, output_count = self.calculate_transaction_fee(tx)
                
                # Check each output
                for vout_idx, vout in enumerate(tx['vout']):
                    script_hex = vout['scriptPubKey'].get('hex', '')
                    
                    # Check if it's OP_RETURN
                    if script_hex.startswith('6a'):  # OP_RETURN opcode
                        data = self.extract_op_return_from_script(script_hex)
                        
                        if data and len(data) > 83:
                            found_count += 1
                            logger.info(f"📦 Found OP_RETURN in block {block_number}, tx {txid}, vout {vout_idx}")
                            logger.info(f"  Size: {len(data)} bytes")
                            
                            # Log fee information if available
                            if tx_fee > 0:
                                fee_rate = tx_fee / tx_size if tx_size > 0 else 0
                                cost_per_byte = tx_fee / len(data) if len(data) > 0 else 0
                                logger.info(f"  Fee: {tx_fee:,} sats ({fee_rate:.2f} sats/vbyte)")
                                logger.info(f"  Cost: {cost_per_byte:.2f} sats/byte of OP_RETURN data")
                            
                            metadata = self.save_op_return_data(
                                scan_record,
                                block_number,
                                block_time,
                                txid,
                                vout_idx,
                                data,
                                mined_by,
                                tx_fee,
                                tx_size,
                                input_count,
                                output_count
                            )
                            
                            # Send immediate notification for this OP_RETURN (only in continual scanning mode)
                            if send_immediate_notifications and self.notifier.any_enabled:
                                file_path = metadata.get('saved_file_path')
                                file_type = metadata.get('file_type')
                                decoded_text = metadata.get('decoded_text')
                                
                                # If decoded_text is not in metadata but file_type is text, try to read from file
                                if not decoded_text and file_type == 'text':
                                    block_dir = self.output_dir / f"block_{block_number}"
                                    base_name = f"tx_{txid}_{vout_idx}"
                                    decoded_txt_file = block_dir / f"{base_name}_decoded.txt"
                                    if decoded_txt_file.exists():
                                        try:
                                            with open(decoded_txt_file, 'r', encoding='utf-8') as f:
                                                decoded_text = f.read()
                                        except Exception as e:
                                            logger.debug(f"Could not read decoded text file: {e}")
                                
                                # Determine if it's a valid decoded file (not just binary)
                                is_valid_file = (
                                    file_path and 
                                    file_type and 
                                    file_type not in ['binary'] and
                                    Path(file_path).exists()
                                )
                                
                                found_item = {
                                    'block': block_number,
                                    'mined_by': mined_by or "Unknown",
                                    'txid': txid,
                                    'size': len(data),
                                    'type': file_type or 'binary',
                                    'file_path': file_path if is_valid_file else None,
                                    'file_type': file_type if is_valid_file else None,
                                    'decoded_text': decoded_text  # Include decoded_text if available (will be None if not text)
                                }
                                
                                # Send immediate notification
                                self.notifier.notify_new_op_returns([found_item])
                            
            
            # Update scan record with found count
            if self.use_database and scan_record:
                scan_record.large_op_returns_found = found_count
                self.db.commit()
            
            return found_count
            
        except Exception as e:
            logger.error(f"Error scanning block {block_number}: {e}")
            if self.use_database:
                self.db.rollback()
            return 0
    
    def scan_block_rpc_only(self, block_number):
        """Scan a single block for OP_RETURN transactions (RPC-only mode, no DB/filesystem)
        
        Returns:
            tuple: (found_count, op_returns_list) where op_returns_list contains dicts with:
                block, txid, vout_index, size, mined_by
        """
        try:
            block_hash = self.btc_service._call_rpc("getblockhash", [block_number])
            block = self.btc_service._call_rpc("getblock", [block_hash, 2])  # Verbosity 2 for full tx data
            
            block_time = datetime.fromtimestamp(block['time'])
            total_tx_count = len(block['tx'])
            found_count = 0
            op_returns_found = []
            
            # Extract mining pool from coinbase transaction (first tx)
            mined_by = None
            coinbase_tx = None
            if len(block['tx']) > 0:
                coinbase_tx = block['tx'][0]
                mined_by, _ = self.extract_mining_pool(coinbase_tx)
            
            # Check for BIP signaling (e.g., BIP-110) even in RPC-only mode
            block_header = {
                'version': block.get('version'),
                'time': block.get('time'),
                'bits': block.get('bits'),
                'nonce': block.get('nonce'),
            }
            bip110_signal = self.bip_detector.detect_bip110(
                coinbase_tx, 
                block_header, 
                block_number, 
                block_time, 
                mined_by
            )
            if bip110_signal:
                logger.info(f"🔔 BIP-110 signal detected in block {block_number} (mined by {mined_by})")
                logger.info(f"   Detection methods: {', '.join(bip110_signal['detection_methods'])}")
                if bip110_signal.get('coinbase_text'):
                    logger.debug(f"   Coinbase text: {bip110_signal['coinbase_text'][:200]}")
                self.bip_detector.save_bip_signal('bip-110', bip110_signal)
                # Send notification about BIP signal
                if self.notifier.any_enabled:
                    self.notifier.notify_bip_signal(bip110_signal)
            else:
                # Debug: Log when we don't detect BIP-110 for known blocks
                if block_number in [938903]:
                    logger.warning(f"   ⚠️  Block {block_number} did not match BIP-110 patterns")
                    if coinbase_tx and coinbase_tx.get('vin'):
                        coinbase_input = coinbase_tx['vin'][0]
                        if 'coinbase' in coinbase_input:
                            coinbase_hex = coinbase_input['coinbase']
                            try:
                                coinbase_bytes = bytes.fromhex(coinbase_hex)
                                coinbase_text = coinbase_bytes.decode('ascii', errors='ignore')
                                logger.warning(f"   Coinbase text: {repr(coinbase_text[:500])}")
                            except:
                                logger.warning(f"   Coinbase hex: {coinbase_hex[:200]}")
            
            # Check each transaction
            for tx in block['tx']:
                txid = tx['txid']
                
                # Check each output
                for vout_idx, vout in enumerate(tx['vout']):
                    script_hex = vout['scriptPubKey'].get('hex', '')
                    
                    # Check if it's OP_RETURN
                    if script_hex.startswith('6a'):  # OP_RETURN opcode
                        data = self.extract_op_return_from_script(script_hex)
                        
                        if data and len(data) > 83:
                            found_count += 1
                            op_returns_found.append({
                                'block': block_number,
                                'txid': txid,
                                'vout_index': vout_idx,
                                'size': len(data),
                                'mined_by': mined_by or "Unknown"
                            })
            
            return found_count, op_returns_found
            
        except Exception as e:
            logger.error(f"Error scanning block {block_number}: {e}")
            return 0, []
    
    def scan_blocks_rpc_only(self, start_block, end_block=None):
        """Scan a range of blocks for OP_RETURN transactions (RPC-only mode, no DB/filesystem)
        
        Returns:
            dict: Summary with keys: total_blocks_scanned, blocks_with_op_returns, total_op_returns, op_returns_by_block
        """
        # Get current block height if end not specified
        if end_block is None:
            chain_info = self.btc_service._call_rpc("getblockchaininfo")
            end_block = chain_info['blocks']
        
        logger.info(f"🔍 RPC-Only Mode: Scanning blocks {start_block} to {end_block}")
        logger.info(f"   Looking for OP_RETURN data > 83 bytes")
        logger.info(f"   No database or filesystem operations will be performed")
        print()
        
        total_blocks_scanned = 0
        blocks_with_op_returns = []
        total_op_returns = 0
        op_returns_by_block = {}
        
        total_blocks = end_block - start_block + 1
        
        for block_num in range(start_block, end_block + 1):
            if block_num % 100 == 0 or block_num == start_block:
                progress = ((block_num - start_block) / total_blocks) * 100
                logger.info(f"📈 Progress: {progress:.1f}% (Block {block_num}/{end_block})")
            
            found_count, op_returns_list = self.scan_block_rpc_only(block_num)
            total_blocks_scanned += 1
            
            if found_count > 0:
                blocks_with_op_returns.append(block_num)
                total_op_returns += found_count
                op_returns_by_block[block_num] = op_returns_list
                
                logger.info(f"✅ Block {block_num}: Found {found_count} large OP_RETURN(s)")
                for op_return in op_returns_list:
                    logger.info(f"   - TX: {op_return['txid'][:16]}..., VOUT: {op_return['vout_index']}, Size: {op_return['size']} bytes")
        
        logger.info(f"\n✅ RPC-Only Scan Complete!")
        logger.info(f"   Scanned {total_blocks_scanned} blocks")
        logger.info(f"   Blocks with large OP_RETURNs: {len(blocks_with_op_returns)}")
        logger.info(f"   Total large OP_RETURNs found: {total_op_returns}")
        
        if blocks_with_op_returns:
            logger.info(f"\n📋 Blocks with large OP_RETURNs:")
            for block_num in blocks_with_op_returns:
                op_returns = op_returns_by_block[block_num]
                logger.info(f"   Block {block_num}: {len(op_returns)} OP_RETURN(s)")
                for op_return in op_returns:
                    logger.info(f"      - {op_return['txid']} (vout {op_return['vout_index']}, {op_return['size']} bytes)")
        
        return {
            'total_blocks_scanned': total_blocks_scanned,
            'blocks_with_op_returns': blocks_with_op_returns,
            'total_op_returns': total_op_returns,
            'op_returns_by_block': op_returns_by_block
        }
    
    def scan_blocks(self, start_block, end_block=None, auto_continue=False, backwards=False, send_immediate_notifications=False, bip_only=False):
        """Scan a range of blocks
        
        Args:
            bip_only: If True, only detect BIP signaling, skip OP_RETURN scanning
        """
        # Handle backwards mode (scan backwards in time from first scanned block)
        if backwards:
            first_scanned = self.get_first_scanned_block()
            if first_scanned:
                # Scan one month backwards (~4320 blocks = 30 days * 144 blocks/day)
                end_block = first_scanned - 1
                start_block = max(0, first_scanned - 4320)
                logger.info(f"📍 Scanning backwards from first scanned block: {first_scanned}")
                logger.info(f"   Going back ~1 month ({first_scanned - start_block} blocks)")
            else:
                logger.error("📍 No previous scans found, cannot scan backwards")
                return 0, []
        # Handle auto-continue mode
        elif auto_continue:
            last_scanned = self.get_last_scanned_block()
            if last_scanned:
                start_block = last_scanned + 1
                logger.info(f"📍 Auto-continue from last scanned block: {last_scanned}")
            else:
                logger.info(f"📍 No previous scans found, starting from block {start_block}")
        
        # Get current block height if end not specified
        if end_block is None and not backwards:
            chain_info = self.btc_service._call_rpc("getblockchaininfo")
            end_block = chain_info['blocks']
        
        # Show current stats if database is enabled
        if self.use_database:
            stats = self.get_scan_statistics()
            if stats['total_blocks_scanned'] > 0:
                logger.info(f"📊 Previous statistics:")
                logger.info(f"   Blocks scanned: {stats['total_blocks_scanned']}")
                logger.info(f"   Large OP_RETURNs found: {stats['total_large_op_returns']}")
                logger.info(f"   Average per block: {stats['avg_per_block']:.2f}")
                print()
        
        if bip_only:
            logger.info(f"🔍 Scanning blocks {start_block} to {end_block} for BIP signaling")
            logger.info(f"   BIP-only mode: OP_RETURN scanning disabled")
        else:
            logger.info(f"🔍 Scanning blocks {start_block} to {end_block}")
            logger.info(f"   Looking for OP_RETURN data > 83 bytes")
            logger.info(f"   Output directory: {self.output_dir.absolute()}")
        print()
        
        total_found = 0
        total_blocks = end_block - start_block + 1
        found_items = []  # Track all found OP_RETURNs for summary
        
        for block_num in range(start_block, end_block + 1):
            if block_num % 100 == 0 or block_num == start_block:
                progress = ((block_num - start_block) / total_blocks) * 100
                logger.info(f"📈 Progress: {progress:.1f}% (Block {block_num}/{end_block})")
            
            found = self.scan_block(block_num, send_immediate_notifications=send_immediate_notifications, bip_only=bip_only)
            total_found += found
            
            # If OP_RETURNs were found, get their details (for batch notification if not using immediate)
            if found > 0 and self.use_database and not send_immediate_notifications:
                scan_record = self.db.query(OPReturnScan).filter(
                    OPReturnScan.block_number == block_num
                ).first()
                if scan_record:
                    for op_return in scan_record.op_returns:
                        # Try to find the file path from disk
                        block_dir = self.output_dir / f"block_{block_num}"
                        base_name = f"tx_{op_return.txid}_{op_return.vout_index}"
                        file_path = None
                        file_type = op_return.file_type
                        
                        # Check if file exists
                        if file_type and file_type not in ['binary', 'text']:
                            potential_file = block_dir / f"{base_name}.{file_type}"
                            if potential_file.exists():
                                file_path = str(potential_file)
                        
                        found_items.append({
                            'block': block_num,
                            'mined_by': scan_record.mined_by or "Unknown",
                            'txid': op_return.txid,
                            'size': op_return.data_size,
                            'type': op_return.file_type,
                            'file_path': file_path,
                            'file_type': file_type if file_path else None
                        })
        
        logger.info(f"\n✅ Scan complete!")
        logger.info(f"   Scanned {total_blocks} blocks")
        if not bip_only:
            logger.info(f"   Found {total_found} OP_RETURN transactions > 83 bytes")
        else:
            logger.info(f"   BIP detection complete - check bip_blocks/ directory for results")
        
        # Display found items summary
        if found_items:
            logger.info(f"\n📋 Found OP_RETURNs in this scan:")
            logger.info(f"   {'Block':<8} {'Miner':<20} {'Size (bytes)':<12} {'Type':<10} {'Transaction ID'}")
            logger.info(f"   {'-'*8} {'-'*20} {'-'*12} {'-'*10} {'-'*64}")
            for item in found_items:
                logger.info(f"   {item['block']:<8} {item['mined_by']:<20} {item['size']:<12} {item['type']:<10} {item['txid'][:16]}...")
        
        if self.use_database:
            stats = self.get_scan_statistics()
            logger.info(f"\n📊 Overall statistics:")
            logger.info(f"   Total blocks scanned: {stats['total_blocks_scanned']}")
            logger.info(f"   Total large OP_RETURNs: {stats['total_large_op_returns']}")
            logger.info(f"   Block range: {stats['first_block']} - {stats['last_block']}")
            logger.info(f"   Average per block: {stats['avg_per_block']:.2f}")
        
        logger.info(f"\n💾 Data saved to: {self.output_dir.absolute()}")
        
        # Regenerate timeline_data.json if any OP_RETURNs were found (skip in bip_only mode)
        if not bip_only and total_found > 0:
            self.regenerate_timeline_data()
        
        # Send batch notifications if OP_RETURNs were found (only if not using immediate notifications, skip in bip_only)
        if not bip_only and total_found > 0 and found_items and not send_immediate_notifications:
            self.notifier.notify_new_op_returns(found_items)
        
        # Auto-sync git if enabled (check even if no new OP_RETURNs found, or if BIP data was saved)
        if self.auto_sync_git:
            self.sync_git_changes()
        else:
            logger.debug("Git auto-sync is disabled (set OP_RETURN_AUTO_SYNC_GIT=true or use --auto-sync-git)")
        
        return total_found, found_items
    
    def rescan_large_op_returns(self):
        """Re-scan all blocks that have large OP_RETURNs to update with new features (like fee tracking)"""
        if not self.use_database:
            logger.error("Re-scanning requires database to be enabled")
            return 0
        
        # Get all blocks that have large OP_RETURNs
        blocks_with_ops = self.db.query(OPReturnScan).filter(
            OPReturnScan.large_op_returns_found > 0
        ).order_by(OPReturnScan.block_number).all()
        
        if not blocks_with_ops:
            logger.info("No blocks with large OP_RETURNs found to re-scan")
            return 0
        
        total_blocks = len(blocks_with_ops)
        total_ops = sum(scan.large_op_returns_found for scan in blocks_with_ops)
        
        logger.info(f"\n🔄 Re-scanning blocks with large OP_RETURNs")
        logger.info("=" * 80)
        logger.info(f"Found {total_blocks} blocks with {total_ops} large OP_RETURNs")
        logger.info("This will DELETE and RE-SCAN to update with latest features (e.g., fee tracking)")
        logger.info("")
        
        # Confirm with user
        response = input("Continue with re-scan? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            logger.info("Re-scan cancelled")
            return 0
        
        logger.info("\n🚀 Starting re-scan...")
        print()
        
        rescanned_count = 0
        ops_found = 0
        
        for idx, scan in enumerate(blocks_with_ops, 1):
            block_num = scan.block_number
            
            # Show progress
            if idx % 10 == 0 or idx == 1:
                progress = (idx / total_blocks) * 100
                logger.info(f"📈 Progress: {progress:.1f}% ({idx}/{total_blocks} blocks)")
            
            try:
                # Delete the existing scan (cascades to LargeOPReturn records)
                self.db.query(LargeOPReturn).filter(
                    LargeOPReturn.scan_id == scan.id
                ).delete()
                self.db.query(OPReturnScan).filter(
                    OPReturnScan.id == scan.id
                ).delete()
                self.db.commit()
                
                # Re-scan the block
                found = self.scan_block(block_num, skip_if_scanned=False)
                ops_found += found
                rescanned_count += 1
                
            except Exception as e:
                logger.error(f"Error re-scanning block {block_num}: {e}")
                self.db.rollback()
                continue
        
        logger.info(f"\n✅ Re-scan complete!")
        logger.info(f"   Re-scanned {rescanned_count} blocks")
        logger.info(f"   Found {ops_found} OP_RETURN transactions")
        
        # Show updated statistics
        stats = self.get_scan_statistics()
        logger.info(f"\n📊 Updated statistics:")
        logger.info(f"   Total blocks scanned: {stats['total_blocks_scanned']}")
        logger.info(f"   Total large OP_RETURNs: {stats['total_large_op_returns']}")
        logger.info(f"   Block range: {stats['first_block']} - {stats['last_block']}")
        logger.info(f"   Average per block: {stats['avg_per_block']:.2f}")
        
        return rescanned_count
    
    def sync_filesystem_to_database(self, block_number=None, verify_with_node=True):
        """Sync OP_RETURN data from filesystem to database
        
        Args:
            block_number: Specific block to sync (None = scan all blocks)
            verify_with_node: If True, verify transaction data with Bitcoin node
        """
        if not self.use_database:
            logger.error("Filesystem sync requires database mode (don't use --no-db)")
            return 0
        
        logger.info(f"\n🔄 Syncing filesystem data to database...")
        if block_number:
            logger.info(f"   Block: {block_number}")
        else:
            logger.info(f"   Scanning all blocks in filesystem")
        
        synced_count = 0
        
        try:
            # Find all block directories
            if block_number:
                block_dirs = [self.output_dir / f"block_{block_number}"]
            else:
                block_dirs = [d for d in self.output_dir.iterdir() if d.is_dir() and d.name.startswith('block_')]
            
            for block_dir in block_dirs:
                if not block_dir.exists():
                    continue
                
                try:
                    block_num = int(block_dir.name.replace('block_', ''))
                except ValueError:
                    continue
                
                # Find all metadata.json files
                metadata_files = list(block_dir.glob('*_metadata.json'))
                
                if not metadata_files:
                    continue
                
                logger.info(f"\n   Block {block_num}: Found {len(metadata_files)} metadata file(s)")
                
                # Check if scan record exists
                scan_record = self.db.query(OPReturnScan).filter(
                    OPReturnScan.block_number == block_num
                ).first()
                
                # Process each metadata file
                for metadata_file in metadata_files:
                    try:
                        with open(metadata_file, 'r') as f:
                            metadata = json.load(f)
                        
                        txid = metadata.get('transaction_id')
                        vout_index = metadata.get('vout_index')
                        
                        if not txid or vout_index is None:
                            logger.warning(f"     ⚠️  Invalid metadata: {metadata_file.name}")
                            continue
                        
                        # Check if OP_RETURN already exists in database
                        existing_op = self.db.query(LargeOPReturn).filter(
                            LargeOPReturn.txid == txid,
                            LargeOPReturn.vout_index == vout_index
                        ).first()
                        
                        if existing_op:
                            logger.debug(f"     ✓ Already in DB: {txid[:16]}...")
                            continue
                        
                        # Verify with Bitcoin node if requested
                        if verify_with_node:
                            try:
                                block_hash = self.btc_service._call_rpc("getblockhash", [block_num])
                                block = self.btc_service._call_rpc("getblock", [block_hash, 2])
                                
                                # Find the transaction
                                tx = None
                                for t in block.get('tx', []):
                                    if t['txid'] == txid:
                                        tx = t
                                        break
                                
                                if not tx:
                                    logger.warning(f"     ⚠️  Transaction {txid[:16]}... not found in block {block_num}")
                                    continue
                                
                                # Verify OP_RETURN exists
                                found_op_return = False
                                for vout_idx, vout in enumerate(tx.get('vout', [])):
                                    script_hex = vout['scriptPubKey'].get('hex', '')
                                    if script_hex.startswith('6a'):  # OP_RETURN
                                        data = self.extract_op_return_from_script(script_hex)
                                        if data and len(data) > 83 and vout_idx == vout_index:
                                            found_op_return = True
                                            break
                                
                                if not found_op_return:
                                    logger.warning(f"     ⚠️  OP_RETURN not found at vout {vout_index} in transaction {txid[:16]}...")
                                    continue
                                
                            except Exception as e:
                                logger.warning(f"     ⚠️  Could not verify with node: {e}")
                                # Continue anyway - trust filesystem data
                        
                        # Create or update scan record
                        if not scan_record:
                            block_time_str = metadata.get('block_time')
                            block_hash_val = 'unknown'
                            total_tx_count = 0
                            mined_by_val = None
                            coinbase_text_val = None
                            
                            if block_time_str:
                                try:
                                    block_time = datetime.fromisoformat(block_time_str.replace('Z', '+00:00'))
                                except:
                                    block_time = datetime.now()
                            else:
                                block_time = datetime.now()
                            
                            # Get from node if available
                            try:
                                block_hash_val = self.btc_service._call_rpc("getblockhash", [block_num])
                                block = self.btc_service._call_rpc("getblock", [block_hash_val, 2])
                                block_time = datetime.fromtimestamp(block['time'])
                                total_tx_count = len(block.get('tx', []))
                                
                                # Extract mining pool
                                if len(block.get('tx', [])) > 0:
                                    coinbase_tx = block['tx'][0]
                                    mined_by_val, coinbase_text_val = self.extract_mining_pool(coinbase_tx)
                            except Exception as e:
                                logger.debug(f"     Could not fetch block info from node: {e}")
                            
                            scan_record = OPReturnScan(
                                block_number=block_num,
                                block_hash=block_hash_val,
                                block_time=block_time,
                                total_transactions=total_tx_count,
                                large_op_returns_found=0,  # Will update after counting
                                mined_by=metadata.get('mined_by') or mined_by_val,
                                coinbase_text=coinbase_text_val
                            )
                            self.db.add(scan_record)
                            self.db.flush()  # Get the ID
                        
                        # Read raw data if available
                        raw_data_hex = metadata.get('raw_data_hex')
                        raw_data = None
                        if raw_data_hex:
                            try:
                                raw_data = bytes.fromhex(raw_data_hex)
                            except:
                                pass
                        
                        # If raw data not in metadata, try to read from file
                        if not raw_data:
                            base_name = f"tx_{txid}_{vout_index}"
                            raw_file = block_dir / f"{base_name}_raw.bin"
                            if raw_file.exists():
                                with open(raw_file, 'rb') as f:
                                    raw_data = f.read()
                        
                        # Determine if we should store raw_data in DB (limit 32767 bytes)
                        store_raw_data = raw_data and len(raw_data) <= 32767
                        data_hex = raw_data_hex if raw_data_hex else (raw_data.hex() if raw_data else None)
                        
                        # Get decoded text if available
                        decoded_text = None
                        if metadata.get('file_type') == 'text':
                            decoded_txt_file = block_dir / f"tx_{txid}_{vout_index}_decoded.txt"
                            if decoded_txt_file.exists():
                                with open(decoded_txt_file, 'r', encoding='utf-8') as f:
                                    decoded_text = f.read()
                        
                        # Create LargeOPReturn record
                        large_op_return = LargeOPReturn(
                            scan_id=scan_record.id,
                            block_number=block_num,
                            txid=txid,
                            vout_index=vout_index,
                            data_size=metadata.get('data_size', 0),
                            raw_data=data_hex if store_raw_data else None,
                            decoded_text=decoded_text if store_raw_data and decoded_text else None,
                            file_type=metadata.get('file_type', 'binary'),
                            mime_type=metadata.get('mime_type', 'application/octet-stream'),
                            is_text=metadata.get('file_type') == 'text',
                            storage_format=metadata.get('storage_format', 'raw'),
                            tx_fee=metadata.get('transaction_fee_sats'),
                            tx_size=metadata.get('transaction_size_vbytes'),
                            fee_rate=metadata.get('fee_rate_sats_per_vbyte'),
                            cost_per_byte=metadata.get('cost_per_byte_of_data'),
                            tx_input_count=metadata.get('tx_inputs'),
                            tx_output_count=metadata.get('tx_outputs')
                        )
                        self.db.add(large_op_return)
                        synced_count += 1
                        logger.info(f"     ✓ Synced: {txid[:16]}... ({metadata.get('data_size', 0)} bytes, {metadata.get('file_type', 'binary')})")
                        
                    except Exception as e:
                        logger.error(f"     ❌ Error syncing {metadata_file.name}: {e}")
                        import traceback
                        traceback.print_exc()
                        continue
                
                # Update scan record count
                if scan_record:
                    op_count = self.db.query(LargeOPReturn).filter(
                        LargeOPReturn.scan_id == scan_record.id
                    ).count()
                    scan_record.large_op_returns_found = op_count
                
                self.db.commit()
            
            logger.info(f"\n✅ Sync complete! Synced {synced_count} OP_RETURN(s) to database")
            return synced_count
            
        except Exception as e:
            logger.error(f"Error syncing filesystem to database: {e}")
            import traceback
            traceback.print_exc()
            self.db.rollback()
            return 0
    
    def test_notification(self, block_number):
        """Test notification system by sending a notification for the first OP_RETURN in a block"""
        logger.info(f"\n🧪 Testing notification system with block {block_number}")
        
        if not self.use_database:
            logger.error("Test notification requires database mode (don't use --no-db)")
            return False
        
        try:
            # First, try to sync filesystem data if files exist but not in DB
            block_dir = self.output_dir / f"block_{block_number}"
            if block_dir.exists() and list(block_dir.glob('*_metadata.json')):
                logger.info(f"   Found filesystem data, checking database sync...")
                self.sync_filesystem_to_database(block_number=block_number, verify_with_node=True)
            
            # Check if block is already scanned in database
            scan_record = self.db.query(OPReturnScan).filter(
                OPReturnScan.block_number == block_number
            ).first()
            
            if scan_record and scan_record.large_op_returns_found > 0:
                # Use existing data from database
                logger.info(f"   Block {block_number} already scanned, using existing data")
                
                # Query LargeOPReturn directly (relationship might not be loaded)
                op_return = self.db.query(LargeOPReturn).filter(
                    LargeOPReturn.scan_id == scan_record.id
                ).first()
                
                if not op_return:
                    logger.warning(f"   ⚠️  Block {block_number} shows {scan_record.large_op_returns_found} OP_RETURNs but none found in database")
                    logger.info(f"   Try scanning the block again or use a different block number")
                    return False
                
                # Try to find file path
                block_dir = self.output_dir / f"block_{block_number}"
                base_name = f"tx_{op_return.txid}_{op_return.vout_index}"
                file_path = None
                file_type = op_return.file_type
                
                # Check if file exists
                if file_type and file_type not in ['binary', 'text']:
                    potential_file = block_dir / f"{base_name}.{file_type}"
                    if potential_file.exists():
                        file_path = str(potential_file)
                
                # Also check for text files
                if not file_path and file_type == 'text':
                    potential_file = block_dir / f"{base_name}_decoded.txt"
                    if potential_file.exists():
                        file_path = str(potential_file)
                
                # Read decoded text if it's a text type
                decoded_text = None
                if file_type == 'text':
                    # First try database
                    if op_return.decoded_text:
                        decoded_text = op_return.decoded_text
                    else:
                        # Fallback to filesystem
                        decoded_txt_file = block_dir / f"{base_name}_decoded.txt"
                        if decoded_txt_file.exists():
                            try:
                                with open(decoded_txt_file, 'r', encoding='utf-8') as f:
                                    decoded_text = f.read()
                            except Exception as e:
                                logger.debug(f"Could not read decoded text: {e}")
                
                found_item = {
                    'block': block_number,
                    'mined_by': scan_record.mined_by or "Unknown",
                    'txid': op_return.txid,
                    'size': op_return.data_size,
                    'type': op_return.file_type,
                    'file_path': file_path,
                    'file_type': file_type if file_path else None,
                    'decoded_text': decoded_text
                }
            else:
                # Block not scanned yet, scan it now
                logger.info(f"   Block {block_number} not scanned yet, scanning now...")
                found_count = self.scan_block(block_number, skip_if_scanned=False)
                
                if found_count == 0:
                    logger.warning(f"   ⚠️  No large OP_RETURNs found in block {block_number}")
                    logger.info(f"   Try a different block number that contains large OP_RETURNs")
                    return False
                
                # Get the first OP_RETURN from database
                scan_record = self.db.query(OPReturnScan).filter(
                    OPReturnScan.block_number == block_number
                ).first()
                
                if not scan_record:
                    logger.warning(f"   ⚠️  Could not retrieve scan record from database")
                    return False
                
                # Query LargeOPReturn directly (relationship might not be loaded)
                op_return = self.db.query(LargeOPReturn).filter(
                    LargeOPReturn.scan_id == scan_record.id
                ).first()
                
                if not op_return:
                    logger.warning(f"   ⚠️  Could not retrieve OP_RETURN data from database")
                    return False
                
                # Try to find file path
                block_dir = self.output_dir / f"block_{block_number}"
                base_name = f"tx_{op_return.txid}_{op_return.vout_index}"
                file_path = None
                file_type = op_return.file_type
                
                # Check if file exists
                if file_type and file_type not in ['binary', 'text']:
                    potential_file = block_dir / f"{base_name}.{file_type}"
                    if potential_file.exists():
                        file_path = str(potential_file)
                
                # Also check for text files
                if not file_path and file_type == 'text':
                    potential_file = block_dir / f"{base_name}_decoded.txt"
                    if potential_file.exists():
                        file_path = str(potential_file)
                
                # Read decoded text if it's a text type
                decoded_text = None
                if file_type == 'text':
                    # First try database
                    if op_return.decoded_text:
                        decoded_text = op_return.decoded_text
                    else:
                        # Fallback to filesystem
                        decoded_txt_file = block_dir / f"{base_name}_decoded.txt"
                        if decoded_txt_file.exists():
                            try:
                                with open(decoded_txt_file, 'r', encoding='utf-8') as f:
                                    decoded_text = f.read()
                            except Exception as e:
                                logger.debug(f"Could not read decoded text: {e}")
                
                found_item = {
                    'block': block_number,
                    'mined_by': scan_record.mined_by or "Unknown",
                    'txid': op_return.txid,
                    'size': op_return.data_size,
                    'type': op_return.file_type,
                    'file_path': file_path,
                    'file_type': file_type if file_path else None,
                    'decoded_text': decoded_text
                }
            
            # Send test notification
            logger.info(f"\n📤 Sending test notification...")
            logger.info(f"   Block: {found_item['block']}")
            logger.info(f"   TX: {found_item['txid'][:16]}...")
            logger.info(f"   Size: {found_item['size']} bytes")
            logger.info(f"   Type: {found_item['type']}")
            if found_item.get('file_path'):
                logger.info(f"   File: {found_item['file_path']}")
            
            self.notifier.notify_new_op_returns([found_item])
            
            logger.info(f"\n✅ Test notification sent!")
            logger.info(f"   Check your configured notification channels (Email/Telegram/Discord/SMS)")
            
            return True
            
        except Exception as e:
            logger.error(f"Error testing notification: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def continual_scan(self, interval_seconds=60, heartbeat_interval=3600):
        """Continuously scan for new blocks at specified interval
        
        Args:
            interval_seconds: Seconds between block scans
            heartbeat_interval: Seconds between heartbeat messages (default: 3600 = 1 hour)
        """
        logger.info(f"\n🔄 Starting continual scanning mode")
        logger.info(f"   Interval: {interval_seconds} seconds")
        if heartbeat_interval:
            logger.info(f"   Heartbeat interval: {heartbeat_interval} seconds")
        logger.info(f"   Press Ctrl+C to stop")
        print()
        
        if not self.use_database:
            logger.error("Continual scanning requires database mode (don't use --no-db)")
            return
        
        # Send startup notification
        self.notifier.notify_startup(interval_seconds, heartbeat_interval)
        
        # Track blocks scanned for heartbeat
        blocks_scanned_since_heartbeat = 0
        failed_rpc_calls_since_heartbeat = 0
        last_heartbeat_time = time.time()
        initial_block_count = self.get_scan_statistics()['total_blocks_scanned'] or 0
        first_block_scanned_since_heartbeat = None  # Track first block scanned in this heartbeat period
        last_block_scanned_since_heartbeat = None   # Track last block scanned in this heartbeat period
        
        try:
            while True:
                try:
                    # Get current blockchain height
                    try:
                        chain_info = self.btc_service._call_rpc("getblockchaininfo")
                        current_height = chain_info['blocks']
                    except Exception as rpc_error:
                        failed_rpc_calls_since_heartbeat += 1
                        logger.error(f"❌ RPC call failed: {rpc_error}")
                        logger.info(f"   Failed RPC calls since last heartbeat: {failed_rpc_calls_since_heartbeat}")
                        
                        # Check if it's time for a heartbeat (even with failures)
                        current_time = time.time()
                        if heartbeat_interval and (current_time - last_heartbeat_time) >= heartbeat_interval:
                            stats = self.get_scan_statistics()
                            total_blocks = stats['total_blocks_scanned'] or 0
                            last_block = stats['last_block'] or self.get_last_scanned_block() or 0
                            
                            self.notifier.notify_heartbeat(
                                blocks_scanned_since_heartbeat,
                                total_blocks,
                                last_block,
                                failed_rpc_calls_since_heartbeat,
                                first_block_scanned_since_heartbeat,
                                last_block_scanned_since_heartbeat
                            )
                            
                            # Reset heartbeat tracking
                            blocks_scanned_since_heartbeat = 0
                            failed_rpc_calls_since_heartbeat = 0
                            first_block_scanned_since_heartbeat = None
                            last_block_scanned_since_heartbeat = None
                            last_heartbeat_time = current_time
                        
                        # Wait before retrying
                        logger.info(f"   Retrying in {interval_seconds} seconds...")
                        time.sleep(interval_seconds)
                        continue
                    
                    # Get last scanned block
                    last_scanned = self.get_last_scanned_block()
                    
                    if last_scanned is None:
                        # First scan - start from current height
                        logger.info(f"📍 No previous scans, starting from block {current_height}")
                        start_block = current_height
                    else:
                        start_block = last_scanned + 1
                    
                    # Check if there are new blocks
                    if start_block > current_height:
                        logger.debug(f"⏳ No new blocks (current: {current_height}, last scanned: {last_scanned})")
                    else:
                        # Scan new blocks
                        end_block = current_height
                        blocks_to_scan = end_block - start_block + 1
                        
                        if blocks_to_scan > 0:
                            logger.info(f"🔍 Scanning {blocks_to_scan} new block(s): {start_block} to {end_block}")
                            
                            # Track first block scanned in this heartbeat period
                            if first_block_scanned_since_heartbeat is None:
                                first_block_scanned_since_heartbeat = start_block
                            
                            # Note: scan_blocks will send immediate notifications for each OP_RETURN found
                            # We don't need to send another batch notification here
                            total_found, found_items = self.scan_blocks(
                                start_block, 
                                end_block, 
                                auto_continue=False, 
                                backwards=False,
                                send_immediate_notifications=True  # Enable immediate notifications in continual mode
                            )
                            
                            # Track blocks scanned for heartbeat
                            blocks_scanned_since_heartbeat += blocks_to_scan
                            last_block_scanned_since_heartbeat = end_block
                            
                            if total_found > 0:
                                logger.info(f"✅ Found {total_found} new OP_RETURN(s) in this scan")
                            else:
                                logger.debug(f"   No large OP_RETURNs found in these blocks")
                        else:
                            logger.debug(f"⏳ No new blocks to scan")
                    
                    # Check if it's time for a heartbeat
                    current_time = time.time()
                    if heartbeat_interval and (current_time - last_heartbeat_time) >= heartbeat_interval:
                        stats = self.get_scan_statistics()
                        total_blocks = stats['total_blocks_scanned'] or 0
                        last_block = stats['last_block'] or last_scanned or 0
                        
                        self.notifier.notify_heartbeat(
                            blocks_scanned_since_heartbeat,
                            total_blocks,
                            last_block,
                            failed_rpc_calls_since_heartbeat,
                            first_block_scanned_since_heartbeat,
                            last_block_scanned_since_heartbeat
                        )
                        
                        # Reset heartbeat tracking
                        blocks_scanned_since_heartbeat = 0
                        failed_rpc_calls_since_heartbeat = 0
                        first_block_scanned_since_heartbeat = None
                        last_block_scanned_since_heartbeat = None
                        last_heartbeat_time = current_time
                    
                    # Wait for next interval
                    logger.debug(f"⏸️  Waiting {interval_seconds} seconds until next scan...")
                    time.sleep(interval_seconds)
                    
                except KeyboardInterrupt:
                    logger.info("\n\n⏹️  Continual scanning stopped by user")
                    break
                except Exception as e:
                    failed_rpc_calls_since_heartbeat += 1
                    logger.error(f"❌ Error during continual scan: {e}")
                    logger.info(f"   Failed RPC calls since last heartbeat: {failed_rpc_calls_since_heartbeat}")
                    
                    # Check if it's time for a heartbeat (even with failures)
                    current_time = time.time()
                    if heartbeat_interval and (current_time - last_heartbeat_time) >= heartbeat_interval:
                        stats = self.get_scan_statistics()
                        total_blocks = stats['total_blocks_scanned'] or 0
                        last_block = stats['last_block'] or self.get_last_scanned_block() or 0
                        
                        self.notifier.notify_heartbeat(
                            blocks_scanned_since_heartbeat,
                            total_blocks,
                            last_block,
                            failed_rpc_calls_since_heartbeat,
                            first_block_scanned_since_heartbeat,
                            last_block_scanned_since_heartbeat
                        )
                        
                        # Reset heartbeat tracking
                        blocks_scanned_since_heartbeat = 0
                        failed_rpc_calls_since_heartbeat = 0
                        first_block_scanned_since_heartbeat = None
                        last_block_scanned_since_heartbeat = None
                        last_heartbeat_time = current_time
                    
                    logger.info(f"   Retrying in {interval_seconds} seconds...")
                    time.sleep(interval_seconds)
                    
        except KeyboardInterrupt:
            logger.info("\n\n⏹️  Continual scanning stopped")
    
    def reinterpret_file_types(self, file_type_filter='binary'):
        """Re-interpret file types for existing OP_RETURNs
        
        Args:
            file_type_filter: Only reinterpret OP_RETURNs with this file type (default: 'binary')
        """
        if not self.use_database:
            logger.error("Reinterpretation requires database to be enabled")
            return 0
        
        # Query for OP_RETURNs with the specified file type
        op_returns = self.db.query(LargeOPReturn).filter(
            LargeOPReturn.file_type == file_type_filter
        ).all()
        
        if not op_returns:
            logger.info(f"No OP_RETURNs found with file type '{file_type_filter}'")
            return 0
        
        logger.info(f"\n🔄 Reinterpreting {len(op_returns)} OP_RETURN(s) with file type '{file_type_filter}'")
        logger.info("=" * 80)
        
        updated_count = 0
        unchanged_count = 0
        
        for op_return in op_returns:
            try:
                # Get the raw data - handle cases where raw_data might be None (large files)
                if op_return.raw_data:
                    raw_data = bytes.fromhex(op_return.raw_data)
                else:
                    # For large files, read from disk
                    block_dir = self.output_dir / f"block_{op_return.block_number}"
                    base_name = f"tx_{op_return.txid}_{op_return.vout_index}"
                    raw_file = block_dir / f"{base_name}_raw.bin"
                    if raw_file.exists():
                        with open(raw_file, 'rb') as f:
                            raw_data = f.read()
                    else:
                        logger.warning(f"   ⚠️  Could not find raw data for {op_return.txid}")
                        unchanged_count += 1
                        continue
                
                # Detect file type again (may decode data URIs or base64)
                new_file_ext, new_mime_type, decoded_binary, new_storage_format = self.detect_file_type(raw_data)
                
                # Use decoded binary if available (from data URI or base64)
                save_data = decoded_binary if decoded_binary is not None else raw_data
                
                # Check if we found a more specific type (or if we decoded base64)
                type_changed = (new_file_ext and new_file_ext != file_type_filter) or (decoded_binary is not None and file_type_filter == 'text')
                
                if type_changed:
                    logger.info(f"\n📦 Block {op_return.block_number}, tx {op_return.txid[:16]}...")
                    logger.info(f"   Old type: {op_return.file_type}")
                    logger.info(f"   New type: {new_file_ext or 'binary'} ({new_mime_type or 'application/octet-stream'})")
                    logger.info(f"   Storage format: {new_storage_format}")
                    logger.info(f"   Size: {op_return.data_size} bytes")
                    
                    # Update database
                    op_return.file_type = new_file_ext or ("binary" if decoded_binary is not None else file_type_filter)
                    op_return.mime_type = new_mime_type or ("application/octet-stream" if decoded_binary is not None else op_return.mime_type)
                    op_return.storage_format = new_storage_format
                    # If we decoded base64, it's no longer text
                    if decoded_binary is not None:
                        op_return.is_text = False
                        op_return.decoded_text = None
                    
                    # Get the scan record to get block info
                    scan_record = self.db.query(OPReturnScan).filter(
                        OPReturnScan.id == op_return.scan_id
                    ).first()
                    
                    if scan_record:
                        # Update metadata JSON file
                        block_dir = self.output_dir / f"block_{op_return.block_number}"
                        base_name = f"tx_{op_return.txid}_{op_return.vout_index}"
                        metadata_file = block_dir / f"{base_name}_metadata.json"
                        
                        if metadata_file.exists():
                            with open(metadata_file, 'r') as f:
                                metadata = json.load(f)
                            
                            metadata['file_type'] = op_return.file_type
                            metadata['mime_type'] = op_return.mime_type
                            metadata['storage_format'] = new_storage_format
                            
                            with open(metadata_file, 'w', newline='\n') as f:
                                json.dump(metadata, f, indent=2)
                            
                            logger.info(f"   ✓ Updated metadata file")
                        
                        # Remove old decoded.txt if it exists and we decoded base64
                        if decoded_binary is not None or (new_file_ext and new_file_ext != 'text'):
                            decoded_txt_file = block_dir / f"{base_name}_decoded.txt"
                            if decoded_txt_file.exists():
                                decoded_txt_file.unlink()
                                logger.info(f"   ✓ Removed old decoded.txt file")
                        
                        # Create/update the file with proper extension (skip dangerous executables)
                        dangerous_types = {'exe', 'elf'}
                        if new_file_ext and new_file_ext not in dangerous_types:
                            new_file_path = block_dir / f"{base_name}.{new_file_ext}"
                            if not new_file_path.exists():
                                with open(new_file_path, 'wb') as f:
                                    f.write(save_data)
                                logger.info(f"   ✓ Created file: {new_file_path.name}")
                                if decoded_binary is not None:
                                    if new_storage_format == 'data_uri':
                                        logger.info(f"   🔓 Decoded from data URI")
                                    elif new_storage_format == 'base64':
                                        logger.info(f"   🔓 Decoded from base64")
                        elif new_file_ext in dangerous_types:
                            logger.warning(f"   ⚠️  Skipping all file creation for executable: {new_file_ext} (security risk)")
                            # Remove any existing .bin file if it was created before security fix
                            bin_file = block_dir / f"{base_name}_raw.bin"
                            if bin_file.exists():
                                bin_file.unlink()
                                logger.info(f"   ✓ Removed existing .bin file for security")
                    
                    updated_count += 1
                else:
                    unchanged_count += 1
                    
            except Exception as e:
                logger.error(f"Error reinterpreting OP_RETURN {op_return.txid}: {e}")
                import traceback
                traceback.print_exc()
        
        # Commit all changes
        self.db.commit()
        
        logger.info("\n" + "=" * 80)
        logger.info(f"✅ Reinterpretation complete!")
        logger.info(f"   Updated: {updated_count}")
        logger.info(f"   Unchanged: {unchanged_count}")
        
        return updated_count
    
    def regenerate_timeline_data(self):
        """Regenerate timeline_data.json from all scanned OP_RETURN data"""
        try:
            logger.info(f"\n📊 Regenerating timeline_data.json...")
            
            # Import generate_timeline_data functions
            import sys
            from pathlib import Path
            
            # Try to import the generate_timeline_data module
            try:
                # Check if generate_timeline_data.py exists in the same directory
                script_dir = Path(__file__).parent
                generate_script = script_dir / 'generate_timeline_data.py'
                
                if generate_script.exists():
                    # Import the module dynamically
                    import importlib.util
                    spec = importlib.util.spec_from_file_location("generate_timeline_data", generate_script)
                    generate_module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(generate_module)
                    
                    # Call the scan function (pass the op_return_data directory)
                    timeline_data = generate_module.scan_op_return_data(str(self.output_dir))
                    
                    if timeline_data:
                        # Save to JSON file (in op_return_data directory)
                        output_file = self.output_dir / 'timeline_data.json'
                        import json
                        with open(output_file, 'w', newline='\n') as f:
                            json.dump(timeline_data, f, indent=2)
                        
                        logger.info(f"   ✓ Updated timeline_data.json ({len(timeline_data)} items)")
                    else:
                        logger.debug("   No timeline data to generate")
                else:
                    logger.debug(f"   generate_timeline_data.py not found at {generate_script}")
            except Exception as e:
                logger.warning(f"   ⚠️  Failed to regenerate timeline_data.json: {e}")
                logger.debug(f"   You can manually run: python generate_timeline_data.py")
        except Exception as e:
            logger.debug(f"Error regenerating timeline data: {e}")
    
    def setup_git_authentication(self):
        """Setup git authentication using GitHub token or SSH"""
        if self.github_token:
            # Use HTTPS with token - update remote URL if needed
            try:
                # Check current remote URL
                result = subprocess.run(
                    ['git', 'remote', 'get-url', 'origin'],
                    capture_output=True,
                    text=True,
                    check=False,
                    cwd=str(self.submodule_root)
                )
                
                current_url = result.stdout.strip()
                
                # If using SSH URL, convert to HTTPS
                if current_url.startswith('git@github.com:'):
                    # Convert git@github.com:user/repo.git to https://github.com/user/repo.git
                    repo_path = current_url.replace('git@github.com:', '').replace('.git', '')
                    https_url = f'https://github.com/{repo_path}.git'
                    
                    # Update remote URL
                    subprocess.run(
                        ['git', 'remote', 'set-url', 'origin', https_url],
                        check=True,
                        cwd=str(self.submodule_root)
                    )
                    logger.debug(f"   Updated remote URL to HTTPS")
                
                return True
            except Exception as e:
                logger.debug(f"Git authentication setup error: {e}")
                return False
        else:
            # Fall back to SSH if no token provided
            logger.debug("No GITHUB_TOKEN found, using SSH authentication")
            return True
    
    def sync_git_changes(self):
        """Automatically commit and push changes to the bitcoin_large_op_returns submodule"""
        if not self.submodule_root or not self.submodule_root.exists():
            logger.debug("Submodule root not found, skipping git sync")
            return
        
        git_dir = self.submodule_root / '.git'
        if not git_dir.exists():
            logger.debug(f"Not a git repository: {self.submodule_root}")
            return
        
        # Setup git authentication (HTTPS with token or SSH)
        self.setup_git_authentication()
        
        # Log that we're checking for sync
        logger.info(f"\n🔄 Checking for git changes in {self.submodule_root.name}...")
        
        try:
            # Change to submodule directory
            original_cwd = os.getcwd()
            os.chdir(str(self.submodule_root))
            
            try:
                # Check if there are any changes
                result = subprocess.run(
                    ['git', 'status', '--porcelain'],
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if not result.stdout.strip():
                    logger.info(f"   ✓ No changes to commit - repository is up to date")
                    return
                
                # Show what will be committed
                logger.info(f"   Changes detected:")
                for line in result.stdout.strip().split('\n')[:10]:  # Show first 10 files
                    logger.info(f"     {line}")
                newline_count = result.stdout.count('\n')
                if newline_count > 10:
                    logger.info(f"     ... and {newline_count - 10} more files")
                
                # Add all changes
                subprocess.run(
                    ['git', 'add', '-A'],
                    check=True,
                    capture_output=True
                )
                
                # Get count of new/changed files for commit message
                status_lines = result.stdout.strip().split('\n')
                new_files = sum(1 for line in status_lines if line.startswith('??'))
                modified_files = len(status_lines) - new_files
                
                # Create commit message
                commit_msg = f"Add OP_RETURN data: {new_files} new files"
                if modified_files > 0:
                    commit_msg += f", {modified_files} modified"
                
                # Commit
                subprocess.run(
                    ['git', 'commit', '-m', commit_msg],
                    check=True,
                    capture_output=True
                )
                logger.info(f"   ✓ Committed changes")
                
                # Push to remote (use token if available)
                push_env = os.environ.copy()
                
                if self.github_token:
                    # Use HTTPS with token - embed token in URL for this push
                    result = subprocess.run(
                        ['git', 'remote', 'get-url', 'origin'],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    remote_url = result.stdout.strip()
                    
                    # Extract repo path from URL
                    if 'github.com' in remote_url:
                        if remote_url.startswith('https://'):
                            # Already HTTPS, add token
                            if '@' not in remote_url:  # No token already embedded
                                repo_path = remote_url.replace('https://github.com/', '').replace('.git', '')
                                token_url = f'https://{self.github_token}@github.com/{repo_path}.git'
                            else:
                                token_url = remote_url
                        else:
                            # SSH URL, convert to HTTPS with token
                            repo_path = remote_url.replace('git@github.com:', '').replace('.git', '')
                            token_url = f'https://{self.github_token}@github.com/{repo_path}.git'
                        
                        # Temporarily update remote URL with token, then push
                        subprocess.run(
                            ['git', 'remote', 'set-url', 'origin', token_url],
                            check=True
                        )
                        push_result = subprocess.run(
                            ['git', 'push'],
                            check=False,
                            capture_output=True,
                            text=True,
                            env=push_env
                        )
                        # Restore original URL (without token) for security
                        clean_url = remote_url.replace(f'{self.github_token}@', '') if '@' in remote_url else remote_url
                        if not clean_url.startswith('https://'):
                            clean_url = f'https://github.com/{repo_path}.git'
                        subprocess.run(
                            ['git', 'remote', 'set-url', 'origin', clean_url],
                            check=False
                        )
                        
                        # Check if token might be invalid
                        if push_result.returncode != 0:
                            error_output = push_result.stderr if push_result.stderr else push_result.stdout
                            if '403' in error_output or 'Permission denied' in error_output or 'denied' in error_output.lower():
                                logger.warning(f"   ⚠️  Authentication failed - check your GITHUB_TOKEN:")
                                logger.warning(f"      - Token must have 'repo' scope")
                                logger.warning(f"      - Token must be valid and not expired")
                                logger.warning(f"      - Set GITHUB_TOKEN in .env file")
                    else:
                        # Not GitHub, use regular push
                        push_result = subprocess.run(
                            ['git', 'push'],
                            check=False,
                            capture_output=True,
                            text=True,
                            env=push_env
                        )
                else:
                    # No token, try SSH
                    ssh_key = os.getenv('SSH_KEY_PATH', os.path.expanduser('~/.ssh/cyber64'))
                    if os.path.exists(ssh_key):
                        push_env['GIT_SSH_COMMAND'] = f'ssh -i {ssh_key} -o IdentitiesOnly=yes'
                    
                    push_result = subprocess.run(
                        ['git', 'push'],
                        check=False,
                        capture_output=True,
                        text=True,
                        env=push_env
                    )
                
                if push_result.returncode == 0:
                    logger.info(f"   ✓ Pushed to remote")
                    logger.info(f"   ✅ Git sync complete!")
                else:
                    error_msg = push_result.stderr if push_result.stderr else push_result.stdout
                    logger.warning(f"   ⚠️  Git push failed: {error_msg}")
                    if not self.github_token:
                        logger.warning(f"   Set GITHUB_TOKEN in .env file for automatic authentication")
                        logger.warning(f"   Or manually run: eval $(ssh-agent) && ssh-add ~/.ssh/cyber64")
                    elif '403' in error_msg or 'Permission denied' in error_msg or 'denied' in error_msg.lower():
                        logger.warning(f"   Authentication issue detected:")
                        logger.warning(f"   - Verify GITHUB_TOKEN has 'repo' scope")
                        logger.warning(f"   - Check token hasn't expired")
                        logger.warning(f"   - Ensure token has access to bitcoin_large_op_returns repository")
                    logger.warning(f"   Manual push: cd {self.submodule_root} && git push")
                
            finally:
                os.chdir(original_cwd)
                
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            logger.warning(f"   ⚠️  Git sync failed: {error_msg}")
            logger.warning(f"   You may need to manually commit and push changes")
        except Exception as e:
            logger.warning(f"   ⚠️  Error during git sync: {e}")
            logger.warning(f"   You may need to manually commit and push changes")

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Scan Bitcoin blocks for OP_RETURN data > 83 bytes',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Scan a single block:
    python op_return_scanner.py 917963
  
  Scan a range of blocks:
    python op_return_scanner.py 917963 918000
  
  Auto-continue from last scan:
    python op_return_scanner.py --continue
  
  Scan backwards from first scan (1 month earlier):
    python op_return_scanner.py --backwards
  
  Show statistics without scanning:
    python op_return_scanner.py --stats
  
  Reinterpret file types (update 'binary' files with new detection):
    python op_return_scanner.py --reinterpret
    python op_return_scanner.py --reinterpret text
  
  Re-scan all blocks with large OP_RETURNs (to add fee tracking, etc.):
    python op_return_scanner.py --rescan_large_op_returns
  
  Regenerate timeline_data.json from existing data:
    python op_return_scanner.py --regenerate-timeline-data-json
  
  Continual scanning (check every 60 seconds for new blocks):
    python op_return_scanner.py --continual-scanning --interval 60
  
  Continual scanning with custom interval:
    python op_return_scanner.py --continual-scanning --interval 120
  
  Test notification system with a specific block:
    python op_return_scanner.py --test-notification-block 924616
  
  Sync filesystem data to database (all blocks):
    python op_return_scanner.py --sync-filesystem-to-db
  
  Sync filesystem data to database (specific block):
    python op_return_scanner.py --sync-filesystem-to-db 920661
  
  RPC-only mode (check blocks without saving):
    python op_return_scanner.py 924617 925147 --rpc-only
  
  BIP-only mode (only detect BIP signaling, skip OP_RETURN scanning):
    python op_return_scanner.py 924617 925147 --bip-only
        """
    )
    parser.add_argument('start_block', type=int, nargs='?', help='Starting block number')
    parser.add_argument('end_block', type=int, nargs='?', help='Ending block number (optional, defaults to current height)')
    parser.add_argument('--output', '-o', default='bitcoin_large_op_returns/op_return_data', help='Output directory (default: bitcoin_large_op_returns/op_return_data)')
    parser.add_argument('--continue', '-c', dest='auto_continue', action='store_true', 
                       help='Continue forward from last scanned block')
    parser.add_argument('--backwards', '-b', action='store_true',
                       help='Scan backwards from first scanned block (~1 month, 4320 blocks)')
    parser.add_argument('--stats', '-s', action='store_true', 
                       help='Show statistics and exit')
    parser.add_argument('--reinterpret', '-r', nargs='?', const='binary', default=None, metavar='TYPE',
                       help='Reinterpret existing OP_RETURNs with specified file type (default: binary)')
    parser.add_argument('--rescan_large_op_returns', action='store_true',
                       help='Re-scan all blocks that have large OP_RETURNs (to update with new features like fee tracking)')
    parser.add_argument('--no-db', action='store_true', 
                       help='Disable database storage (files only)')
    parser.add_argument('--auto-sync-git', action='store_true',
                       help='Automatically commit and push changes to git submodule (can also set OP_RETURN_AUTO_SYNC_GIT=true)')
    parser.add_argument('--no-auto-sync-git', action='store_true',
                       help='Disable automatic git sync (overrides environment variable)')
    parser.add_argument('--regenerate-timeline-data-json', action='store_true',
                       help='Regenerate timeline_data.json from existing OP_RETURN data and exit')
    parser.add_argument('--continual-scanning', action='store_true',
                       help='Continuously scan for new blocks (requires database mode)')
    parser.add_argument('--interval', type=int, default=60, metavar='SECONDS',
                       help='Interval in seconds between scans when using --continual-scanning (default: 60)')
    parser.add_argument('--heartbeat', type=int, default=3600, metavar='SECONDS',
                       help='Interval in seconds between heartbeat messages when using --continual-scanning (default: 3600 = 1 hour)')
    parser.add_argument('--test-notification-block', type=int, metavar='BLOCK_NUMBER',
                       help='Test notification system by sending a notification for the first OP_RETURN in the specified block')
    parser.add_argument('--sync-filesystem-to-db', type=int, nargs='?', const=None, metavar='BLOCK_NUMBER',
                       help='Sync OP_RETURN data from filesystem to database (optionally specify a block number, or sync all blocks)')
    parser.add_argument('--rpc-only', action='store_true',
                       help='RPC-only mode: Check blocks via RPC and report findings without database or filesystem operations')
    parser.add_argument('--bip-only', action='store_true',
                       help='BIP-only mode: Only detect BIP signaling, skip OP_RETURN scanning (faster for BIP detection)')
    
    args = parser.parse_args()
    
    try:
        auto_sync = args.auto_sync_git if args.auto_sync_git else (False if args.no_auto_sync_git else None)
        scanner = OPReturnScanner(output_dir=args.output, use_database=not args.no_db, auto_sync_git=auto_sync)
        
        # Show stats and exit
        if args.stats:
            if not args.no_db:
                stats = scanner.get_scan_statistics()
                print("\n📊 OP_RETURN Scan Statistics")
                print("=" * 50)
                print(f"Total blocks scanned:     {stats['total_blocks_scanned']}")
                print(f"Total large OP_RETURNs:   {stats['total_large_op_returns']}")
                if stats['first_block']:
                    print(f"Block range:              {stats['first_block']} - {stats['last_block']}")
                print(f"Average per block:        {stats['avg_per_block']:.2f}")
                print()
            else:
                logger.error("Stats require database mode (don't use --no-db)")
            return 0
        
        # Reinterpret file types and exit
        if args.reinterpret is not None:
            if not args.no_db:
                scanner.reinterpret_file_types(args.reinterpret)
            else:
                logger.error("Reinterpretation requires database mode (don't use --no-db)")
            return 0
        
        # Re-scan all blocks with large OP_RETURNs and exit
        if args.rescan_large_op_returns:
            if not args.no_db:
                scanner.rescan_large_op_returns()
            else:
                logger.error("Re-scanning requires database mode (don't use --no-db)")
            return 0
        
        # Regenerate timeline_data.json and exit
        if args.regenerate_timeline_data_json:
            scanner.regenerate_timeline_data()
            return 0
        
        # Sync filesystem to database mode
        if args.sync_filesystem_to_db is not None:
            if args.no_db:
                logger.error("Filesystem sync requires database mode (don't use --no-db)")
                return 1
            block_num = args.sync_filesystem_to_db if args.sync_filesystem_to_db else None
            synced = scanner.sync_filesystem_to_database(block_number=block_num, verify_with_node=True)
            return 0 if synced >= 0 else 1
        
        # Test notification mode
        if args.test_notification_block is not None:
            if args.no_db:
                logger.error("Test notification requires database mode (don't use --no-db)")
                return 1
            success = scanner.test_notification(args.test_notification_block)
            return 0 if success else 1
        
        # Continual scanning mode
        if args.continual_scanning:
            if args.no_db:
                logger.error("Continual scanning requires database mode (don't use --no-db)")
                return 1
            scanner.continual_scan(interval_seconds=args.interval, heartbeat_interval=args.heartbeat)
            return 0
        
        # RPC-only mode
        if args.rpc_only:
            if args.start_block is None:
                parser.error("start_block is required when using --rpc-only")
                return 1
            result = scanner.scan_blocks_rpc_only(args.start_block, args.end_block)
            return 0
        
        # Require start_block unless using --continue or --backwards
        if not args.auto_continue and not args.backwards and args.start_block is None:
            parser.error("start_block is required unless using --continue or --backwards")
        
        # Set default start block for auto-continue or backwards
        if args.auto_continue or args.backwards:
            if args.start_block is None:
                args.start_block = 0  # Will be overridden by auto_continue or backwards
        
        result = scanner.scan_blocks(args.start_block, args.end_block, 
                          auto_continue=args.auto_continue, 
                          backwards=args.backwards,
                          bip_only=args.bip_only)
        
        # Handle return value (may be tuple or int for backwards compatibility)
        if isinstance(result, tuple):
            total_found, found_items = result
        else:
            total_found = result
    except Exception as e:
        logger.error(f"Scanner failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())

