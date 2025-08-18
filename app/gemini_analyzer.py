import google.generativeai as genai
import os
import logging
from typing import List, Dict, Optional, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class GeminiAnalyzer:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("API ключ Gemini не предоставлен.")
        try:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-1.5-flash-latest')
            logger.info("Gemini API успешно сконфигурирован.")
        except Exception as e:
            logger.error(f"Ошибка конфигурации Gemini API: {e}")
            raise ConnectionError(f"Не удалось сконфигурировать Gemini API: {e}")

    def analyze_reviews(self, reviews: List[str], product_name: str = "товар") -> Tuple[Optional[Dict[str, List[str]]], Optional[str]]:
        if not reviews:
            return None, "Список отзывов пуст для анализа."

        full_reviews_text = "\n\n".join([f"Отзыв {i+1}: {review}" for i, review in enumerate(reviews)])
        
        max_len = 250000
        if len(full_reviews_text) > max_len:
            original_len = len(full_reviews_text)
            full_reviews_text = full_reviews_text[:max_len]
            logger.warning(f"Текст отзывов (исходная длина: {original_len}) был обрезан до {max_len} символов для отправки в Gemini.")

        prompt = f"""
        Проанализируй следующие отзывы о товаре '{product_name}'.
        Твоя задача - внимательно прочитать все отзывы и выделить основные положительные (Плюсы) и отрицательные (Минусы) моменты, которые часто упоминаются пользователями.
        Сгруппируй схожие по смыслу утверждения. Избегай перечисления каждого мелкого замечания, если оно не является массовым.
        Сосредоточься на наиболее значимых и повторяющихся аспектах.

        Представь результат в следующем формате:
        Плюсы:
        - [Главный плюс 1]
        - [Главный плюс 2]
        ...

        Минусы:
        - [Главный минус 1]
        - [Главный минус 2]
        ...

        Если какие-то аспекты не упоминаются или отзывы неинформативны, укажи "Не найдено" в соответствующей секции.

        Отзывы:
        {full_reviews_text}
        """

        try:
            logger.info(f"Отправка запроса к Gemini API для анализа '{product_name}' (длина текста: {len(full_reviews_text)} символов)...")
            response = self.model.generate_content(prompt)
            
            if not response.candidates or not response.candidates[0].content.parts:
                 logger.error("Ответ Gemini не содержит ожидаемой структуры.")
                 return None, "Не удалось получить структурированный ответ от Gemini."

            analysis_text = response.text
            logger.info("Ответ от Gemini получен.")
            
            pros = []
            cons = []
            current_section = None

            for line in analysis_text.split('\n'):
                line = line.strip()
                if line.lower().startswith("плюсы:"):
                    current_section = "pros"
                    continue
                elif line.lower().startswith("минусы:"):
                    current_section = "cons"
                    continue
                
                if line.startswith("- ") and current_section:
                    item = line[2:].strip()
                    if item:
                        if current_section == "pros":
                            pros.append(item)
                        elif current_section == "cons":
                            cons.append(item)
            
            if not pros and not cons and "не найдено" not in analysis_text.lower():
                 logger.warning(f"Не удалось извлечь структурированные плюсы и минусы из ответа Gemini для '{product_name}'. Ответ: {analysis_text[:200]}...")
                 return {"pros": ["Не удалось структурировать ответ Gemini."], "cons": [analysis_text.strip() if analysis_text.strip() else "Ответ Gemini пуст."]}, None

            return {"pros": pros, "cons": cons}, None

        except Exception as e:
            logger.error(f"Ошибка при взаимодействии с Gemini API для '{product_name}': {e}")
            if "API key not valid" in str(e) or "PERMISSION_DENIED" in str(e).upper():
                 return None, "Ошибка API: Недействительный или заблокированный API ключ Gemini."
            if "content" in str(e).lower() and ("size" in str(e).lower() or "limit" in str(e).lower()):
                return None, f"Ошибка Gemini API: Возможно, превышен лимит размера входных данных. {e}"
            return None, f"Ошибка Gemini API: {e}"

if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv(dotenv_path='../.env')
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Ошибка: GEMINI_API_KEY не найден в .env.")
    else:
        analyzer = GeminiAnalyzer(api_key=api_key)
        sample_reviews_large = [f"Это очень хороший отзыв номер {i}, всем советую, товар просто супер, качество отличное, доставка быстрая, упаковка целая, цвет соответствует." for i in range(200)]
        sample_reviews_large.append("А вот этот телефон быстро разряжается, хотя камера снимает неплохо, но экран мог бы быть и поярче, зато цена приемлемая.")
        sample_reviews_large.append("Ужасный товар, сломался на второй день, никому не советую, деньги на ветер, продавец обманщик, не покупайте здесь ничего.")
        
        result, error = analyzer.analyze_reviews(sample_reviews_large, product_name="Тестовый Товар (много отзывов)")
        
        if error:
            print(f"Ошибка анализа: {error}")
        elif result:
            print("Анализ завершен:")
            print("\nПлюсы:")
            for pro in result.get("pros", []):
                print(f"- {pro}")
            
            print("\nМинусы:")
            for con in result.get("cons", []):
                print(f"- {con}")
        else:
            print("Не удалось получить результат анализа.")