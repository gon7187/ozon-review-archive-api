import customtkinter as ctk
from app.gui import App
from dotenv import load_dotenv
import os
import logging

logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.StreamHandler(),
                    ])

logger = logging.getLogger(__name__)

def main():
    logger.info("Запуск приложения WB Review Analyzer.")
    load_dotenv()
    gemini_api_key = os.getenv("GEMINI_API_KEY")

    if not gemini_api_key:
        logger.warning("GEMINI_API_KEY не найден. Функциональность Gemini будет недоступна или приведет к ошибке в GUI.")

    ctk.set_appearance_mode("dark") 
    
    try:
        app = App(gemini_api_key=gemini_api_key)
        if not app.winfo_exists():
            logger.error("Окно приложения не было создано. Проверьте лог на наличие ошибок инициализации.")
            return
        app.mainloop()
    except Exception as e:
        logger.critical(f"Необработанное исключение на верхнем уровне: {e}", exc_info=True)
    
    logger.info("Приложение WB Review Analyzer завершило работу.")

if __name__ == "__main__":
    main()