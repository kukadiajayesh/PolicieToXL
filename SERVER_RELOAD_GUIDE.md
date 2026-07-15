# Server Reload Guide

## Quick Reload Commands

### Option 1: Kill and Restart (Complete Reload)

```bash
# Kill all running processes
pkill -f "python app.py"
pkill -f "npm run dev"

# Wait a moment
sleep 2

# Start fresh
cd /Users/harvi/Documents/Workspace/pdf_xl
source .venv/bin/activate
python app.py &

# In another terminal:
cd /Users/harvi/Documents/Workspace/pdf_xl/frontend
npm run dev
```

### Option 2: One-Line Reload Script

Save this as `reload.sh`:

```bash
#!/bin/bash
cd /Users/harvi/Documents/Workspace/pdf_xl
pkill -f "python app.py"
pkill -f "npm run dev"
sleep 2

# Start backend
source .venv/bin/activate
python app.py > /tmp/backend.log 2>&1 &

# Start frontend
cd frontend
npm run dev > /tmp/frontend.log 2>&1 &

echo "✓ Servers reloading..."
sleep 5

# Check status
curl -s http://localhost:5001/api/ollama/status | grep -q "ok" && echo "✓ Backend OK" || echo "✗ Backend failed"
curl -s http://localhost:5173/ | grep -q "Insurance" && echo "✓ Frontend OK" || echo "✗ Frontend failed"
```

Then run:
```bash
chmod +x reload.sh
./reload.sh
```

### Option 3: Using Claude Code `/run` Command

Simply use:
```
/run
```

This will detect and launch both the backend and frontend automatically.

## Check Server Status

### Backend (Flask)
- **URL**: http://localhost:5001
- **Health check**: `curl http://localhost:5001/api/ollama/status`

### Frontend (Vite)
- **URL**: http://localhost:5173
- **Logs**: Check `/tmp/frontend.log`

## View Logs

```bash
# Backend logs
tail -f /tmp/backend.log

# Frontend logs
tail -f /tmp/frontend.log
```

## Kill Servers Gracefully

```bash
# Kill just the backend
pkill -f "python app.py"

# Kill just the frontend
pkill -f "npm run dev"

# Kill both
pkill -f "python app.py"; pkill -f "npm run dev"
```

## Common Issues

### Port 5001 already in use
```bash
# Find process using port 5001
lsof -i :5001

# Kill the process
kill -9 <PID>
```

### Port 5173 already in use
```bash
# Find process using port 5173
lsof -i :5173

# Kill the process
kill -9 <PID>
```

### Frontend not updating
- Make sure you're hitting http://localhost:5173 (not 5001)
- Check that `npm run dev` is running (should see "VITE ready")
- Hard refresh the browser (Cmd+Shift+R on Mac, Ctrl+Shift+R on Windows)

## Currently Running

✓ Backend: http://localhost:5001  
✓ Frontend: http://localhost:5173
