"""
Main entry point when running as a module: python -m translation_app
"""
import os
import sys
import traceback
import threading
from tkinter import messagebox

# Add the current directory's parent to sys.path to enable module imports when run directly
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from translation_app.utils.logger import setup_logging, logger
from translation_app.config import config
from translation_app.ui.main_window import MainWindow


def main():
    """Main application entry point"""
    try:
        # Initialize logging
        setup_logging(config.log_level)
        logger.info("=" * 60)
        logger.info("Translation Application Starting")
        logger.info("=" * 60)

        import threading
        from translation_app.utils.update_service import check_for_updates, perform_update

        # Create and run main window
        app = MainWindow()

        # Check for updates after window is shown
        def delayed_update_check():
            update_info = check_for_updates()
            if update_info:
                app.after(500, lambda: perform_update(update_info))
        
        # Run update check in a separate thread to not block UI startup
        threading.Thread(target=delayed_update_check, daemon=True).start()

        # Setup close handler
        app.protocol("WM_DELETE_WINDOW", app.on_closing)

        # Start main loop
        logger.info("Starting main event loop")
        app.mainloop()

        logger.info("Application closed normally")

    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
        sys.exit(0)
    except Exception as e:
        error_msg = f"Fatal error: {e}"
        logger.critical(error_msg, exc_info=True)
        traceback.print_exc()

        # Show error dialog if possible
        try:
            messagebox.showerror(
                "Lỗi nghiêm trọng",
                f"Đã xảy ra lỗi nghiêm trọng:\n{error_msg}\n\n"
                f"Vui lòng kiểm tra file log để biết thêm chi tiết."
            )
        except Exception:
            # If messagebox fails, print to console
            print(f"ERROR: {error_msg}")

        sys.exit(1)
    finally:
        # Cleanup
        logger.info("Application cleanup completed")


if __name__ == "__main__":
    main()
