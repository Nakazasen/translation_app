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
        # Determine base directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if os.path.exists(os.path.join(script_dir, 'main.py')):
            base_dir = script_dir
            req_file = os.path.join(base_dir, 'requirements.txt')
            main_script = os.path.join(base_dir, 'main.py')
        elif os.path.exists(os.path.join(script_dir, 'translation_app', 'main.py')):
            base_dir = os.path.join(script_dir, 'translation_app')
            req_file = os.path.join(base_dir, 'requirements.txt')
            main_script = os.path.join(base_dir, 'main.py')
        else:
            print("❌ Error: main.py not found in current directory or translation_app subdirectory!")
            return False

        # Ensure parent directory is accessible in sys.path
        parent_dir = os.path.dirname(base_dir)
        env = os.environ.copy()
        existing_pythonpath = env.get('PYTHONPATH', '')
        env['PYTHONPATH'] = f"{parent_dir};{existing_pythonpath}" if existing_pythonpath else parent_dir
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'

        # Install dependencies if requirements.txt exists
        if os.path.exists(req_file):
            print("📦 Checking dependencies...")
            result = subprocess.run([
                sys.executable, '-m', 'pip', 'install', '-r', req_file
            ], capture_output=True, text=True, cwd=base_dir)

            if result.returncode != 0:
                print("⚠️ Warning: Could not install dependencies automatically")
                print(f"Please run: pip install -r {req_file}")

        # Run the application
        print("🚀 Starting Translation Application...")
        subprocess.run([sys.executable, main_script], env=env, cwd=base_dir)

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
