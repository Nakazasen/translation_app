#!/usr/bin/env python3
"""
Simple script to run the translation application
"""

import subprocess
import sys
import os

def run_app():
    """Run the translation application"""
    try:
        # Check if we're in the right directory
        if not os.path.exists('translation_app'):
            print("❌ Error: translation_app directory not found!")
            print("Please run this script from the parent directory of translation_app")
            return False

        # Install dependencies if requirements.txt exists
        if os.path.exists('translation_app/requirements.txt'):
            print("📦 Installing dependencies...")
            result = subprocess.run([
                sys.executable, '-m', 'pip', 'install', '-r', 'translation_app/requirements.txt'
            ], capture_output=True, text=True)

            if result.returncode != 0:
                print("⚠️ Warning: Could not install dependencies automatically")
                print("Please run: pip install -r translation_app/requirements.txt")

        # Run the application
        print("🚀 Starting Translation Application...")
        subprocess.run([sys.executable, '-m', 'translation_app'])

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
