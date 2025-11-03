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
        shutil.rmtree("build")
    if os.path.exists("dist"):
        print("Cleaning dist directory...")
        shutil.rmtree("dist")
    
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
    print("\nNote: Playwright browsers may need to be installed separately.")
    print("The EXE will attempt to use Playwright if available, otherwise it will fall back to HTTP requests.")
    print("\nTo test the EXE:")
    print(f"  1. Navigate to: {exe_path.parent.absolute()}")
    print("  2. Run: KackyWatcher.exe")
    print("  3. Check that settings.json, watchlist.txt, and map_status.json are created in the same directory")


if __name__ == "__main__":
    main()

