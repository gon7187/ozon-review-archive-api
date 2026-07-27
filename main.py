import os
import logging
import sys
from pathlib import Path


def _restart_in_project_venv() -> None:
    """Use the prepared project environment even when main.py is run globally."""
    project_root = Path(__file__).resolve().parent
    venv_python = project_root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        return
    if Path(sys.executable).resolve() == venv_python.resolve():
        return
    os.execv(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]])


_restart_in_project_venv()

from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.StreamHandler(),
                    ])

logger = logging.getLogger(__name__)

def main():
    logger.info("Запуск Marketplace Review Analyzer.")
    load_dotenv()
    gemini_api_key = os.getenv("GEMINI_API_KEY")

    if not gemini_api_key:
        logger.error("GEMINI_API_KEY не найден в .env.")
        print("Добавьте GEMINI_API_KEY в файл .env и повторите запуск.")
        return

    try:
        import customtkinter as ctk
        from app.gui import App
    except ModuleNotFoundError as exc:
        if exc.name == "_tkinter":
            print(
                "В Python отсутствует Tk. Для Homebrew Python 3.14 выполните:\n"
                "  brew install python-tk@3.14\n"
                "Затем снова запустите приложение."
            )
            return
        raise

    ctk.set_appearance_mode("dark") 
    
    try:
        app = App(gemini_api_key=gemini_api_key)
        if not app.winfo_exists():
            logger.error("Окно приложения не было создано. Проверьте лог на наличие ошибок инициализации.")
            return
        app.mainloop()
    except Exception as e:
        logger.critical(f"Необработанное исключение на верхнем уровне: {e}", exc_info=True)
    
    logger.info("Marketplace Review Analyzer завершил работу.")

if __name__ == "__main__":
    main()
