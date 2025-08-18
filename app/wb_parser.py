import requests
import re
import logging
from typing import List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CARD_URL_TEMPLATE = "https://card.wb.ru/cards/v1/detail?appType=1&curr=rub&dest=-1257786&spp=30&nm={product_id}"
FEEDBACK_URL_TEMPLATE_1 = "https://feedbacks1.wb.ru/feedbacks/v1/{imt_id}"
FEEDBACK_URL_TEMPLATE_2 = "https://feedbacks2.wb.ru/feedbacks/v1/{imt_id}"

COMMON_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
    'Origin': 'https://www.wildberries.ru',
    'Referer': 'https://www.wildberries.ru/',
}

MAX_REVIEWS_PER_REQUEST = 5000

def get_product_id_from_url(url: str) -> Optional[str]:
    match = re.search(r"/catalog/(\d+)/detail\.aspx", url)
    if match:
        return match.group(1)
    if url.isdigit():
        return url
    logger.warning(f"Не удалось извлечь ID товара из URL: {url}")
    return None

def fetch_product_data_and_reviews(product_id: str, reviews_limit: int = 200) -> Tuple[Optional[List[str]], Optional[str], Optional[str]]:
    if not product_id:
        return None, None, "ID товара не предоставлен."

    card_url = CARD_URL_TEMPLATE.format(product_id=product_id)
    logger.info(f"Запрос данных о товаре: {card_url}")
    product_name_default = f"Товар ID {product_id}"
    product_name = product_name_default
    imt_id = None
    feedbacks_count_on_card = 0

    try:
        response_card = requests.get(card_url, headers=COMMON_HEADERS, timeout=10)
        response_card.raise_for_status()
        card_data = response_card.json()

        if not card_data.get("data") or not card_data["data"].get("products"):
            logger.warning(f"Не найдены данные для товара {product_id} в ответе от card.wb.ru")
            return None, None, "Товар не найден или информация о нем неполная (ответ от card.wb.ru)."
        
        product_info_list = card_data["data"]["products"]
        if not product_info_list:
            logger.warning(f"Список продуктов пуст для товара {product_id} в ответе от card.wb.ru")
            return None, None, "Товар не найден (пустой список продуктов от card.wb.ru)."

        product_info = product_info_list[0]
        imt_id = product_info.get("root")
        product_name = product_info.get("name", product_name_default)
        feedbacks_count_on_card = product_info.get("feedbacks", 0)

        if not imt_id:
            logger.warning(f"Не удалось получить imt_id (root) для товара {product_id}")
            return None, product_name, "Не удалось получить внутренний ID товара для загрузки отзывов."
        
        logger.info(f"Получен imt_id: {imt_id}, название: '{product_name}', заявлено отзывов: {feedbacks_count_on_card}")
        
        if feedbacks_count_on_card == 0:
            logger.info(f"На карточке товара '{product_name}' (ID: {product_id}) указано 0 отзывов.")
            return [], product_name, None

    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка сети при получении данных о товаре {product_id}: {e}")
        return None, None, f"Ошибка сети (карточка товара): {e}"
    except (ValueError, KeyError, IndexError) as e:
        logger.error(f"Ошибка парсинга JSON или структуры ответа для карточки товара {product_id}: {e}")
        return None, None, f"Ошибка ответа сервера (карточка товара): {e}"

    all_review_texts = []

    feedback_urls_to_try = [
        FEEDBACK_URL_TEMPLATE_1.format(imt_id=imt_id),
        FEEDBACK_URL_TEMPLATE_2.format(imt_id=imt_id)
    ]
    
    fetched_successfully = False
    last_feedback_error = "Не удалось загрузить отзывы после нескольких попыток."

    for i, feedback_url in enumerate(feedback_urls_to_try):
        logger.info(f"Запрос отзывов (попытка {i+1}) для imt_id: {imt_id} с URL: {feedback_url}")
        try:
            response_feedback = requests.get(feedback_url, headers=COMMON_HEADERS, timeout=30) 
            response_feedback.raise_for_status()
            feedback_data = response_feedback.json()
            
            feedbacks_list = []
            if isinstance(feedback_data, dict):
                feedbacks_list = feedback_data.get("feedbacks", [])
            elif isinstance(feedback_data, list):
                feedbacks_list = feedback_data

            if not feedbacks_list:
                logger.warning(f"Список отзывов пуст для imt_id {imt_id} (URL: {feedback_url}).")
                last_feedback_error = f"Список отзывов пуст (URL: {feedback_url})."
                if i < len(feedback_urls_to_try) -1:
                    continue
                else:
                    if feedbacks_count_on_card > 0:
                        logger.warning(f"Отзывы были заявлены ({feedbacks_count_on_card}), но не получены.")
                    else:
                        fetched_successfully = True 
                    break 

            for feedback_item in feedbacks_list:
                text = feedback_item.get("text", "")
                if text and text.strip():
                    all_review_texts.append(text.strip())
            
            logger.info(f"Успешно обработаны отзывы с {feedback_url}. Получено {len(all_review_texts)} текстов.")
            fetched_successfully = True
            break

        except requests.exceptions.HTTPError as e:
            last_feedback_error = f"Ошибка HTTP {e.response.status_code} (отзывы с {feedback_url}): {e}"
            logger.warning(last_feedback_error)
            if e.response.status_code == 404 and i < len(feedback_urls_to_try) - 1:
                continue
            break 
        except requests.exceptions.Timeout:
            last_feedback_error = f"Тайм-аут при запросе отзывов с {feedback_url}"
            logger.error(last_feedback_error)
            if i == len(feedback_urls_to_try) -1: break
        except requests.exceptions.RequestException as e:
            last_feedback_error = f"Ошибка сети (отзывы с {feedback_url}): {e}"
            logger.error(last_feedback_error)
            if i == len(feedback_urls_to_try) -1: break
        except (ValueError, KeyError) as e:
            last_feedback_error = f"Ошибка данных/JSON (отзывы с {feedback_url}): {e}"
            logger.error(last_feedback_error)
            if i == len(feedback_urls_to_try) -1: break
    
    if not fetched_successfully and feedbacks_count_on_card > 0 and not all_review_texts:
        return None, product_name, last_feedback_error
    
    if not all_review_texts:
        if feedbacks_count_on_card > 0:
            logger.info(f"Для товара '{product_name}' (ID: {product_id}) не найдено текстовых отзывов, хотя они заявлены.")
            return [], product_name, "Отзывы найдены (или заявлены), но не содержат текста, либо не удалось их загрузить."
        else:
            logger.info(f"Для товара '{product_name}' (ID: {product_id}) текстовые отзывы отсутствуют (0 на карточке).")
            return [], product_name, None

    limited_reviews = all_review_texts[:reviews_limit]
    logger.info(f"Всего извлечено {len(all_review_texts)} текстовых отзывов. Отобрано для анализа: {len(limited_reviews)} для товара '{product_name}'.")
    return limited_reviews, product_name, None


if __name__ == '__main__':
    test_product_id = "224980546" 
    test_reviews_limit = 500 
    print(f"Тестирование с ID: {test_product_id}, лимит отзывов: {test_reviews_limit}")
    
    reviews, name, error = fetch_product_data_and_reviews(test_product_id, reviews_limit=test_reviews_limit)
    
    if error:
        print(f"Ошибка: {error}")
        if name:
            print(f"Название товара (если удалось получить): {name}")
    elif name and not reviews:
        print(f"Для товара '{name}' текстовые отзывы не найдены или отсутствуют.")
    elif reviews:
        print(f"Найдено {len(reviews)} отзывов для товара '{name}':")
    else:
        print("Неизвестный результат.")