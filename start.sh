#!/bin/bash
# Startup script with error logging
echo "=== Starting Faceless Video Generator ==="
echo "Python version: $(python --version 2>&1)"
echo "Working directory: $(pwd)"
echo "Listing files:"
ls -la
echo "---"

# Try to import and report errors
python -c "
import sys
print(f'Python: {sys.version}')
try:
    from app.main import app
    print('✅ App imported successfully')
except Exception as e:
    print(f'❌ Import error: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)
" 2>&1

if [ $? -ne 0 ]; then
    echo "=== IMPORT FAILED ==="
    # Keep the container alive so we can see logs
    sleep 30
    exit 1
fi

echo "=== Starting uvicorn ==="
exec uvicorn app.main:app --host 0.0.0.0 --port $PORT
