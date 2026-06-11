#!/usr/bin/env python3
"""
Simple script to run the translation application
"""

import subprocess
import sys
import os

# Configure stdout/stderr to use utf-8 to avoid encoding crashes on CP932 terminals
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

def run_app():
    """Run the translation application"""
    try:
        # Determine directory layout
        in_root = os.path.exists('main.py') and os.path.exists('core') and os.path.exists('ui')
        in_parent = os.path.exists('translation_app')

        if not (in_root or in_parent):
            print("❌ Error: translation_app files or directory not found!")
            print("Please run this script from the project root directory or its parent directory.")
            return False

        req_path = 'requirements.txt' if in_root else 'translation_app/requirements.txt'
        run_args = [sys.executable, 'main.py'] if in_root else [sys.executable, '-m', 'translation_app']

        # Install dependencies if requirements.txt exists
        if os.path.exists(req_path):
            print("📦 Installing dependencies...")
            result = subprocess.run([
                sys.executable, '-m', 'pip', 'install', '-r', req_path
            ], capture_output=True, text=True)

            if result.returncode != 0:
                print("⚠️ Warning: Could not install dependencies automatically")
                print(f"Please run: pip install -r {req_path}")

        # Run the application
        print("🚀 Starting Translation Application...")
        subprocess.run(run_args)

        return True

    except KeyboardInterrupt:
        print("\n👋 Application closed by user")
        return True
    except Exception as e:
        print(f"❌ Error running application: {e}")
        return False

if __name__ == "__main__":
    success = run_app()
    if not success:
        sys.exit(1)
