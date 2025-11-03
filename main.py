"""
Main entry point for Kacky Watcher.
Launches GUI by default, or CLI if --cli flag is used.
"""
import sys

# Check command line arguments
if "--cli" in sys.argv or "-c" in sys.argv:
    # Run CLI mode
    from kacky_watcher import main
    main()
else:
    # Run GUI mode
    try:
        import tkinter
    except ImportError:
        print("Error: tkinter is not available. Install it or use --cli flag for console mode.")
        sys.exit(1)
    
    from gui import main
    main()

