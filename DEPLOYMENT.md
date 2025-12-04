# OP_RETURN Scanner Deployment Guide

This guide covers multiple options for keeping the `op_return_scanner.py` script running continuously on a Linux container/server.

## Prerequisites

1. Ensure the virtual environment is set up:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. Ensure `.env` file is configured with:
   - `BTC_RPC_HOST`
   - `BTC_RPC_PORT`
   - `BTC_RPC_USER`
   - `BTC_RPC_PASSWORD`
   - Database connection settings
   - Notification settings (optional)

3. Create logs directory:
   ```bash
   mkdir -p logs
   ```

## Option 1: systemd Service (Recommended for Linux servers)

### Setup

1. Copy the service file:
   ```bash
   sudo cp op_return_scanner.service /etc/systemd/system/
   ```

2. Edit the service file to match your paths:
   ```bash
   sudo nano /etc/systemd/system/op_return_scanner.service
   ```
   
   Update these paths if different:
   - `User=ubuntu` → your username
   - `WorkingDirectory=/home/ubuntu/crypto_basis` → your project path
   - `ExecStart=/home/ubuntu/crypto_basis/venv/bin/python3` → your venv python path

3. Reload systemd and enable the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable op_return_scanner.service
   sudo systemctl start op_return_scanner.service
   ```

### Management Commands

```bash
# Check status
sudo systemctl status op_return_scanner.service

# View logs
sudo journalctl -u op_return_scanner.service -f

# Stop the service
sudo systemctl stop op_return_scanner.service

# Restart the service
sudo systemctl restart op_return_scanner.service

# Disable auto-start on boot
sudo systemctl disable op_return_scanner.service
```

## Option 2: Supervisor (Good for containers without systemd)

### Installation

```bash
sudo apt-get update
sudo apt-get install supervisor
```

### Setup

1. Copy the supervisor config:
   ```bash
   sudo cp supervisord_op_return_scanner.conf /etc/supervisor/conf.d/op_return_scanner.conf
   ```

2. Edit the config file to match your paths:
   ```bash
   sudo nano /etc/supervisor/conf.d/op_return_scanner.conf
   ```

3. Create logs directory:
   ```bash
   mkdir -p /home/ubuntu/crypto_basis/logs
   ```

4. Reload and start:
   ```bash
   sudo supervisorctl reread
   sudo supervisorctl update
   sudo supervisorctl start op_return_scanner
   ```

### Management Commands

```bash
# Check status
sudo supervisorctl status op_return_scanner

# View logs
tail -f /home/ubuntu/crypto_basis/logs/op_return_scanner.log
tail -f /home/ubuntu/crypto_basis/logs/op_return_scanner_error.log

# Restart
sudo supervisorctl restart op_return_scanner

# Stop
sudo supervisorctl stop op_return_scanner

# Reload config after changes
sudo supervisorctl reread
sudo supervisorctl update
```

## Option 3: Wrapper Script with nohup

### Setup

1. Make the script executable:
   ```bash
   chmod +x run_op_return_scanner.sh
   ```

2. Edit the script to match your paths (if different from defaults)

3. Run with nohup:
   ```bash
   nohup ./run_op_return_scanner.sh > logs/wrapper.log 2>&1 &
   ```

4. Or add to crontab for auto-start on boot:
   ```bash
   crontab -e
   ```
   
   Add this line:
   ```
   @reboot /home/ubuntu/crypto_basis/run_op_return_scanner.sh >> /home/ubuntu/crypto_basis/logs/cron.log 2>&1
   ```

### Management

```bash
# Check if running
ps aux | grep op_return_scanner

# Stop (find PID and kill)
ps aux | grep op_return_scanner
kill <PID>

# Or kill by PID file
kill $(cat logs/op_return_scanner.pid)
```

## Option 4: Docker Restart Policy (If using Docker)

If you're running in a Docker container, add restart policy to your `docker-compose.yml` or `docker run` command:

### docker-compose.yml

```yaml
version: '3.8'
services:
  op_return_scanner:
    build: .
    restart: unless-stopped  # or 'always'
    environment:
      - BTC_RPC_HOST=${BTC_RPC_HOST}
      - BTC_RPC_PORT=${BTC_RPC_PORT}
      # ... other env vars
    volumes:
      - ./bitcoin_large_op_returns:/app/bitcoin_large_op_returns
      - ./logs:/app/logs
```

### docker run

```bash
docker run -d \
  --restart unless-stopped \
  --name op_return_scanner \
  -e BTC_RPC_HOST=... \
  # ... other options
  your-image:tag
```

Restart policies:
- `no` - Never restart (default)
- `always` - Always restart
- `on-failure` - Restart on failure
- `unless-stopped` - Restart unless manually stopped

## Monitoring

### Check if process is running

```bash
# For systemd
sudo systemctl is-active op_return_scanner.service

# For supervisor
sudo supervisorctl status op_return_scanner

# General check
ps aux | grep op_return_scanner.py
```

### View logs

```bash
# systemd
sudo journalctl -u op_return_scanner.service -n 100 -f

# supervisor
tail -f logs/op_return_scanner.log

# wrapper script
tail -f logs/op_return_scanner.log
tail -f logs/op_return_scanner_error.log
```

### Health check script

Create a simple health check:

```bash
#!/bin/bash
# health_check.sh

if pgrep -f "op_return_scanner.py.*--continual-scanning" > /dev/null; then
    echo "OK: Scanner is running"
    exit 0
else
    echo "ERROR: Scanner is not running"
    exit 1
fi
```

Run periodically with cron:
```bash
*/5 * * * * /home/ubuntu/crypto_basis/health_check.sh || systemctl restart op_return_scanner.service
```

## Troubleshooting

### Service won't start

1. Check logs:
   ```bash
   sudo journalctl -u op_return_scanner.service -n 50
   ```

2. Verify paths in service file are correct

3. Check permissions:
   ```bash
   ls -la /home/ubuntu/crypto_basis/venv/bin/python3
   ```

4. Test manually:
   ```bash
   cd /home/ubuntu/crypto_basis
   source venv/bin/activate
   python3 op_return_scanner.py --continual-scanning --interval 60 --heartbeat 360
   ```

### Process keeps restarting

1. Check error logs for the root cause
2. Verify database connection
3. Verify Bitcoin RPC connection
4. Check disk space: `df -h`
5. Check memory: `free -h`

### Permission errors

```bash
# Fix ownership
sudo chown -R ubuntu:ubuntu /home/ubuntu/crypto_basis

# Fix permissions
chmod +x run_op_return_scanner.sh
chmod +x venv/bin/python3
```

## Recommended Setup

For a production Linux server, **Option 1 (systemd)** is recommended because:
- Automatic restart on failure
- Automatic start on boot
- Integrated logging with journalctl
- Resource limits
- Better process management

For containers without systemd, use **Option 2 (supervisor)** or **Option 4 (Docker restart policy)**.

