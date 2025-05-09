# WB Product Review Analyzer (Анализатор отзывов товаров на WB)

Проект для анализа отзывов на товары с Wildberries с использованием Gemini API для структурирования положительных и отрицательных моментов. Приложение имеет графический интерфейс, выполненный в строгом черно-белом дизайне.

## Особенности

*   Получение отзывов о товаре с Wildberries по ID или URL товара.
*   Анализ текста отзывов с помощью Google Gemini API.
*   Структурированное представление плюсов и минусов товара.
*   Графический интерфейс на CustomTkinter.
*   Строгий черно-белый дизайн с элементами анимации загрузки.

## Стек технологий

*   Python 3.x
*   CustomTkinter (для GUI)
*   Requests (для HTTP-запросов к WB)
*   Google Generative AI (Gemini API)
*   python-dotenv (для управления переменными окружения)

## Установка

1.  **Клонируйте репозиторий:**
    ```bash
    git clone https://github.com/ReNothingg/WBcheker.git
    cd wb_analyzer
    ```

2.  **Создайте и активируйте виртуальное окружение (рекомендуется):**
    ```bash
    python -m venv venv
    # Windows
    venv\Scripts\activate
    # macOS/Linux
    source venv/bin/activate
    ```

3.  **Установите зависимости:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Настройте переменные окружения:**
    Скопируйте файл `.env.example` в `.env`:
    ```bash
    cp .env.example .env
    ```
    Откройте файл `.env` и вставьте ваш API ключ для Gemini:
    ```
    GEMINI_API_KEY="ВАШ_GOOGLE_GEMINI_API_KEY"
    ```
    Получить ключ можно на [Google AI Studio](https://aistudio.google.com/app/apikey).

## Запуск

Выполните команду из корневой папки проекта:

```bash
python main.py