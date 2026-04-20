#!/usr/bin/env python
"""
Quick setup script for Biogas Telegram Bot.
Run this after cloning the repository.
"""
import os
import sys
import subprocess
from pathlib import Path


def run_command(cmd, description):
    """Run a command and print status."""
    print(f"\n{'='*60}")
    print(f"→ {description}")
    print(f"{'='*60}")
    print(f"$ {' '.join(cmd)}")
    
    result = subprocess.run(cmd, shell=True)
    
    if result.returncode != 0:
        print(f"❌ Failed: {description}")
        sys.exit(1)
    
    print(f"✅ Success: {description}")


def main():
    print("\n" + "="*60)
    print("  Biogas Telegram Bot - Setup Script")
    print("="*60)
    
    # Check Python version
    print(f"\nPython version: {sys.version}")
    if sys.version_info < (3, 11):
        print("⚠️  Warning: Python 3.11+ recommended")
    
    # Create virtual environment
    if not Path("venv").exists():
        run_command([sys.executable, "-m", "venv", "venv"], 
                   "Creating virtual environment")
    else:
        print("\n✅ Virtual environment already exists")
    
    # Determine pip path
    if os.name == 'nt':  # Windows
        pip_path = "venv\\Scripts\\pip.exe"
        python_path = "venv\\Scripts\\python.exe"
    else:  # Unix
        pip_path = "venv/bin/pip"
        python_path = "venv/bin/python"
    
    # Install dependencies
    run_command([pip_path, "install", "--upgrade", "pip"],
               "Upgrading pip")
    
    run_command([pip_path, "install", "-r", "requirements.txt"],
               "Installing dependencies")
    
    # Create .env if not exists
    if not Path(".env").exists():
        if Path(".env.example").exists():
            import shutil
            shutil.copy(".env.example", ".env")
            print("\n✅ Created .env from .env.example")
            print("⚠️  Please edit .env with your configuration")
        else:
            print("\n❌ .env.example not found")
            sys.exit(1)
    else:
        print("\n✅ .env already exists")
    
    # Create logs directory
    Path("logs").mkdir(exist_ok=True)
    print("\n✅ Logs directory created")
    
    # Run migrations
    run_command([python_path, "manage.py", "makemigrations"],
               "Creating database migrations")
    
    run_command([python_path, "manage.py", "migrate"],
               "Running database migrations")
    
    # Create superuser prompt
    print("\n" + "="*60)
    print("  Setup Complete!")
    print("="*60)
    print("\nNext steps:")
    print("1. Edit .env with your configuration")
    print("2. Create admin user: python manage.py createsuperuser")
    print("3. Add credentials.json for Google Sheets")
    print("4. Run server: python manage.py runserver")
    print("5. Run tests: python manage.py test")
    print("\n📖 See README.md for full documentation")


if __name__ == "__main__":
    main()
