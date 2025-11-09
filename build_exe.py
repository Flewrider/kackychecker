"""
Build script for creating Kacky Watcher EXE.
This script helps with local testing and ensures all dependencies are included.
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path


def main():
    """Build the EXE using PyInstaller."""
    print("Building Kacky Watcher EXE...")
    
    # Clean previous builds
    if os.path.exists("build"):
        print("Cleaning build directory...")
        try:
            shutil.rmtree("build")
        except PermissionError as e:
            print(f"Warning: Could not delete build directory: {e}")
            print("This is usually fine - PyInstaller will handle cleanup.")
    
    if os.path.exists("dist"):
        print("Cleaning dist directory...")
        try:
            shutil.rmtree("dist")
        except PermissionError as e:
            print(f"Warning: Could not delete dist directory: {e}")
            print("The KackyWatcher.exe may be running. Please close it and try again.")
            print("Alternatively, PyInstaller's --clean flag should handle this.")
            # Ask user if they want to continue
            response = input("Continue anyway? (y/n): ").strip().lower()
            if response != 'y':
                print("Build cancelled.")
                sys.exit(1)
    
    # Check if PyInstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("ERROR: PyInstaller is not installed.")
        print("Install it with: pip install pyinstaller")
        sys.exit(1)
    
    # Run PyInstaller
    print("Running PyInstaller...")
    result = subprocess.run(
        [
            sys.executable,
            "-m", "PyInstaller",
            "kacky_watcher.spec",
            "--clean",
            "--noconfirm"
        ],
        check=False
    )
    
    if result.returncode != 0:
        print("ERROR: PyInstaller failed!")
        sys.exit(1)
    
    # Check if EXE was created
    exe_path = Path("dist/KackyWatcher.exe")
    if not exe_path.exists():
        print("ERROR: EXE was not created!")
        sys.exit(1)
    
    print(f"\n✓ Build successful! EXE created at: {exe_path.absolute()}")
    print("\nNote: Playwright browsers are NOT bundled in the EXE.")
    print("The app will prompt users to install Playwright browsers on first run (~100-200MB download).")
    print("\nTo test the EXE:")
    print(f"  1. Navigate to: {exe_path.parent.absolute()}")
    print("  2. Run: KackyWatcher.exe")
    print("  3. The app will prompt you to install Playwright browsers (required)")
    print("  4. Check that settings.json, watchlist.txt, and map_status.json are created in the same directory")


if __name__ == "__main__":
    main()

