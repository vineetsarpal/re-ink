"""
Debug entry point for FastAPI application.
This script starts the FastAPI server with debugpy enabled for interactive debugging.
"""
import debugpy
import uvicorn
import os
import sys
from pathlib import Path

# Add the backend directory to the Python path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

# Clear conflicting environment variables that might interfere with .env file
# This allows .env file values to take precedence
if "DEBUG" in os.environ:
    print(f"Warning: Removing system DEBUG={os.environ['DEBUG']} to use .env file value")
    del os.environ["DEBUG"]

# Debugger configuration
DEBUG_PORT = int(os.getenv("DEBUG_PORT", "5678"))
WAIT_FOR_CLIENT = os.getenv("WAIT_FOR_DEBUGGER", "false").lower() == "true"

def main():
    """Start the FastAPI server with debugging enabled."""
    # Start debugpy server
    print(f"Starting debugpy on port {DEBUG_PORT}")
    print(f"Waiting for debugger: {WAIT_FOR_CLIENT}")
    
    debugpy.listen(("0.0.0.0", DEBUG_PORT))
    
    if WAIT_FOR_CLIENT:
        print("Waiting for debugger to attach...")
        debugpy.wait_for_client()
        print("Debugger attached!")
    
    # Import settings to check DEBUG mode
    from app.core.config import settings
    
    # Start uvicorn server
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # Enable auto-reload for development
        reload_dirs=[str(backend_dir / "app")],  # Only watch app directory
        log_level="info" if settings.DEBUG else "warning"
    )

if __name__ == "__main__":
    main()

